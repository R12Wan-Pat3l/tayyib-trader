#!/usr/bin/env python3
"""tayyib-backtest: if you had run this strategy every day for the last N years, what happened?

Replays tayyib-daily day by day over the halal list with your capital and settings, using the same
functions the live pipeline uses (setups, liquidity, exit plan, ranking, sizing, the paper outcome rules
and Zerodha delivery charges):

  each close   scan every compliant stock on its bars up to that day only, pick and rank the day's
               stocks like tayyib-daily, size them against the cash left and place buy-stop plans
  next days    a plan fills when price trades through its entry (by its valid-until date), then exits at
               the stop, the target, breakeven or the time stop exactly like the paper tracker
  one account  one cash balance (never negative, no margin), one position per stock, at most
               --max-positions open or waiting, charges on every buy and sell

Writes trader/backtest/<id>.json and .md with --write, and nothing else (prices go to the usual cache).
A replay of the past with today's halal list: read the banners. Places no order.

  backtest.py run [--mode swing|delivery|all] [--setups breakout,pullback] [--years 3]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--capital N] [--max-positions 5]
                  [--split YYYY-MM-DD] [--write] [--json]
  backtest.py list
  backtest.py show ID
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

WARMUP_BARS = 250              # bars a stock needs before the window starts
TM_RUNS, TM_SEED = 3000, 7     # what tayyib-daily asks the time machine for (daily.py --runs, timemachine --seed)
TM_YEARS = 2                   # the time machine sees the stock's last 2 years (get_daily_bars' default range)
BENCHMARKS = (("SHARIABEES.NS", "Nippon India ETF Shariah BeES"),
              ("^NSEI", "Nifty 50 (price index: dividends not included)"))
SHARIAH_BENCH = "SHARIABEES.NS"
MIN_TRADES = 30

BANNER_HALAL = ("Halal status is today's list applied to past years (point-in-time halal data is not "
                "available).")
BANNER_SURVIVOR = ("Universe is today's list: companies that dropped out are missing (survivorship bias), so "
                   "results are likely better than reality.")
BANNER_PAST = "Past results do not predict future results. Not financial advice, not a fatwa."
BANNER_FEW = "Too few trades to judge."
BANNER_OVERFIT = "Out-of-sample results are much weaker: the strategy may be overfit."
BANNER_ETF = "Buying and holding the Shariah ETF did better."
BANNER_NO_ETF = ("The Shariah ETF benchmark is UNKNOWN (it could not be fetched), so the strategy could not be "
                 "compared with it.")
EXIT_AT_END = "OPEN AT END"


# ---------------------------------------------------------------------------
# Universe and data
# ---------------------------------------------------------------------------

def halal_universe(uni):
    """Compliant stocks after your overrides (tc.halal_status applies halal_overrides.json last, so overrides
    win). review, excluded and unknown are never traded, whatever halal.allow_review says.
    -> (sorted symbols, {status: count})."""
    syms, counts = [], {}
    for s in sorted((uni or {}).get("stocks") or {}):
        st = tc.halal_status(s, uni)["status"]
        counts[st] = counts.get(st, 0) + 1
        if st == "compliant":
            syms.append(s)
    return syms, counts


def yahoo_range(first_needed, today):
    """The smallest Yahoo range that reaches back to first_needed."""
    days = (today - first_needed).days
    for r, n in (("1y", 360), ("2y", 725), ("5y", 1820), ("10y", 3645)):
        if days <= n:
            return r
    return "max"


def load_bars(syms, range_, start, end, sleep=0.25, progress=None):
    """-> ({sym: bars up to `end`}, skipped[]). A stock with no data, or fewer than WARMUP_BARS bars before
    the window starts, is skipped with the reason. Nothing is filled in: a missing day stays missing."""
    data, skipped = {}, []
    for k, s in enumerate(syms):
        if progress:
            progress("prices %d/%d %s" % (k + 1, len(syms), s))
        try:
            bars, _ = tc.get_daily_bars(s, range_=range_)
        except tc.FetchError as e:
            skipped.append({"symbol": s, "reason": "no price data: %s" % str(e)[:160]})
            continue
        finally:
            if sleep and not tc.fixtures_dir():
                time.sleep(sleep)
        bars = [b for b in bars if b["date"] <= end]
        before = sum(1 for b in bars if b["date"] < start)
        if not bars:
            skipped.append({"symbol": s, "reason": "no price data up to %s" % end})
        elif before < WARMUP_BARS:
            skipped.append({"symbol": s, "reason": "only %s before %s (needs %d warm-up bars); data starts %s"
                            % (tc.plural(before, "bar"), start, WARMUP_BARS, bars[0]["date"])})
        else:
            data[s] = bars
    return data, skipped


# ---------------------------------------------------------------------------
# One day's list, like tayyib-daily (bars up to that day only)
# ---------------------------------------------------------------------------

class Book:
    """A stock's bars, its indicators (causal: bar i uses bars 0..i) and a date -> index map."""

    def __init__(self, bars):
        self.bars = bars
        self.ind = tc.indicators(bars)
        self.idx = {b["date"]: k for k, b in enumerate(bars)}


def scan_day(books, date, cfg, mode, setups, held):
    """tayyib-scanner + tayyib-daily's choice for one close: every compliant stock with a bar on `date`, its
    signals on bars[0..i], the liquidity filter on bars[0..i], a plan for each (tc.plan_trade), best score
    first, the scanner's top max(2 x daily.top, 25), held stocks dropped, then tc.choose_candidates.
    -> list of picks {symbol, setup, mode, score, sig, plan, i}."""
    min_hist = cfg["scanner"]["min_history_bars"]
    tick = cfg["tick_size"]
    cands = []
    for s in sorted(books):
        bk = books[s]
        i = bk.idx.get(date)
        if i is None or i + 1 < min_hist:
            continue
        sigs = tc.detect_at(bk.bars, bk.ind, i, mode, setups, tick, cfg)
        if not sigs:
            continue
        ok, _ = tc.liquidity_ok(bk.bars[:i + 1], cfg)
        if not ok:
            continue
        for sig in sigs:
            sig = dict(sig, symbol=s)
            try:
                pl = tc.plan_trade(sig, cfg)
            except ValueError:
                continue
            pl["date"] = sig["date"]                 # trade_outcome follows the plan from its signal date
            cands.append({"symbol": s, "setup": sig["setup"], "mode": sig["mode"], "score": sig["score"],
                          "sig": sig, "plan": pl, "i": i})
    cands.sort(key=lambda c: -c["score"])            # stable, like scan.py
    top = cfg["daily"]["top"]
    cands = [c for c in cands[: max(top * 2, 25)] if c["symbol"] not in held]
    return tc.choose_candidates(cands, mode, top)


def time_machine(bk, pick, cfg, K, mn):
    """What tayyib-daily's time machine says about a pick on its signal day: history replay (and, when the
    ranking or daily.min_expectancy_r needs it, the Monte Carlo) on the stock's last TM_YEARS of bars up to
    that day. -> (expectancy_r or None, past trades)."""
    i, d = pick["i"], tc.parse_date(pick["sig"]["date"])
    try:
        cut = d.replace(year=d.year - TM_YEARS).isoformat()
    except ValueError:                               # 29 February
        cut = (d - dt.timedelta(days=365 * TM_YEARS)).isoformat()
    j = i
    while j > 0 and bk.bars[j - 1]["date"] > cut:
        j -= 1
    win = bk.bars[j:i + 1]
    summ, _ = tc.tm_history(win, pick["plan"], cfg)
    exp = None
    if mn is not None or not tc.thin_evidence(summ["trades"], K):
        exp = tc.tm_monte_carlo(win, pick["plan"], cfg, TM_RUNS, TM_SEED)["expectancy_r"]
    return exp, summ["trades"]


def rank_day(books, picks, cfg, avail, free):
    """Order the day's picks like tayyib-daily (tc.rank_key: best time-machine expectancy among stocks with at
    least daily.min_past_trades_for_rank past trades, then by setup score), ties by symbol, and apply
    daily.min_expectancy_r. The time machine only runs when the order can change what is bought: more picks
    than free slots, or not enough cash for all of them in any order. -> (ordered picks, filtered[], tm_runs)."""
    K = cfg["daily"]["min_past_trades_for_rank"]
    mn = cfg["daily"].get("min_expectancy_r")
    if mn is None and len(picks) <= free:
        need = 0.0
        for p in picks:
            sz = tc.size_trade(p["plan"], cfg, avail)
            need += sz["qty"] * p["plan"]["entry"] * 1.002
        if need <= avail:
            for p in picks:
                p["ranked_by"] = "not needed (every pick fitted)"
            return sorted(picks, key=lambda p: p["symbol"]), [], 0
    runs = 0
    for p in picks:
        bk = books[p["symbol"]]
        exp, n = time_machine(bk, p, cfg, K, mn)
        runs += 1
        p["expectancy_r"], p["past_trades"] = exp, n
        p["ranked_by"] = "score" if tc.thin_evidence(n, K) else "expectancy"
    filtered = []
    if mn is not None:
        filtered = [p for p in picks if p["expectancy_r"] is None or p["expectancy_r"] < mn]
        picks = [p for p in picks if p not in filtered]
    picks = sorted(picks, key=lambda p: tc.rank_key(p.get("expectancy_r"), p.get("past_trades"), p["score"], K)
                   + (p["symbol"],))
    return picks, filtered, runs


# ---------------------------------------------------------------------------
# The account, day by day
# ---------------------------------------------------------------------------

def _charges(side, price, qty, cfg):
    return tc.order_charges(side, price, qty, cfg)["total"]


def simulate(data, cfg, start, end, mode="all", setups=None, max_positions=5, progress=None):
    """Run the strategy over [start, end] on {sym: bars} (compliant stocks only, bars up to `end`).
    -> {trades[], curve[], unfilled, fill_cuts[], counts}."""
    books = {s: Book(b) for s, b in data.items()}
    days = sorted({b["date"] for bk in books.values() for b in bk.bars if start <= b["date"] <= end})
    capital = float(cfg["capital"])
    cash = capital
    pending, held, trades, curve = {}, {}, [], []
    last_close = {}
    counts = {"plans": 0, "not_triggered": 0, "no_cash_at_fill": 0, "qty_cut_at_fill": 0, "not_sized": 0,
              "no_slot": 0, "tm_days": 0, "signal_days": 0}

    def outcome(rec):
        pl = dict(rec["plan"], qty=rec["qty"])
        return tc.trade_outcome(books[rec["symbol"]].bars, pl, cfg, today=end)

    def close(rec, px, date, reason):
        nonlocal cash
        sell = _charges("SELL", px, rec["qty"], cfg)
        cash += rec["qty"] * px - sell
        o = rec["out"]
        trades.append({
            "symbol": rec["symbol"], "setup": rec["setup"], "mode": rec["mode"],
            "signal_date": rec["plan"]["signal_date"], "entry_date": rec["filled"], "entry_price": rec["fill"],
            "exit_date": date, "exit_price": round(px, 2), "exit_reason": reason, "qty": rec["qty"],
            "charges": round(rec["buy_charges"] + sell, 2), "pnl_rs": o["pnl_rs"], "r": o["r"],
            "plan_entry": rec["plan"]["entry"], "stop": rec["plan"]["stop"], "target": rec["plan"]["target"],
            "valid_until": rec["plan"]["valid_until"], "score": rec["score"], "ranked_by": rec["ranked_by"],
            "expectancy_r": rec.get("expectancy_r"), "past_trades": rec.get("past_trades"),
            "qty_cut_at_fill": rec.get("qty_cut", False)})

    for n_day, d in enumerate(days):
        if progress and n_day % 50 == 0:
            progress("day %d/%d %s" % (n_day + 1, len(days), d))
        for s, bk in books.items():
            k = bk.idx.get(d)
            if k is not None:
                last_close[s] = bk.bars[k]["close"]
        # 1. exits of positions already held
        for s in sorted(held):
            rec = held[s]
            if rec["out"]["exited"] == d:
                close(rec, rec["out"]["exit"], d, rec["out"]["status"])
                del held[s]
        # 2. fills (cash checked again at the fill price: a gap up costs more than planned)
        for s in sorted(pending):
            rec = pending[s]
            if rec["out"]["filled"] != d:
                continue
            del pending[s]
            fill = rec["out"]["fill"]
            room = cash - sum(r["reserve"] for r in pending.values())
            q = rec["qty"]
            while q > 0 and q * fill + _charges("BUY", fill, q, cfg) > room:
                q -= 1
            if q == 0:
                counts["no_cash_at_fill"] += 1
                continue
            if q != rec["qty"]:
                counts["qty_cut_at_fill"] += 1
                rec["qty"], rec["qty_cut"] = q, True
                rec["out"] = outcome(rec)
            rec["fill"], rec["filled"] = fill, d
            rec["buy_charges"] = _charges("BUY", fill, q, cfg)
            cash -= q * fill + rec["buy_charges"]
            held[s] = rec
            if rec["out"]["exited"] == d:                      # stopped out on the fill day
                close(rec, rec["out"]["exit"], d, rec["out"]["status"])
                del held[s]
        # 3. plans that were never triggered expire at valid_until
        for s in sorted(pending):
            if pending[s]["plan"]["valid_until"] <= d:
                counts["not_triggered"] += 1
                del pending[s]
        # 4. the close: today's list, ranked, sized against the cash not already promised
        if d != days[-1]:
            picks = scan_day(books, d, cfg, mode, setups, set(held) | set(pending))
            if picks:
                counts["signal_days"] += 1
                free = max_positions - len(held) - len(pending)
                avail = cash - sum(r["reserve"] for r in pending.values())
                if free > 0:
                    picks, _, runs = rank_day(books, picks, cfg, avail, free)
                    counts["tm_days"] += 1 if runs else 0
                    for p in picks:
                        if len(held) + len(pending) >= max_positions:
                            counts["no_slot"] += 1
                            continue
                        sz = tc.size_trade(p["plan"], cfg, avail)
                        if not sz["qty"]:
                            counts["not_sized"] += 1
                            continue
                        rec = {"symbol": p["symbol"], "setup": p["setup"], "mode": p["mode"], "score": p["score"],
                               "plan": p["plan"], "qty": sz["qty"], "ranked_by": p.get("ranked_by"),
                               "expectancy_r": p.get("expectancy_r"), "past_trades": p.get("past_trades"),
                               "reserve": sz["position_value_rs"] + sz["buy_charges_rs"]}
                        rec["out"] = outcome(rec)
                        avail -= rec["reserve"]
                        pending[p["symbol"]] = rec
                        counts["plans"] += 1
                else:
                    counts["no_slot"] += len(picks)
        # 5. the last day: whatever is still held is valued at its last close, after the sell charges
        if d == days[-1]:
            for s in sorted(held):
                rec = held[s]
                if rec["out"]["exited"] is None:
                    close(rec, last_close[s], d, EXIT_AT_END)
                    del held[s]
            pending.clear()
        mtm = sum(r["qty"] * last_close[s] for s, r in held.items())
        curve.append({"date": d, "equity": round(cash + mtm, 2), "cash": round(cash, 2),
                      "open_positions": len(held), "waiting_plans": len(pending)})
        if cash < -1e-6:
            raise AssertionError("cash went negative on %s: %.2f" % (d, cash))
    return {"trades": trades, "curve": curve, "counts": counts, "days": days}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _r2(x, n=2):
    return None if x is None else round(x, n)


def curve_stats(points):
    """points: [(date, equity, exposed)] -> return, CAGR, max drawdown with dates, exposure."""
    if not points:
        return {"total_return_pct": None, "cagr_pct": None, "max_drawdown_pct": None, "drawdown_peak": None,
                "drawdown_trough": None, "exposure_pct": None, "start_equity": None, "end_equity": None}
    e0, e1 = points[0][1], points[-1][1]
    years = (tc.parse_date(points[-1][0]) - tc.parse_date(points[0][0])).days / 365.25
    cagr = ((e1 / e0) ** (1 / years) - 1) * 100 if years > 0 and e0 > 0 and e1 > 0 else None
    peak, peak_d, worst, wp, wt = e0, points[0][0], 0.0, None, None
    for d, e, _ in points:
        if e > peak:
            peak, peak_d = e, d
        dd = (e / peak - 1) * 100 if peak > 0 else 0.0
        if dd < worst:
            worst, wp, wt = dd, peak_d, d
    return {"total_return_pct": _r2((e1 / e0 - 1) * 100 if e0 else None), "cagr_pct": _r2(cagr),
            "max_drawdown_pct": round(worst, 2), "drawdown_peak": wp, "drawdown_trough": wt,
            "exposure_pct": round(sum(1 for p in points if p[2]) / len(points) * 100, 1),
            "start_equity": round(e0, 2), "end_equity": round(e1, 2)}


def trade_stats(trades):
    n = len(trades)
    out = {"trades": n, "win_rate_pct": None, "avg_r": None, "avg_win_r": None, "avg_loss_r": None,
           "expectancy_r": None, "profit_factor": None, "pnl_rs": None, "longest_losing_streak": 0,
           "total_charges_rs": round(sum(t["charges"] for t in trades), 2)}
    if not n:
        return out
    rs = [t["r"] for t in trades]
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    p = len(wins) / n
    gp = sum(t["pnl_rs"] for t in trades if t["pnl_rs"] > 0)
    gl = -sum(t["pnl_rs"] for t in trades if t["pnl_rs"] < 0)
    streak = best = 0
    for t in sorted(trades, key=lambda t: (t["exit_date"], t["symbol"])):
        streak = streak + 1 if t["pnl_rs"] < 0 else 0
        best = max(best, streak)
    aw = sum(wins) / len(wins) if wins else None
    al = sum(losses) / len(losses) if losses else None
    out.update({"win_rate_pct": round(p * 100, 1), "avg_r": round(sum(rs) / n, 3), "avg_win_r": _r2(aw, 3),
                "avg_loss_r": _r2(al, 3),
                # p x average win - (1 - p) x average loss: the same number as the average R, by definition
                "expectancy_r": round(p * (aw or 0) + (1 - p) * (al or 0), 3),
                "profit_factor": round(gp / gl, 2) if gl > 0 else None,
                "pnl_rs": round(sum(t["pnl_rs"] for t in trades), 2), "longest_losing_streak": best})
    if gl == 0:
        out["profit_factor_note"] = "no losing trades: profit factor undefined"
    return out


def realised_points(trades, days, capital):
    """A curve for a subset of trades (one setup or one mode): capital + the P&L of its trades closed by each
    day; exposed while one of them is held."""
    pts, k = [], 0
    by_exit = sorted(trades, key=lambda t: t["exit_date"])
    pnl = 0.0
    for d in days:
        while k < len(by_exit) and by_exit[k]["exit_date"] <= d:
            pnl += by_exit[k]["pnl_rs"]
            k += 1
        exposed = any(t["entry_date"] <= d <= t["exit_date"] for t in trades)
        pts.append((d, capital + pnl, exposed))
    return pts


def group_metrics(trades, days, capital, key):
    out = {}
    for g in sorted({t[key] for t in trades}):
        sub = [t for t in trades if t[key] == g]
        m = trade_stats(sub)
        m.update(curve_stats(realised_points(sub, days, capital)))
        m["curve_basis"] = "realised: capital + P&L of these trades when they closed"
        out[g] = m
    return out


def split_metrics(trades, curve, split):
    """In-sample (signals before split) vs out-of-sample (on or after), side by side. Return, CAGR and
    drawdown come from the account's own equity on each side of the split."""
    pts = [(c["date"], c["equity"], c["open_positions"] > 0) for c in curve]
    before = [p for p in pts if p[0] < split]
    after = [p for p in pts if p[0] >= split]
    if before and after:
        after = [before[-1]] + after                  # out-of-sample starts from the equity at the split
    res = {}
    for name, sub, seg in (("in_sample", [t for t in trades if t["signal_date"] < split], before),
                           ("out_of_sample", [t for t in trades if t["signal_date"] >= split], after)):
        m = trade_stats(sub)
        m.update(curve_stats(seg))
        m["from"], m["to"] = (seg[0][0], seg[-1][0]) if seg else (None, None)
        res[name] = m
    return res


# ---------------------------------------------------------------------------
# Benchmarks: buy and hold, one set of charges
# ---------------------------------------------------------------------------

def benchmark(sym, name, range_, start, end, capital, cfg, fetch=None):
    """Buy at the close of the first bar in the window with all the capital (fractional units, so the index
    can be compared), sell at the last close, one buy and one sell charge. UNKNOWN with the reason when the
    data cannot be had, never 0."""
    out = {"symbol": sym, "name": name, "status": "UNKNOWN"}
    try:
        bars, _ = (fetch or tc.get_daily_bars)(sym, range_=range_)
    except tc.FetchError as e:
        out["reason"] = "could not be fetched: %s" % str(e)[:200]
        return out
    bars = [b for b in bars if start <= b["date"] <= end]
    if len(bars) < 2:
        out["reason"] = "no prices in the window %s to %s" % (start, end)
        return out
    p0, p1 = bars[0]["close"], bars[-1]["close"]
    units = capital / p0
    for _ in range(3):                                  # the buy charge comes out of the capital
        units = (capital - _charges("BUY", p0, units, cfg)) / p0
    buy, sell = _charges("BUY", p0, units, cfg), _charges("SELL", p1, units, cfg)
    pts = [(bars[0]["date"], capital, True)] + [(b["date"], units * b["close"], True) for b in bars[1:-1]] + \
          [(bars[-1]["date"], units * p1 - sell, True)]
    st = curve_stats(pts)
    st.pop("exposure_pct", None)
    out.update(status="OK", start=bars[0]["date"], end=bars[-1]["date"], buy_price=round(p0, 2),
               sell_price=round(p1, 2), charges_rs=round(buy + sell, 2), **st)
    if bars[0]["date"] > start and (tc.parse_date(bars[0]["date"]) - tc.parse_date(start)).days > 7:
        out["note"] = "its data starts %s, after the window start %s" % (bars[0]["date"], start)
    return out


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------

def banners(overall, split, benches):
    b = [BANNER_HALAL, BANNER_SURVIVOR, BANNER_PAST]
    if overall["trades"] < MIN_TRADES:
        b.append(BANNER_FEW)
    ise, ose = split["in_sample"]["expectancy_r"], split["out_of_sample"]["expectancy_r"]
    if overfit(ise, ose):
        b.append(BANNER_OVERFIT)
    etf = benches.get(SHARIAH_BENCH) or {}
    if etf.get("status") != "OK":
        b.append(BANNER_NO_ETF)
    elif overall.get("cagr_pct") is not None and etf.get("cagr_pct") is not None \
            and overall["cagr_pct"] < etf["cagr_pct"]:
        b.append(BANNER_ETF)
    return b


def overfit(ise, ose):
    """Out-of-sample expectancy below half the in-sample one (which includes the opposite sign), when the
    in-sample one was positive. An in-sample result that already lost is not 'overfit', and an
    out-of-sample result better than it is not 'much weaker'. Missing on either side: no verdict."""
    if ise is None or ose is None or ise <= 0:
        return False
    return ose < ise / 2


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def window(a, today):
    end = a.to or today.isoformat()
    if a.from_:
        start = a.from_
    else:
        e = tc.parse_date(end)
        try:
            start = e.replace(year=e.year - a.years).isoformat()
        except ValueError:
            start = (e - dt.timedelta(days=round(365.25 * a.years))).isoformat()
    if start >= end:
        tc.die("--from must be before --to")
    s, e = tc.parse_date(start), tc.parse_date(end)
    split = a.split or (s + dt.timedelta(days=round((e - s).days * 2 / 3))).isoformat()
    if not start < split <= end:
        tc.die("--split must be inside the window (%s to %s)" % (start, end))
    return start, end, split


def run_id(params, label, syms):
    h = hashlib.sha1(json.dumps([params, label, syms], sort_keys=True).encode("utf-8")).hexdigest()[:6]
    return "%s_%s_%s_%s" % (params["to"], params["mode"], params["from"], h)


def run(params, cfg, uni, data_fn=load_bars, bench_fn=None, progress=None):
    """The whole backtest -> result dict (no file is written here)."""
    syms, status_counts = halal_universe(uni)
    start, end, split = params["from"], params["to"], params["split"]
    first = tc.parse_date(start) - dt.timedelta(days=365 * TM_YEARS + 10)
    range_ = yahoo_range(first, tc.today_ist())
    data, skipped = data_fn(syms, range_, start, end, progress=progress)
    sim = simulate(data, cfg, start, end, params["mode"], params["setups"], params["max_positions"], progress)
    trades, curve, days = sim["trades"], sim["curve"], sim["days"]
    capital = float(cfg["capital"])
    pts = [(c["date"], c["equity"], c["open_positions"] > 0) for c in curve]
    overall = trade_stats(trades)
    overall.update(curve_stats(pts))
    benches = {}
    for sym, name in BENCHMARKS:
        benches[sym] = benchmark(sym, name, range_, start, end, capital, cfg, fetch=bench_fn)
    spl = split_metrics(trades, curve, split)
    snap = tc.settings_snapshot(cfg)
    res = {
        "id": run_id(params, snap["hash"], syms),
        "version": tc.VERSION,
        "params": params,
        "settings": {"label": snap["label"], "hash": snap["hash"], "differs_from_default": snap["differs_from_default"],
                     "capital": capital, "risk_per_trade_pct": cfg["max_risk_per_trade_pct"],
                     "max_position_pct": cfg["max_position_pct"], "broker": cfg["broker"]},
        "window": {"from": start, "to": end, "split": split, "first_day": days[0] if days else None,
                   "last_day": days[-1] if days else None, "trading_days": len(days), "price_range": range_},
        "universe": {"list_updated": uni.get("updated"), "statuses": status_counts, "compliant": len(syms),
                     "tested": len(data), "skipped": len(skipped)},
        "skipped": skipped,
        "banners": [],
        "metrics": {"overall": overall, "by_setup": group_metrics(trades, days, capital, "setup"),
                    "by_mode": group_metrics(trades, days, capital, "mode")},
        "split": spl,
        "benchmarks": benches,
        "counts": sim["counts"],
        "rules": [
            "Signals, liquidity, plans and ranking on each day use that day's bars and earlier only; fills from "
            "the next session.",
            "Each day's stocks are picked and ranked like tayyib-daily (scanner top max(2 x daily.top, 25), one "
            "setup per stock, rank_key with the time machine on the stock's last 2 years; ties by symbol).",
            "A plan waits as a buy-stop until valid_until; it fills at max(open, entry) and then follows "
            "trade_outcome: a gap through the stop fills at the open, a day touching stop and target is the "
            "stop, swing breakeven at +1R, time stop at that day's close.",
            "Sized with tayyib-budget's rule (risk per trade incl. charges, max position) on the configured "
            "capital, against the cash not already held or promised to waiting plans; at most max_positions "
            "held or waiting; one per stock; no margin. A gap up that needs more cash than is free cuts the "
            "quantity.",
            "tayyib-risk's other limits (portfolio heat, positions per industry, net reward:risk, news) are not "
            "applied: they need data the past does not keep (news) or are left for a later version.",
            "Zerodha delivery charges (or your broker in config) on every buy and sell. Positions still open on the "
            "last day are valued at the last close after the sell charges (exit reason %s)." % EXIT_AT_END],
        "trades": trades,
        "equity_curve": curve,
        "disclaimer": tc.DISCLAIMER,
    }
    res["banners"] = banners(overall, spl, benches)
    return res


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def fmt(x, unit="", d=2):
    if x is None:
        return "UNKNOWN"
    if unit == "Rs":
        return tc.fmt_rs(x, 0)
    if unit == "R":
        return "%+.*fR" % (d, x)
    return ("%.*f" % (d, x)) + unit


def metrics_rows(m):
    dd = fmt(m.get("max_drawdown_pct"), "%")
    if m.get("drawdown_peak"):
        dd += " (%s to %s)" % (m["drawdown_peak"], m["drawdown_trough"])
    return [("trades", str(m["trades"])), ("win rate", fmt(m["win_rate_pct"], "%", 1)),
            ("average R", fmt(m["avg_r"], "R")), ("expectancy", fmt(m["expectancy_r"], "R")),
            ("profit factor", "no losing trades" if m.get("profit_factor_note") else fmt(m["profit_factor"])), ("P&L", fmt(m["pnl_rs"], "Rs")),
            ("total return", fmt(m.get("total_return_pct"), "%")), ("CAGR", fmt(m.get("cagr_pct"), "%")),
            ("max drawdown", dd), ("longest losing streak", str(m["longest_losing_streak"])),
            ("exposure", fmt(m.get("exposure_pct"), "%", 1)), ("charges", fmt(m["total_charges_rs"], "Rs"))]


def table(cols):
    """cols: [(title, metrics)] -> markdown table with one column per title."""
    names = [r[0] for r in metrics_rows(cols[0][1])]
    vals = [dict(metrics_rows(m)) for _, m in cols]
    L = ["| | " + " | ".join(t for t, _ in cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for n in names:
        L.append("| %s | %s |" % (n, " | ".join(v[n] for v in vals)))
    return L


def render_md(r):
    w, u, s = r["window"], r["universe"], r["settings"]
    L = ["**%s**" % b for b in r["banners"]] + ["", "# Backtest %s" % r["id"], "",
         "%s mode%s, %s to %s (%d trading days), split %s. Capital %s, risk %s%% a trade, max %d positions, "
         "settings %s, broker %s." % (r["params"]["mode"], " (%s)" % ", ".join(r["params"]["setups"])
                                      if r["params"]["setups"] else "", w["first_day"], w["last_day"],
                                      w["trading_days"], w["split"], tc.fmt_rs(s["capital"], 0),
                                      tc._fmt_val(s["risk_per_trade_pct"]), r["params"]["max_positions"],
                                      s["label"], s["broker"]),
         "Universe: %d compliant stocks on today's halal list (built %s), %d tested, %d skipped."
         % (u["compliant"], u["list_updated"], u["tested"], u["skipped"]), "", "## Overall", ""]
    L += table([("strategy", r["metrics"]["overall"])]) + [""]
    if r["metrics"]["by_setup"]:
        L += ["## By setup", ""] + table(list(r["metrics"]["by_setup"].items())) + [""]
    if r["metrics"]["by_mode"]:
        L += ["## By mode", ""] + table(list(r["metrics"]["by_mode"].items())) + [""]
    L += ["Setup and mode columns: return, CAGR and drawdown are on the capital plus those trades' realised "
          "P&L.", "", "## In-sample vs out-of-sample (split %s, by signal date)" % w["split"], ""]
    L += table([("in-sample", r["split"]["in_sample"]), ("out-of-sample", r["split"]["out_of_sample"])]) + [""]
    L += ["## Benchmarks (buy and hold, one buy and one sell charge)", "",
          "| | total return | CAGR | max drawdown | note |", "|---|---|---|---|---|",
          "| strategy | %s | %s | %s | |" % (fmt(r["metrics"]["overall"]["total_return_pct"], "%"),
                                           fmt(r["metrics"]["overall"]["cagr_pct"], "%"),
                                           fmt(r["metrics"]["overall"]["max_drawdown_pct"], "%"))]
    for b in r["benchmarks"].values():
        if b["status"] != "OK":
            L.append("| %s (%s) | UNKNOWN | UNKNOWN | UNKNOWN | %s |" % (b["name"], b["symbol"], b["reason"]))
        else:
            L.append("| %s (%s) | %s | %s | %s | %s to %s%s |" % (
                b["name"], b["symbol"], fmt(b["total_return_pct"], "%"), fmt(b["cagr_pct"], "%"),
                fmt(b["max_drawdown_pct"], "%"), b["start"], b["end"], "; " + b["note"] if b.get("note") else ""))
    c = r["counts"]
    L += ["", "Plans placed %d; never triggered %d; no free slot %d; not sized %d; no cash at the fill %d; "
          "quantity cut at the fill %d." % (c["plans"], c["not_triggered"], c["no_slot"], c["not_sized"],
                                            c["no_cash_at_fill"], c["qty_cut_at_fill"]), ""]
    if r["skipped"]:
        L += ["## Skipped stocks", ""] + ["- %s: %s" % (x["symbol"], x["reason"]) for x in r["skipped"]] + [""]
    L += ["## Rules", ""] + ["- " + x for x in r["rules"]] + ["", "## Trades", "",
          "| signal | stock | setup | entry | price | exit | price | reason | qty | charges | P&L | R |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in r["trades"]:
        L.append("| %s | %s | %s %s | %s | %.2f | %s | %.2f | %s | %d | %.2f | %.2f | %+.2f |" % (
            t["signal_date"], t["symbol"], t["mode"], t["setup"], t["entry_date"], t["entry_price"], t["exit_date"],
            t["exit_price"], t["exit_reason"], t["qty"], t["charges"], t["pnl_rs"], t["r"]))
    L += ["", r["disclaimer"]]
    return "\n".join(L) + "\n"


def out_dir():
    return os.path.join(tc.data_dir(), "backtest")


def save(res):
    """trader/backtest/<id>.json and .md: the only files this skill writes."""
    d = out_dir()
    os.makedirs(d, exist_ok=True)
    jp = os.path.join(d, res["id"] + ".json")
    tc.write_json(jp, res)
    with open(os.path.join(d, res["id"] + ".md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(render_md(res))
    return jp


def summary(res):
    m = res["metrics"]["overall"]
    return {"id": res["id"], "from": res["window"]["first_day"], "to": res["window"]["last_day"],
            "mode": res["params"]["mode"], "settings": res["settings"]["label"], "trades": m["trades"],
            "total_return_pct": m["total_return_pct"], "cagr_pct": m["cagr_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"], "banners": len(res["banners"])}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a backtest")
    r.add_argument("--mode", choices=("swing", "delivery", "all"), default="all")
    r.add_argument("--setups", help="comma list: %s" % ",".join(tc.SWING_SETUPS + tc.DELIVERY_SETUPS))
    r.add_argument("--years", type=int, default=3)
    r.add_argument("--from", dest="from_", help="YYYY-MM-DD (default: --years before --to)")
    r.add_argument("--to", help="YYYY-MM-DD (default: today)")
    r.add_argument("--capital", type=float, help="default: capital in config")
    r.add_argument("--max-positions", type=int, default=5)
    r.add_argument("--split", help="in-sample / out-of-sample date (default: the start of the last third)")
    r.add_argument("--write", action="store_true", help="save trader/backtest/<id>.json and .md")
    r.add_argument("--json", action="store_true")
    ls = sub.add_parser("list", help="saved backtests")
    ls.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="one saved backtest")
    sh.add_argument("id")
    sh.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "list":
        d = out_dir()
        rows = []
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f.endswith(".json"):
                try:
                    rows.append(summary(tc.read_json(os.path.join(d, f))))
                except (ValueError, KeyError, TypeError):
                    rows.append({"id": f[:-5], "error": "could not be read"})
        if a.json:
            return tc.print_json(rows)
        if not rows:
            return print("No saved backtests: run `backtest.py run --write`.")
        for x in rows:
            if "error" in x:
                print("%s  (%s)" % (x["id"], x["error"]))
                continue
            print("%s  %s to %s  %s  %s  %d trades  return %s  CAGR %s  max drawdown %s"
                  % (x["id"], x["from"], x["to"], x["mode"], x["settings"], x["trades"],
                     fmt(x["total_return_pct"], "%"), fmt(x["cagr_pct"], "%"), fmt(x["max_drawdown_pct"], "%")))
        return
    if a.cmd == "show":
        name = os.path.basename(a.id)
        jp = os.path.join(out_dir(), name + ".json")
        if not os.path.exists(jp):
            tc.die("no saved backtest %s (see backtest.py list)" % name)
        res = tc.read_json(jp)
        if a.json:
            return tc.print_json(res)
        return print(render_md(res))

    cfg = tc.load_config()
    tc.report_config(cfg)
    if a.capital is not None:
        if a.capital <= 0:
            tc.die("--capital must be positive")
        cfg["capital"] = a.capital
    if a.max_positions < 1:
        tc.die("--max-positions must be at least 1")
    setups = None
    if a.setups:
        setups = [x.strip() for x in a.setups.split(",") if x.strip()]
        bad = [x for x in setups if x not in tc.SWING_SETUPS + tc.DELIVERY_SETUPS]
        if bad:
            tc.die("unknown setup %s (choose from %s)" % (", ".join(bad), ", ".join(tc.SWING_SETUPS + tc.DELIVERY_SETUPS)))
    start, end, split = window(a, tc.today_ist())
    uni = tc.load_universe()
    if not uni.get("stocks"):
        tc.die("no halal universe yet: run tayyib-halal/halal.py build first")
    params = {"mode": a.mode, "setups": setups, "from": start, "to": end, "split": split,
              "max_positions": a.max_positions, "top": cfg["daily"]["top"], "warmup_bars": WARMUP_BARS,
              "tm_runs": TM_RUNS, "tm_seed": TM_SEED}
    t0 = time.time()
    progress = None if a.json else (lambda m: sys.stderr.write("  %s\n" % m))
    res = run(params, cfg, uni, progress=progress)
    secs = time.time() - t0
    if a.write:
        jp = save(res)
        sys.stderr.write("-> %s (and .md)\n" % jp)
    sys.stderr.write("run time %.0f s\n" % secs)
    if a.json:
        return tc.print_json(res)
    print(render_md(res))


if __name__ == "__main__":
    main()
