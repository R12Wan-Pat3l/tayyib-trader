#!/usr/bin/env python3
"""tayyib-backtest: if you had run this strategy every day for the last N years, what happened?

Replays tayyib-daily day by day over the halal list with your capital and settings, using the same
functions the live pipeline uses (setups, liquidity, exit plan, ranking, sizing, the risk check, the paper
outcome rules and Zerodha delivery charges):

  each close   scan every compliant stock on its bars up to that day only, pick and rank the day's
               stocks like tayyib-daily, size them, risk-check them against the simulated book (PASS, and
               WARN unless --no-take-warn; never BLOCK) and place buy-stop plans
  next days    a plan fills when price trades through its entry (by its valid-until date), then exits at
               the stop, the target, breakeven or the time stop exactly like the paper tracker
  one account  one cash balance (never negative, no margin; sale proceeds usable from the next day), one
               position per stock, at most --max-positions open or waiting (default: max_open_positions in
               your settings, v0.2.7), charges on every buy and sell

Writes trader/backtest/<id>.json and .md with --write, and nothing else (prices go to the usual cache).
A replay of the past with today's halal list: read the banners. Places no order.

  backtest.py run [--mode swing|delivery|all] [--setups breakout,pullback] [--years 3]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--capital N] [--max-positions N]
                  [--split YYYY-MM-DD] [--no-take-warn] [--no-late] [--compare] [--write] [--json]
                  [--symbols SYM1,SYM2,... | --holdings]

"My stocks" (v0.2.8): --symbols (1 to 20 compliant stocks) or --holdings (the stocks in positions.json) runs the
same strategy on that basket only, and compares it with buying and holding the same stocks (equal shares, one
buy and one sell charge). Every symbol must be compliant on today's halal list: anything else is refused.

Without --to the window ends on the last completed session: today after 15:30 IST on a trading day,
otherwise the previous trading day (so a run in market hours never uses a half-made bar).
  backtest.py list
  backtest.py show ID
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

WARMUP_BARS = 250              # a stock joins on the first day it has this many bars of history
TM_RUNS, TM_SEED = 3000, 7     # what tayyib-daily asks the time machine for (daily.py --runs, timemachine --seed)
TM_YEARS = 2                   # the time machine sees the stock's last 2 years (get_daily_bars' default range)
BENCHMARKS = (("SHARIABEES.NS", "Nippon India ETF Shariah BeES"),
              ("^NSEI", "Nifty 50 (price index: dividends not included)"))
SHARIAH_BENCH, NIFTY = "SHARIABEES.NS", "^NSEI"
MIN_TRADES = tc.MIN_TRADES      # 30

BANNER_HALAL = ("Halal status is today's list applied to past years (point-in-time halal data is not "
                "available).")
BANNER_SURVIVOR = ("Universe is today's list: companies that dropped out are missing (survivorship bias), so "
                   "results are likely better than reality.")
BANNER_PAST = "Past results do not predict future results. Not financial advice, not a fatwa."
BANNER_NEWS = "News and HALAL-WATCH checks can't be replayed for past dates; live results may differ."
BANNER_FEW = "Too few trades to judge."
BANNER_OVERFIT = "Out-of-sample results are much weaker: the strategy may be overfit."
BANNER_ETF = "Buying and holding the Shariah ETF did better."
BANNER_NO_ETF = ("The Shariah ETF benchmark is UNKNOWN (it could not be fetched), so the strategy could not be "
                 "compared with it.")
BANNER_NIFTY = ("The Nifty 50 (not halal-screened, price only) did better over this window; it is shown for "
                "reference only, not as a halal option.")
EXIT_AT_END = "OPEN AT END"
TOO_FEW = "(too few to judge)"
NOT_REPLAYED = ("news / HALAL-WATCH", "halal list age")

# v0.2.8: "My stocks"
UNIVERSE_MODES = ("all", "symbols", "holdings")
SMALL_BASKET = 10
BANNER_HINDSIGHT = ("You chose these stocks today, knowing how they did since. Results are likely better than "
                    "reality (hindsight).")
BANNER_SMALL = "Small basket: fewer stocks means fewer trades and more luck."
BANNER_HOLD = "Buying and holding these same stocks did better."
BASKET_NAME = "Buy and hold these stocks"
BASKET_NOTE = ("The capital split equally across the chosen stocks that had prices; each bought at the close of its "
               "first day in the window (a stock listed during the window on the day it joins the test, its share "
               "waiting as cash until then), fractional units, one buy charge, held to the end and valued after one "
               "sell charge.")
STOCKS_NOTE = ("Strategy return on a stock = the P&L of its trades as a share of that stock's equal slice of the "
               "capital; holding = that slice bought on its first day and held to the end, after charges. A rough "
               "comparison: the strategy did not keep the slice in that stock the whole time.")

# A risk check's BLOCK / WARN text -> a stable reason name for counts.risk_blocked / risk_warned
REASONS = ((r"^hard rule", "hard rules"), (r"^halal: ", "halal status"), (r"^loss at stop", "loss at stop"),
           (r"^position ", "max position %"), (r"^needs ", "cash"), (r"^open positions", "max open positions"),
           (r"^portfolio heat", "portfolio heat"), (r"^\d+ open in ", "positions per industry"),
           (r"^net reward:risk", "min net reward:risk"), (r"^plan expired", "plan expired"),
           (r"^time machine expectancy is negative", "time-machine expectancy negative"),
           (r"^already holding", "already holding"))


def reason_name(text):
    for pat, name in REASONS:
        if re.search(pat, text):
            return name
    return "other: " + text[:40]


# ---------------------------------------------------------------------------
# Universe and data
# ---------------------------------------------------------------------------

def halal_universe(uni):
    """Compliant stocks of the halal list (the automatic TASIS screen; v0.2.7: no per-stock overrides). review,
    excluded and unknown are never traded.
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


def join_date(bars):
    """The first day a stock has WARMUP_BARS bars of history (that day included), or None."""
    return bars[WARMUP_BARS - 1]["date"] if len(bars) >= WARMUP_BARS else None


def load_bars(syms, range_, start, end, sleep=0.25, progress=None):
    """-> ({sym: bars up to `end`}, skipped[], joined_late[]). A stock joins on the first day it has
    WARMUP_BARS bars of history; one that never gets there by `end` (or has no data) is skipped with the
    reason. A stock that joins after `start` is listed in joined_late[]. Nothing is filled in."""
    data, skipped, late = {}, [], []
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
        j = join_date(bars)
        if not bars:
            skipped.append({"symbol": s, "reason": "no price data up to %s" % end})
        elif j is None or j > end:
            skipped.append({"symbol": s, "reason": "only %s up to %s (needs %d to join); data starts %s"
                            % (tc.plural(len(bars), "bar"), end, WARMUP_BARS, bars[0]["date"])})
        else:
            data[s] = bars
            if j > start:
                late.append({"symbol": s, "join_date": j, "data_starts": bars[0]["date"]})
    return data, skipped, late


# ---------------------------------------------------------------------------
# One day's list, like tayyib-daily (bars up to that day only)
# ---------------------------------------------------------------------------

class Book:
    """A stock's bars, its indicators (causal: bar i uses bars 0..i), a date -> index map and the index from
    which it may give signals (WARMUP_BARS of history)."""

    def __init__(self, bars):
        self.bars = bars
        self.ind = tc.indicators(bars)
        self.idx = {b["date"]: k for k, b in enumerate(bars)}
        self.join = WARMUP_BARS - 1


def scan_day(books, date, cfg, mode, setups, held, tie=None, cache=None):
    """tayyib-scanner + tayyib-daily's choice for one close: every compliant stock with a bar on `date` and
    WARMUP_BARS of history, its signals on bars[0..i], the liquidity filter on bars[0..i], a plan for each
    (tc.plan_trade), best score first, the scanner's top max(2 x daily.top, 25), held stocks dropped, then
    tc.choose_candidates. -> list of picks {symbol, setup, mode, score, sig, plan, i}.
    tie (v0.2.6, --robust): equal scores are ordered by tie(symbol) instead of the symbol (None: the symbol, as
    always). cache: a RunCache, so the same day's signals are worked out once for every robust run."""
    key = None
    if cache is not None:
        key = ("scan", cache.digest(cfg), cache.universe(books), mode, tuple(setups or ()), date)
        if key in cache.store:
            return _choose_day([dict(c) for c in cache.store[key]], cfg, mode, held, tie)
    cands = _scan_cands(books, date, cfg, mode, setups)
    if key is not None:
        cache.store[key] = [dict(c) for c in cands]
    return _choose_day(cands, cfg, mode, held, tie)


def _choose_day(cands, cfg, mode, held, tie):
    if tie is None:
        cands.sort(key=lambda c: -c["score"])        # stable, like scan.py (the stocks in symbol order)
    else:
        cands.sort(key=lambda c: (-c["score"], tie(c["symbol"])))
    top = cfg["daily"]["top"]
    cands = [c for c in cands[: max(top * 2, 25)] if c["symbol"] not in held]
    return tc.choose_candidates(cands, mode, top)


def _scan_cands(books, date, cfg, mode, setups):
    """Every signal with a plan on `date`, the stocks in symbol order (nothing sorted or cut yet)."""
    min_hist = cfg["scanner"]["min_history_bars"]
    tick = cfg["tick_size"]
    cands = []
    for s in sorted(books):
        bk = books[s]
        i = bk.idx.get(date)
        if i is None or i < bk.join or i + 1 < min_hist:
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
    return cands


def tm_window(bk, pick):
    """The bars tayyib-daily's time machine would see for a pick on its signal day: the stock's last TM_YEARS
    of bars up to that day (get_daily_bars' default range)."""
    i, d = pick["i"], tc.parse_date(pick["sig"]["date"])
    try:
        cut = d.replace(year=d.year - TM_YEARS).isoformat()
    except ValueError:                               # 29 February
        cut = (d - dt.timedelta(days=365 * TM_YEARS)).isoformat()
    j = i
    while j > 0 and bk.bars[j - 1]["date"] > cut:
        j -= 1
    return bk.bars[j:i + 1]


def rank_day(books, picks, cfg, all_mc=False, tie=None, cache=None):
    """Order the day's picks like tayyib-daily (tc.rank_key: best time-machine expectancy among stocks with at
    least daily.min_past_trades_for_rank past trades, then by setup score), ties by symbol, and apply
    daily.min_expectancy_r. The Monte Carlo runs where the ranking or that filter needs it, or for every pick
    with all_mc (its negative-expectancy WARN matters when WARN plans are not taken).
    tie / cache: as in scan_day (the time machine's answer for a pick is worked out once per settings).
    -> (ordered picks, filtered[])."""
    K = cfg["daily"]["min_past_trades_for_rank"]
    mn = cfg["daily"].get("min_expectancy_r")
    dg = cache.digest(cfg) if cache is not None else None
    for p in picks:
        pl = p["plan"]
        key = ("tm", dg, p["symbol"], p["sig"]["date"], pl["setup"], pl["entry"], pl["stop"], pl["target"])
        hit = cache.store.get(key) if cache is not None else None
        win = None
        if hit is None:
            win = tm_window(books[p["symbol"]], p)
            hit = {"summ": tc.tm_history(win, pl, cfg)[0], "exp": None, "mc": False}
            if cache is not None:
                cache.store[key] = hit
        summ = hit["summ"]
        n = summ["trades"]
        need_mc = all_mc or mn is not None or not tc.thin_evidence(n, K)
        if need_mc and not hit["mc"]:
            win = win or tm_window(books[p["symbol"]], p)
            hit["exp"], hit["mc"] = tc.tm_monte_carlo(win, pl, cfg, TM_RUNS, TM_SEED)["expectancy_r"], True
        p["expectancy_r"], p["past_trades"], p["history"] = hit["exp"] if need_mc else None, n, summ
        p["ranked_by"] = "score" if tc.thin_evidence(n, K) else "expectancy"
    filtered = []
    if mn is not None:
        filtered = [p for p in picks if p["expectancy_r"] is None or p["expectancy_r"] < mn]
        picks = [p for p in picks if p not in filtered]
    tk = tie or _by_symbol
    picks = sorted(picks, key=lambda p: tc.rank_key(p.get("expectancy_r"), p.get("past_trades"), p["score"], K)
                   + (tk(p["symbol"]),))
    return picks, filtered


def _by_symbol(sym):
    return sym


# ---------------------------------------------------------------------------
# The account, day by day
# ---------------------------------------------------------------------------

def _charges(side, price, qty, cfg):
    return tc.order_charges(side, price, qty, cfg)["total"]


def make_order(p, sz, cfg):
    """The ticket tayyib-budget would write for a pick (the fields tayyib-risk checks)."""
    pl = p["plan"]
    o = {"id": "%s-%s-%s" % (p["symbol"], pl["signal_date"], pl["setup"]), "symbol": p["symbol"],
         "exchange": cfg["exchange"], "side": "BUY", "product": "CNC", "instrument": "EQ", "qty": sz["qty"],
         "order_type": "SL", "trigger_price": pl["entry"], "limit_price": sz["limit_price"], "stop": pl["stop"],
         "target": pl["target"], "mode": pl["mode"], "setup": pl["setup"], "valid_until": pl["valid_until"],
         "risk_per_share": pl["risk_per_share"], "broker": cfg["broker"], "status": "SIZED"}
    o.update({k: v for k, v in sz.items() if k not in ("qty", "limit_price")})
    return o


def sim_for(p):
    """The time-machine result tayyib-risk reads (sim.json shape), when the Monte Carlo ran for this pick."""
    if p.get("expectancy_r") is None:
        return None
    return {"results": {p["symbol"]: {"plan": {"setup": p["setup"]}, "monte_carlo": {"expectancy_r": p["expectancy_r"]},
                                      "history": p.get("history") or {"trades": p.get("past_trades")}}}}


class Ledger:
    """The book the risk check sees at a close: held positions (positions.json shape) and the plans already
    waiting or approved (counted like approved tickets: heat, count, industry, cash)."""

    def __init__(self, held, pending, uni):
        self.positions = [{"symbol": s, "qty": r["qty"], "entry": r["fill"], "stop": r["plan"]["stop"],
                           "status": "open"} for s, r in sorted(held.items())]
        self.heat = sum(r["loss_at_stop"] for r in pending.values())
        self.count = len(pending)
        self.value = sum(r["reserve"] for r in pending.values())
        self.inds = {}
        for s in sorted(pending):
            self.add_ind(s, uni)

    def add_ind(self, sym, uni):
        ind = tc.halal_status(sym, uni).get("industry") or ""
        if ind:
            self.inds[ind] = self.inds.get(ind, 0) + 1

    def check(self, o, cfg, uni, cash, sim, day, others=()):
        """tc.risk_check_order on this book (plus `others`, extra orders counted as approved), replay mode."""
        heat, count, value, inds = self.heat, self.count, self.value, dict(self.inds)
        for x in others:
            heat += x.get("loss_at_stop_rs", 0)
            value += x["qty"] * x["trigger_price"] + x.get("buy_charges_rs", 0)
            count += 1
            ind = tc.halal_status(x["symbol"], uni).get("industry") or ""
            if ind:
                inds[ind] = inds.get(ind, 0) + 1
        return tc.risk_check_order(o, dict(cfg, cash_available=cash), self.positions, uni, {}, heat, count, inds,
                                   value, sim, today=day, replay=True)

    def approve(self, o, uni):
        self.heat += o.get("loss_at_stop_rs", 0)
        self.value += o["qty"] * o["trigger_price"] + o.get("buy_charges_rs", 0)
        self.count += 1
        self.add_ind(o["symbol"], uni)


def order_matters(picks, cfg, uni, ledger, cash, avail, free, day, take_warn):
    """False when every pick would be bought whatever the order: they fit in the free slots and the cash
    together, and each passes the risk check (WARN counts when WARN plans are taken) with all the others
    already approved. Every limit only gets tighter with more approved orders, so then no order can change
    what is bought, and the time machine need not run."""
    if len(picks) > free:
        return True
    orders, need = [], 0.0
    for p in picks:
        sz = tc.size_trade(p["plan"], cfg, avail)
        if not sz["qty"]:
            return True
        need += sz["qty"] * p["plan"]["entry"] * 1.002
        orders.append(make_order(p, sz, cfg))
    if need > avail:
        return True
    for k, o in enumerate(orders):
        r = ledger.check(o, cfg, uni, cash, None, day, orders[:k] + orders[k + 1:])
        if r["status"] == "BLOCK" or (r["status"] == "WARN" and not take_warn):
            return True
    return False


# ---------------------------------------------------------------------------
# Market regime (v0.2.4): the same rule as tayyib-daily, causal (the index's bars up to day t only)
# ---------------------------------------------------------------------------

REGIME_VARIANTS = ("off", "close_below_200dma:no_new_swing", "close_below_200dma:no_new_trades",
                   "close_below_200dma:half_risk", "sma50_below_sma200:no_new_swing")
BANNER_REGIME_UNKNOWN = ("The regime index could not be fetched, so every regime variant behaves like 'off' (an "
                         "UNKNOWN regime never blocks or allows anything).")


def parse_regime(text):
    """'off' -> None; 'rule:action' -> {"rule", "action"}; anything else -> ValueError."""
    if text in (None, "", "off"):
        return None
    rule, _, action = str(text).partition(":")
    if rule not in tc.REGIME_RULES or action not in tc.REGIME_ACTIONS:
        raise ValueError("--regime must be off or RULE:ACTION with RULE in %s and ACTION in %s"
                         % ("/".join(tc.REGIME_RULES), "/".join(tc.REGIME_ACTIONS)))
    return {"rule": rule, "action": action}


def regime_states(index_bars, days, rule, index):
    """{date: tc.regime_state(...)} for every backtest day, each from the index's bars dated that day or earlier
    only (changing a later bar cannot change an earlier day's state)."""
    bars = sorted([b for b in index_bars or [] if b.get("close") is not None], key=lambda b: b["date"])
    out, k = {}, 0
    for d in sorted(days):
        while k < len(bars) and bars[k]["date"] <= d:
            k += 1
        out[d] = tc.regime_state(bars[max(0, k - 260):k], d, rule, index)
    return out


def risk_off_ranges(states):
    """C3 (v0.2.5): the risk-off stretches of a {date: state} map, in backtest days -> [{start, end, days}]
    (days = trading days in the window), so they can be checked against a chart of the index."""
    out, cur = [], None
    for d in sorted(states):
        if (states[d] or {}).get("state") == "risk-off":
            if cur is None:
                cur = {"start": d, "end": d, "days": 0}
                out.append(cur)
            cur["end"], cur["days"] = d, cur["days"] + 1
        else:
            cur = None
    return out


def worst_year(curve):
    """The calendar year with the lowest return on the account's equity (a part year is marked partial)."""
    if not curve:
        return None
    by, prev, first_year = {}, curve[0]["equity"], curve[0]["date"][:4]
    for c in curve:
        y = c["date"][:4]
        if y not in by:
            by[y] = {"start": prev, "end": c["equity"], "first": c["date"], "last": c["date"]}
        by[y]["end"], by[y]["last"] = c["equity"], c["date"]
        prev = c["equity"]
    rows = []
    for y, v in sorted(by.items()):
        partial = (y == first_year and not v["first"].endswith(("01-01", "01-02", "01-03", "01-04", "01-05"))) or \
                  (y == curve[-1]["date"][:4] and v["last"] < y + "-12-24")
        rows.append({"year": int(y), "return_pct": round((v["end"] / v["start"] - 1) * 100, 2) if v["start"] else None,
                     "partial": partial})
    rows = [r for r in rows if r["return_pct"] is not None]
    return min(rows, key=lambda r: r["return_pct"]) if rows else None


def regime_column(name, sim, capital, split):
    m, _ = all_metrics(sim, capital, split)
    o = m["overall"]
    tr = sim["trades"]
    sw = trade_stats([t for t in tr if t["mode"] == "swing"])
    pb = trade_stats([t for t in tr if t["setup"] == "pullback"])
    c = sim["counts"]
    return {"variant": name, "trades": o["trades"], "win_rate_pct": o["win_rate_pct"], "expectancy_r": o["expectancy_r"],
            "cagr_pct": o["cagr_pct"], "max_drawdown_pct": o["max_drawdown_pct"], "worst_year": worst_year(sim["curve"]),
            "swing_trades": sw["trades"], "swing_expectancy_r": sw["expectancy_r"],
            "pullback_trades": pb["trades"], "pullback_expectancy_r": pb["expectancy_r"],
            "risk_off_days": c.get("regime_risk_off_days", 0), "unknown_days": c.get("regime_unknown_days", 0),
            "picks_held_back": c.get("regime_blocked", 0), "too_few": o["trades"] < MIN_TRADES}


def new_counts():
    return {"signal_days": 0, "regime_risk_off_days": 0, "regime_unknown_days": 0, "regime_blocked": 0,
            "regime_half_risk_days": 0, "plans": 0, "not_triggered": 0, "no_cash_at_fill": 0, "qty_cut_at_fill": 0,
            "not_sized": 0, "no_slot": 0, "tm_days": 0, "risk_checked": 0, "risk_blocked_plans": 0,
            "risk_blocked": {}, "risk_warned": {}, "warn_taken": 0, "warn_skipped": 0,
            "not_replayed": {k: 0 for k in NOT_REPLAYED}}


def simulate(data, cfg, start, end, mode="all", setups=None, max_positions=5, progress=None, uni=None,
             take_warn=True, rank="tm", regime=None, tie=None, cache=None):
    """Run the strategy over [start, end] on {sym: bars} (compliant stocks only, bars up to `end`).
    rank: "tm" (tayyib-daily's order, with the time machine) or "score" (setup score only, for --compare).
    regime (v0.2.4): None, or {"rule", "action", "states": {date: regime_state}}: on a risk-off day the action
    applies to that day's new plans, as live (an UNKNOWN day: no effect).
    tie (v0.2.6, --robust): the order of equal-ranked signals (None: by symbol, as always). cache: a RunCache
    shared by robust runs on the same bars (the result is the same with or without it).
    -> {trades[], curve[], counts, days}."""
    uni = uni if uni is not None else {"stocks": {}}
    books = cache.books_for(data) if cache is not None else {s: Book(b) for s, b in data.items()}
    extra = {"tie": tie, "cache": cache} if tie is not None or cache is not None else {}
    days = sorted({b["date"] for bk in books.values() for b in bk.bars if start <= b["date"] <= end})
    capital = float(cfg["capital"])
    cash = capital
    pending, held, trades, curve = {}, {}, [], []
    last_close = {}
    counts = new_counts()

    def outcome(rec):
        pl = dict(rec["plan"], qty=rec["qty"])
        return tc.trade_outcome(books[rec["symbol"]].bars, pl, cfg, today=end)

    def close(rec, px, date, reason):
        """Sell; returns the proceeds (usable from the next trading day)."""
        nonlocal cash
        sell = _charges("SELL", px, rec["qty"], cfg)
        got = rec["qty"] * px - sell
        cash += got
        o = rec["out"]
        trades.append({
            "symbol": rec["symbol"], "setup": rec["setup"], "mode": rec["mode"],
            "signal_date": rec["plan"]["signal_date"], "entry_date": rec["filled"], "entry_price": rec["fill"],
            "exit_date": date, "exit_price": round(px, 2), "exit_reason": reason, "qty": rec["qty"],
            "charges": round(rec["buy_charges"] + sell, 2), "pnl_rs": o["pnl_rs"], "r": o["r"],
            "plan_entry": rec["plan"]["entry"], "stop": rec["plan"]["stop"], "target": rec["plan"]["target"],
            "valid_until": rec["plan"]["valid_until"], "score": rec["score"], "ranked_by": rec["ranked_by"],
            "expectancy_r": rec.get("expectancy_r"), "past_trades": rec.get("past_trades"),
            "risk": rec["risk"], "qty_cut_at_fill": rec.get("qty_cut", False)})
        return got

    for n_day, d in enumerate(days):
        if progress and n_day % 50 == 0:
            progress("day %d/%d %s" % (n_day + 1, len(days), d))
        for s, bk in books.items():
            k = bk.idx.get(d)
            if k is not None:
                last_close[s] = bk.bars[k]["close"]
        settling = 0.0                                       # today's sale proceeds: usable from tomorrow
        # 1. exits of positions already held
        for s in sorted(held):
            rec = held[s]
            if rec["out"]["exited"] == d:
                settling += close(rec, rec["out"]["exit"], d, rec["out"]["status"])
                del held[s]
        # 2. fills: paid from cash that is free today (not today's proceeds, not other plans' cash); a gap up
        #    that costs more than that cuts the quantity
        for s in sorted(pending):
            rec = pending[s]
            if rec["out"]["filled"] != d:
                continue
            del pending[s]
            fill = rec["out"]["fill"]
            room = cash - settling - sum(r["reserve"] for r in pending.values())
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
                settling += close(rec, rec["out"]["exit"], d, rec["out"]["status"])
                del held[s]
        # 3. plans that were never triggered expire at valid_until
        for s in sorted(pending):
            if pending[s]["plan"]["valid_until"] <= d:
                counts["not_triggered"] += 1
                del pending[s]
        # 4. the close: today's list, ranked, sized and risk-checked against the simulated book
        if d != days[-1]:
            eff, cfg_day = {"active": False, "block_modes": [], "risk_factor": 1.0}, cfg
            if regime:
                st = regime["states"].get(d) or {"state": "UNKNOWN"}
                eff = tc.regime_effect(st, {"enabled": True, "action": regime["action"]})
                counts["regime_risk_off_days"] += st["state"] == "risk-off"
                counts["regime_unknown_days"] += st["state"] == "UNKNOWN"
                if eff["risk_factor"] != 1.0:
                    counts["regime_half_risk_days"] += 1
                    cfg_day = dict(cfg, max_risk_per_trade_pct=cfg["max_risk_per_trade_pct"] * eff["risk_factor"])
            picks = scan_day(books, d, cfg, mode, setups, set(held) | set(pending), **extra)
            if eff["block_modes"]:
                kept = [p for p in picks if p["mode"] not in eff["block_modes"]]
                counts["regime_blocked"] += len(picks) - len(kept)
                picks = kept
            if picks:
                counts["signal_days"] += 1
                place_day(books, picks, cfg_day, uni, d, cash, held, pending, max_positions, take_warn, rank, counts,
                          outcome, **extra)
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


def place_day(books, picks, cfg, uni, d, cash, held, pending, max_positions, take_warn, rank, counts, outcome, tie=None,
              cache=None):
    """Step 4 of a day, like tayyib-daily: rank, size in that order (each sized ticket uses up cash for the
    ones after it, as size.py does), risk-check each against held + waiting + earlier approved (check.py's
    file order), and place the PASS (and, with take_warn, WARN) plans. BLOCK is never placed."""
    free = max_positions - len(held) - len(pending)
    if free <= 0:
        counts["no_slot"] += len(picks)
        return
    day = tc.parse_date(d)
    avail = cash - sum(r["reserve"] for r in pending.values())
    ledger = Ledger(held, pending, uni)
    tk = tie or _by_symbol
    if rank == "score":
        ordered = sorted(picks, key=lambda p: (-p["score"], tk(p["symbol"])))
        for p in ordered:
            p["ranked_by"] = "score only (--compare)"
    elif cfg["daily"].get("min_expectancy_r") is not None or not take_warn or \
            order_matters(picks, cfg, uni, ledger, cash, avail, free, day, take_warn):
        ordered, filtered = rank_day(books, picks, cfg, all_mc=not take_warn, tie=tie, cache=cache)
        counts["tm_days"] += 1
        counts["not_sized"] += len(filtered)
    else:
        ordered = sorted(picks, key=lambda p: tk(p["symbol"]))
        for p in ordered:
            p["ranked_by"] = "not needed (every pick fitted)"
    sizing_cash = avail
    for p in ordered:
        if len(held) + len(pending) >= max_positions:
            counts["no_slot"] += 1
            continue
        sz = tc.size_trade(p["plan"], cfg, sizing_cash)
        if not sz["qty"]:
            counts["not_sized"] += 1
            continue
        sizing_cash -= sz["position_value_rs"]
        o = make_order(p, sz, cfg)
        r = ledger.check(o, cfg, uni, cash, sim_for(p), day)
        counts["risk_checked"] += 1
        for k in NOT_REPLAYED:
            counts["not_replayed"][k] += 1
        if r["status"] == "BLOCK":
            counts["risk_blocked_plans"] += 1
            for x in r["block"]:
                n = reason_name(x)
                counts["risk_blocked"][n] = counts["risk_blocked"].get(n, 0) + 1
            continue
        if r["status"] == "WARN":
            for x in r["warn"]:
                n = reason_name(x)
                counts["risk_warned"][n] = counts["risk_warned"].get(n, 0) + 1
            if not take_warn:
                counts["warn_skipped"] += 1
                continue
            counts["warn_taken"] += 1
        ledger.approve(o, uni)
        rec = {"symbol": p["symbol"], "setup": p["setup"], "mode": p["mode"], "score": p["score"],
               "plan": p["plan"], "qty": sz["qty"], "ranked_by": p.get("ranked_by"),
               "expectancy_r": p.get("expectancy_r"), "past_trades": p.get("past_trades"), "risk": r["status"],
               "reserve": sz["position_value_rs"] + sz["buy_charges_rs"], "loss_at_stop": sz["loss_at_stop_rs"]}
        rec["out"] = outcome(rec)
        pending[p["symbol"]] = rec
        counts["plans"] += 1


# ---------------------------------------------------------------------------
# Robustness (v0.2.6): one window, many small variations, a range of results instead of one number
# ---------------------------------------------------------------------------

ROBUST_DEFAULT, ROBUST_MAX = 20, 50
ROBUST_MAX_POSITIONS = (3, 5, 8)
ROBUST_METRICS = (("cagr_pct", "CAGR", "%"), ("expectancy_r", "Expectancy", "R"),
                  ("max_drawdown_pct", "Max drawdown", "%"), ("trades", "Trades", ""))
VERDICT_SHARE = 0.8                     # B must beat A on at least 80% of the seeds (or lose on 80%) for a verdict
NO_CLEAR = "No clear difference: don't change the default on this evidence"
ROBUST_NOTE = ("Each run is the same window on the same prices (nothing downloaded again) with one small, "
               "meaningless change, fixed by its seed: the order of signals that rank equal, and the start moved "
               "one trading day earlier or later. A strategy whose result swings a lot under changes like these "
               "cannot be judged on one run. Max positions 3 / 5 / 8: the plain run with only that limit changed.")


class RunCache:
    """Shared by every run on one set of bars: the stocks' indicators (built once), each day's signals and plans
    and each pick's time-machine answer, keyed by the settings that decide them. A seed only changes the order
    of equal-ranked signals and the start day, so with the cache a run gives exactly what it gives without it."""

    def __init__(self):
        self.books, self.store, self._dg = {}, {}, {}

    def books_for(self, data):
        for s, b in data.items():
            if s not in self.books or self.books[s].bars is not b:
                self.books[s] = Book(b)
        return {s: self.books[s] for s in data}

    def digest(self, cfg):
        k = id(cfg)
        hit = self._dg.get(k)
        if hit is None or hit[0] is not cfg:
            hit = (cfg, hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")).hexdigest())
            self._dg[k] = hit
        return hit[1]

    def universe(self, books):
        hit = self._dg.get(("u", id(books)))
        if hit is None or hit[0] is not books:
            hit = (books, hashlib.sha1("|".join(sorted(books)).encode("utf-8")).hexdigest()[:12])
            self._dg[("u", id(books))] = hit
        return hit[1]


def tie_key(seed):
    """The order of equal-ranked signals for a seed: a fixed shuffle of the symbols (sha1 of seed:symbol), the
    same every time for the same seed. None -> by symbol (the plain run)."""
    if seed is None:
        return None

    def key(sym):
        return hashlib.sha1(("%d:%s" % (seed, sym)).encode("utf-8")).hexdigest()
    return key


def tie_order(seed, syms):
    k = tie_key(seed) or _by_symbol
    return sorted(syms, key=k)


def seed_shift(seed):
    """-1 or +1: the trading days the start moves for this seed (random.Random(seed): the same every time)."""
    return random.Random(seed).choice((-1, 1))


def shifted_start(dates, start, shift):
    """The trading day `shift` sessions from the first session on or after `start` (dates: every bar date)."""
    k = next((i for i, d in enumerate(dates) if d >= start), len(dates) - 1)
    return dates[min(max(k + shift, 0), len(dates) - 1)]


def percentile(xs, q):
    """Linear between the closest ranks (numpy's default); xs sorted, not empty."""
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def distribution(values, d=2):
    """-> {n, unknown, median, p10, p90, min, max} of the known values (None = UNKNOWN, left out and counted)."""
    xs = sorted(v for v in values if v is not None)
    out = {"n": len(xs), "unknown": sum(1 for v in values if v is None)}
    if not xs:
        out.update(median=None, p10=None, p90=None, min=None, max=None)
        return out
    out.update(median=round(percentile(xs, 0.5), d), p10=round(percentile(xs, 0.1), d),
               p90=round(percentile(xs, 0.9), d), min=round(xs[0], d), max=round(xs[-1], d))
    return out


def _pick(m):
    return {k: (m or {}).get(k) for k, _, _ in ROBUST_METRICS} if m else \
        {"cagr_pct": None, "expectancy_r": None, "max_drawdown_pct": None, "trades": 0}


def run_row(name, sim, capital, split, bench_cagr):
    m, _ = all_metrics(sim, capital, split)
    o = m["overall"]
    beat = None if bench_cagr is None or o.get("cagr_pct") is None else o["cagr_pct"] > bench_cagr
    return {"run": name, "start": sim["days"][0] if sim["days"] else None, "overall": dict(_pick(o), win_rate_pct=o["win_rate_pct"]),
            "by_mode": {g: _pick(x) for g, x in m["by_mode"].items()},
            "by_setup": {g: _pick(x) for g, x in m["by_setup"].items()},
            "benchmark_cagr_pct": bench_cagr, "beat_benchmark": beat}


def beat_share(rows, get):
    """How many runs had a CAGR above the Shariah ETF's over the same days (UNKNOWN when it could not be had)."""
    known = [(get(r), r["benchmark_cagr_pct"]) for r in rows]
    known = [(c, b) for c, b in known if c is not None and b is not None]
    if not known:
        return {"runs": None, "of": len(rows), "pct": None,
                "text": "Above the Shariah ETF: UNKNOWN (the ETF's prices could not be had)"}
    k = sum(1 for c, b in known if c > b)
    return {"runs": k, "of": len(known), "pct": round(k / len(known) * 100, 1),
            "text": "CAGR above the Shariah ETF (buy and hold, same days) in %d of %d runs (%.0f%%)"
                    % (k, len(known), k / len(known) * 100)}


def summarise(rows):
    """The spread of the seeded runs: each metric's distribution, overall, per mode and per setup, and the share
    of runs that beat the Shariah ETF."""
    out = {"runs": len(rows),
           "overall": {k: distribution([r["overall"][k] for r in rows], 3 if u == "R" else 2) for k, _, u in ROBUST_METRICS},
           "beat_benchmark": beat_share(rows, lambda r: r["overall"]["cagr_pct"])}
    for grp in ("by_mode", "by_setup"):
        out[grp] = {}
        for g in sorted({g for r in rows for g in r[grp]}):
            cells = [r[grp].get(g) or _pick(None) for r in rows]
            d = {k: distribution([c[k] for c in cells], 3 if u == "R" else 2) for k, _, u in ROBUST_METRICS}
            d["beat_benchmark"] = beat_share(rows, lambda r, g=g: (r[grp].get(g) or {}).get("cagr_pct"))
            out[grp][g] = d
    return out


def robust_side(data, cfg, params, uni, n, cache, bench_cagr, regime=None, base_sim=None, progress=None, label=None):
    """B1: n seeded runs and the fixed max-positions 3 / 5 / 8 runs for one set of settings -> {runs[], summary,
    max_positions[]}. bench_cagr(start) -> the Shariah ETF's CAGR from that start (None when UNKNOWN)."""
    start, end, split = params["from"], params["to"], params["split"]
    dates = sorted({b["date"] for bs in data.values() for b in bs if b["date"] <= end})
    capital = float(cfg["capital"])
    kw = dict(mode=params["mode"], setups=params["setups"], uni=uni, take_warn=params["take_warn"], rank="tm",
              regime=regime, cache=cache)
    rows = []
    for seed in range(1, n + 1):
        if progress:
            progress("robust%s: seed %d/%d" % (" " + label if label else "", seed, n))
        sh = seed_shift(seed)
        st = shifted_start(dates, start, sh)
        sim = simulate(data, cfg, st, end, max_positions=params["max_positions"], tie=tie_key(seed), **kw)
        row = run_row("seed %d" % seed, sim, capital, split, bench_cagr(st))
        row.update(seed=seed, shift_days=sh, tie_first=tie_order(seed, sorted(data))[:5])
        rows.append(row)
    sens = []
    for mp in ROBUST_MAX_POSITIONS:
        if progress:
            progress("robust%s: max positions %d" % (" " + label if label else "", mp))
        if base_sim is not None and mp == params["max_positions"]:
            sim = base_sim
        else:
            sim = simulate(data, cfg, start, end, max_positions=mp, **kw)
        r = run_row("max positions %d" % mp, sim, capital, split, bench_cagr(start))
        r["max_positions"] = mp
        sens.append(r)
    return {"runs": rows, "summary": summarise(rows), "max_positions": sens}


def verdict(beat, lost, n):
    """B3: "B is better in X of N runs" when B's CAGR beat A's on at least 80% of the seeds; "B is worse in X of N
    runs" when it lost on at least 80% (B beat A on at most 20%; equal runs count for neither); otherwise no clear
    difference."""
    if n and beat >= VERDICT_SHARE * n:
        return "better", "B is better in %d of %d runs" % (beat, n)
    if n and lost >= VERDICT_SHARE * n:
        return "worse", "B is worse in %d of %d runs" % (lost, n)
    return "unclear", NO_CLEAR


def paired(a_rows, b_rows):
    """Per seed: B minus A for each metric (the same seed = the same tie order and start for both)."""
    out = []
    for ra, rb in zip(a_rows, b_rows):
        assert ra["seed"] == rb["seed"] and ra["start"] == rb["start"], "unpaired seeds"
        d = {"seed": ra["seed"], "start": ra["start"]}
        for k, _, _ in ROBUST_METRICS:
            x, y = ra["overall"][k], rb["overall"][k]
            d[k] = None if x is None or y is None else round(y - x, 3)
        out.append(d)
    return out


def compare_summary(pairs):
    n = len(pairs)
    beat = sum(1 for p in pairs if p["cagr_pct"] is not None and p["cagr_pct"] > 0)
    lost = sum(1 for p in pairs if p["cagr_pct"] is not None and p["cagr_pct"] < 0)
    kind, text = verdict(beat, lost, n)
    return {"seeds": n, "b_beat_a": beat, "b_lost": lost, "equal_or_unknown": n - beat - lost,
            "b_beat_a_pct": round(beat / n * 100, 1) if n else None,
            "difference": {k: distribution([p[k] for p in pairs], 3 if u == "R" else 2) for k, _, u in ROBUST_METRICS},
            "verdict": kind, "verdict_text": text,
            "basis": "Judged on CAGR, seed by seed: B's run against A's run with the same seed (same prices, same "
                     "tie order, same start). Equal runs count for neither side."}


def parse_settings(text, raw):
    """--robust-compare's settings: 'default' (your config.json as it is) or KEY=VALUE pairs separated by commas or
    spaces, over your config.json: a dotted setting (scanner.setups.pullback.enabled=false; on / off mean true /
    false), a setup by name (pullback=off), or regime=off|RULE:ACTION (the backtest's regime filter).
    -> (label, config dict, regime text). Every value goes through tc.validate_config: one it would not accept is
    refused, never ignored (so A and B differ in exactly what you wrote)."""
    import copy as _copy
    user = _copy.deepcopy(raw or {})
    regime, label = "off", (text or "").strip() or "default"
    parts = [x for x in re.split(r"[,\s]+", label) if x and x != "default"]
    for part in parts:
        k, eq, v = part.partition("=")
        if not eq or not k:
            raise ValueError("settings must be KEY=VALUE (got %r)" % part)
        if k == "regime":
            parse_regime(v)
            regime = v
            continue
        if k in tc.SWING_SETUPS + tc.DELIVERY_SETUPS:
            k = "scanner.setups.%s.enabled" % k
        doc = tc.DEFAULT_CONFIG_DOCS.get(k)
        if not doc or doc.get("type") == "locked" or tc.is_account_key(k):
            raise ValueError("%s is not a strategy setting you can vary here" % k)
        low = v.lower()
        val = True if low in ("on", "true", "yes") else False if low in ("off", "false", "no") else None
        if val is None:
            try:
                val = json.loads(v)
            except ValueError:
                val = v
        d = user
        ks = k.split(".")
        for x in ks[:-1]:
            d = d.setdefault(x, {})
            if not isinstance(d, dict):
                raise ValueError("%s: %s is not a group of settings" % (k, x))
        d[ks[-1]] = val
    cfg, notes = tc.validate_config(user)
    errs = tc.config_errors(notes)
    if errs:
        raise ValueError("; ".join(errs))
    return label, cfg, regime


def robust_section(sides, params, uni, n, cache, bench_cagr, progress=None):
    """B1 / B3 over the same bars: sides = [(name, label, data, cfg, regime text, regime dict, base sim or None)]."""
    out = {}
    for name, label, data, cfg, rtext, reg, base in sides:
        rb = robust_side(data, cfg, params, uni, n, cache, bench_cagr, regime=reg, base_sim=base, progress=progress,
                         label=name if len(sides) > 1 else None)
        snap = tc.settings_snapshot(cfg)
        rb["settings"] = {"label": label, "settings_label": snap["label"], "hash": snap["hash"], "same_as": snap["same_as"]}
        rb["regime"] = rtext or "off"
        out[name] = rb
    return out


def robust_md(rb, title="Robustness"):
    s = rb["summary"]
    L = ["## %s: %d seeded runs (%s)" % (title, s["runs"], rb["settings"]["label"]), "", ROBUST_NOTE, ""]
    L += robust_table(s)
    L += ["", s["beat_benchmark"]["text"] + ".", ""]
    for grp, head in (("by_mode", "mode"), ("by_setup", "setup")):
        if s[grp]:
            L += ["| %s | trades (median) | CAGR median | CAGR 10th-90th | expectancy median | expectancy 10th-90th | "
                  "max DD median | above the ETF |" % head, "|---|---|---|---|---|---|---|---|"]
            for g, d in s[grp].items():
                L.append("| %s | %s | %s | %s to %s | %s | %s to %s | %s | %s |" % (
                    g, fmt(d["trades"]["median"], "", 0), fmt(d["cagr_pct"]["median"], "%"), fmt(d["cagr_pct"]["p10"], "%"),
                    fmt(d["cagr_pct"]["p90"], "%"), fmt(d["expectancy_r"]["median"], "R"), fmt(d["expectancy_r"]["p10"], "R"),
                    fmt(d["expectancy_r"]["p90"], "R"), fmt(d["max_drawdown_pct"]["median"], "%"),
                    "UNKNOWN" if d["beat_benchmark"]["runs"] is None else "%d of %d" % (d["beat_benchmark"]["runs"], d["beat_benchmark"]["of"])))
            L.append("")
    L += ["Max positions (the plain run, only this limit changed):", "",
          "| max positions | trades | win rate | expectancy | CAGR | max drawdown | above the ETF |", "|---|---|---|---|---|---|---|"]
    for r in rb["max_positions"]:
        o = r["overall"]
        L.append("| %d | %d | %s | %s | %s | %s | %s |" % (r["max_positions"], o["trades"], fmt(o["win_rate_pct"], "%", 1),
                                                           fmt(o["expectancy_r"], "R"), fmt(o["cagr_pct"], "%"),
                                                           fmt(o["max_drawdown_pct"], "%"),
                                                           "UNKNOWN" if r["beat_benchmark"] is None else ("yes" if r["beat_benchmark"] else "no")))
    return L + [""]


def robust_table(s):
    L = ["| | median | 10th pct | 90th pct | min | max |", "|---|---|---|---|---|---|"]
    for k, name, u in ROBUST_METRICS:
        d = s["overall"][k] if "overall" in s else s[k]
        dd = 0 if u == "" else 3 if u == "R" else 2
        L.append("| %s | %s |" % (name, " | ".join(fmt(d[x], u, dd) for x in ("median", "p10", "p90", "min", "max"))))
    return L


def robust_compare_md(rc):
    c = rc["compare"]
    L = ["## Robust compare: A = %s, B = %s" % (rc["a"]["settings"]["label"], rc["b"]["settings"]["label"]), "",
         "**%s.**" % c["verdict_text"], "", c["basis"], "",
         "B beat A on %d of %d seeds, lost on %d, equal or UNKNOWN on %d." % (c["b_beat_a"], c["seeds"], c["b_lost"],
                                                                            c["equal_or_unknown"]), "",
         "B minus A, per seed:", ""]
    L += robust_table(c["difference"]) + [""]
    for side in ("a", "b"):
        L += robust_md(rc[side], title="Side %s" % side.upper())
    return L


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

# v0.2.9: the metrics live in core (the paper account uses them too); the old names stay
_r2 = tc._r2
curve_stats = tc.curve_stats
trade_stats = tc.trade_stats


def flag_few(m):
    """Groups (setup, mode, in / out of sample) with under MIN_TRADES trades are noise: too_few true."""
    m["too_few"] = m["trades"] < MIN_TRADES
    return m


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
        out[g] = flag_few(m)
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
        res[name] = flag_few(m)
    return res


def all_metrics(sim, capital, split):
    trades, curve, days = sim["trades"], sim["curve"], sim["days"]
    overall = trade_stats(trades)
    overall.update(curve_stats([(c["date"], c["equity"], c["open_positions"] > 0) for c in curve]))
    return ({"overall": overall, "by_setup": group_metrics(trades, days, capital, "setup"),
             "by_mode": group_metrics(trades, days, capital, "mode")}, split_metrics(trades, curve, split))


# ---------------------------------------------------------------------------
# Benchmarks: buy and hold, one set of charges
# ---------------------------------------------------------------------------

def benchmark(sym, name, range_, start, end, capital, cfg, fetch=None):
    """Buy and hold with all the capital, one buy and one sell charge; UNKNOWN with the reason when the data
    cannot be had (tc.buy_hold_benchmark, v0.2.9)."""
    return tc.buy_hold_benchmark(sym, name, range_, start, end, capital, cfg, fetch=fetch)


# ---------------------------------------------------------------------------
# v0.2.8 "My stocks": buying and holding the same basket, and the strategy stock by stock
# ---------------------------------------------------------------------------

def _units(money, price, cfg):
    """Fractional units that `money` buys at `price` with the buy charge paid out of it (as benchmark())."""
    units = money / price
    for _ in range(3):
        units = (money - _charges("BUY", price, units, cfg)) / price
    return units


def basket_benchmark(chosen, data, skipped, late, days, capital, cfg, no_late=False):
    """Buy and hold the chosen stocks on the strategy's own days and bars (nothing downloaded). The capital is split
    equally across the stocks that are in the test; each is bought at the close of its first day in the window on or
    after the day it joins the test (WARMUP_BARS of history, as for the strategy), so a late joiner's share waits as
    cash until then. One buy charge each; on the last day every stock is valued at its last close after one sell
    charge. A stock with no usable prices (or left out with --no-late) is UNKNOWN, out of the basket, and listed."""
    reasons = {x["symbol"]: x["reason"] for x in skipped or []}
    late_syms = {x["symbol"] for x in late or []}
    stocks, left_out, eligible = {}, [], []
    for s in chosen:
        if s in data and not (no_late and s in late_syms):
            eligible.append(s)
            continue
        why = ("left out with --no-late (listed during the window)" if s in data else
               reasons.get(s) or "no price data")
        stocks[s] = {"status": "UNKNOWN", "reason": why}
        left_out.append({"symbol": s, "reason": why})
    res = {"symbol": "BASKET", "name": BASKET_NAME, "status": "UNKNOWN", "stocks": stocks, "left_out": left_out,
           "in_basket": len(eligible), "note": BASKET_NOTE}
    if not eligible or len(days) < 2:
        res["reason"] = ("no chosen stock had usable prices in the window" if not eligible else
                         "fewer than 2 trading days in the window")
        return res
    first, last = days[0], days[-1]
    share = capital / len(eligible)
    plan = {}
    for s in eligible:
        bars = [b for b in data[s] if b["date"] <= last]
        buy_from = max(first, join_date(bars) or first)
        k = next((i for i, b in enumerate(bars) if b["date"] >= buy_from), None)
        if k is None:                                   # cannot happen for a stock in the test; never invented
            stocks[s] = {"status": "UNKNOWN", "reason": "no price on or after %s" % buy_from}
            continue
        p0 = bars[k]["close"]
        u = _units(share, p0, cfg)
        plan[s] = {"buy_date": bars[k]["date"], "buy_price": p0, "units": u, "buy_charges": _charges("BUY", p0, u, cfg),
                   "closes": {b["date"]: b["close"] for b in bars[k:]}, "late": s in late_syms}
    pts, last_close, bought = [], {}, set()
    for d in days:
        for s in plan:
            c = plan[s]["closes"].get(d)
            if c is not None:
                last_close[s] = c
            if s not in bought and d >= plan[s]["buy_date"] and s in last_close:
                bought.add(s)
        cash = capital - share * len(bought)
        value = cash + sum(plan[s]["units"] * last_close[s] for s in bought)
        if d == last:
            value -= sum(_charges("SELL", last_close[s], plan[s]["units"], cfg) for s in bought)
        pts.append((d, value, bool(bought)))
    pts[0] = (pts[0][0], capital, pts[0][2])            # as benchmark(): the first point is the capital itself
    total_ch = 0.0
    for s, pl in plan.items():
        lc = last_close[s]
        sell = _charges("SELL", lc, pl["units"], cfg)
        end_value = pl["units"] * lc - sell
        total_ch += pl["buy_charges"] + sell
        stocks[s] = {"status": "OK", "buy_date": pl["buy_date"], "buy_price": round(pl["buy_price"], 2),
                     "end_price": round(lc, 2), "units": round(pl["units"], 4), "joined_late": pl["late"],
                     "share_rs": round(share, 2), "end_value_rs": round(end_value, 2),
                     "charges_rs": round(pl["buy_charges"] + sell, 2),
                     "return_pct": round((end_value / share - 1) * 100, 2)}
    st = curve_stats(pts)
    st.pop("exposure_pct", None)
    res.update(status="OK", start=first, end=last, share_rs=round(share, 2), charges_rs=round(total_ch, 2), **st)
    res["curve"] = [[d, round(v, 2)] for d, v, _ in pts]
    res["stocks"] = {s: stocks[s] for s in chosen if s in stocks}
    return res


def stock_table(chosen, trades, basket, uni):
    """A5: one row per chosen stock: its trades, wins, win rate, total R and P&L, its buy-and-hold return over the
    same window, and "better" / "worse" / "no trades" (strategy return on its slice vs holding it). The rows add up
    to the run's totals (every trade is on a chosen stock). Under MIN_TRADES trades: too_few."""
    share = basket.get("share_rs")
    rows = []
    for s in chosen:
        ts = [t for t in trades if t["symbol"] == s]
        n = len(ts)
        wins = sum(1 for t in ts if t["r"] > 0)
        pnl = round(sum(t["pnl_rs"] for t in ts), 2)
        b = (basket.get("stocks") or {}).get(s) or {"status": "UNKNOWN", "reason": "not in the basket"}
        hold = b.get("return_pct") if b.get("status") == "OK" else None
        strat = round(pnl / share * 100, 2) if share and b.get("status") == "OK" else None
        if not n:
            vs = "no trades"
        elif hold is None or strat is None:
            vs = "UNKNOWN"
        else:
            vs = "better" if strat > hold else "worse" if strat < hold else "same"
        rows.append({"symbol": s, "name": tc.halal_status(s, uni).get("name"), "trades": n, "wins": wins,
                     "win_rate_pct": round(wins / n * 100, 1) if n else None,
                     "total_r": round(sum(t["r"] for t in ts), 3), "pnl_rs": pnl,
                     "strategy_return_pct": strat, "hold_return_pct": hold, "hold_status": b.get("status"),
                     "hold_note": b.get("reason"), "buy_date": b.get("buy_date"), "vs": vs,
                     "too_few": n < MIN_TRADES})
    tot = {"trades": sum(r["trades"] for r in rows), "wins": sum(r["wins"] for r in rows),
           "total_r": round(sum(r["total_r"] for r in rows), 3), "pnl_rs": round(sum(r["pnl_rs"] for r in rows), 2)}
    return {"rows": rows, "totals": tot, "note": STOCKS_NOTE,
            "outside": sorted({t["symbol"] for t in trades} - set(chosen))}    # always empty: a test checks it


def basket_banners(n_tested, overall, basket):
    """A6: always at the top in symbols / holdings mode: hindsight; small basket under SMALL_BASKET stocks; holding
    the basket did better (when its CAGR beats the strategy's); the stocks left out of the basket."""
    b = [BANNER_HINDSIGHT]
    if n_tested < SMALL_BASKET:
        b.append(BANNER_SMALL)
    if basket.get("status") == "OK" and basket.get("cagr_pct") is not None and overall.get("cagr_pct") is not None \
            and basket["cagr_pct"] > overall["cagr_pct"]:
        b.append(BANNER_HOLD)
    if basket.get("left_out"):
        b.append("Left out of the test and the basket (UNKNOWN): %s." % "; ".join(
            "%s (%s)" % (x["symbol"], x["reason"]) for x in basket["left_out"]))
    if basket.get("status") != "OK":
        b.append("Buying and holding these stocks is UNKNOWN: %s." % basket.get("reason"))
    return b


def universe_label(res):
    """A8: "all 183", "5 stocks: TCS, INFY, ..." or "3 held stocks: ..." (older runs: all)."""
    u = res.get("universe") or {}
    mode = u.get("mode") or (res.get("params") or {}).get("universe_mode") or "all"
    if mode == "all":
        return "all %s" % u.get("compliant", "?")
    syms = u.get("symbols") or (res.get("params") or {}).get("symbols") or []
    head = ", ".join(syms[:5]) + (", +%d more" % (len(syms) - 5) if len(syms) > 5 else "")
    return "%s: %s" % (tc.plural(len(syms), "held stock" if mode == "holdings" else "stock"), head)


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------

def _beat(bench, overall):
    return (bench or {}).get("status") == "OK" and overall.get("cagr_pct") is not None \
        and bench.get("cagr_pct") is not None and overall["cagr_pct"] < bench["cagr_pct"]


def banners(overall, split, benches):
    b = [BANNER_HALAL, BANNER_SURVIVOR, BANNER_PAST, BANNER_NEWS]
    if overall["trades"] < MIN_TRADES:
        b.append(BANNER_FEW)
    ise, ose = split["in_sample"]["expectancy_r"], split["out_of_sample"]["expectancy_r"]
    if overfit(ise, ose):
        b.append(BANNER_OVERFIT)
    etf = benches.get(SHARIAH_BENCH) or {}
    if etf.get("status") != "OK":
        b.append(BANNER_NO_ETF)
    elif _beat(etf, overall):
        b.append(BANNER_ETF)
    if _beat(benches.get(NIFTY), overall):
        b.append(BANNER_NIFTY)
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

def default_end(now, cfg):
    """The last completed NSE session at `now` (IST) -> (YYYY-MM-DD, end_rule). Today once it is 15:30 IST on a
    trading day (a stock with no bar today then simply ends on the session before); otherwise the previous
    trading day (weekends and the holidays in config skipped). A bar made during market hours is never used."""
    d = now.date()
    if tc.is_trading_day(d, cfg) and now.hour * 60 + now.minute >= 15 * 60 + 30:
        return d.isoformat(), "last completed session: today (%s, after 15:30 IST)" % d.isoformat()
    p = d - dt.timedelta(days=1)
    while not tc.is_trading_day(p, cfg):
        p -= dt.timedelta(days=1)
    why = ("before 15:30 IST" if tc.is_trading_day(d, cfg) else "today is not a trading day")
    return p.isoformat(), "last completed session: the previous trading day (%s; %s)" % (p.isoformat(), why)


def window(a, now, cfg):
    """-> (start, end, split, end_rule)."""
    if a.to:
        end, rule = a.to, "--to %s" % a.to
    else:
        end, rule = default_end(now, cfg)
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
    return start, end, split, rule


def robust_results(params, cfg, uni, used, sim, main_regime, regimes, robust_sides, cache, bench_get, range_, capital,
                   progress):
    """--robust: the seeded runs for your settings; --robust-compare: the same for A and B (and --robust's section
    reuses A when A is your settings as they are) -> (robust or None, robust_compare or None)."""
    n, end = params["robust"], params["to"]
    bmemo = {}

    def bench_cagr(st):
        if st not in bmemo:
            b = benchmark(SHARIAH_BENCH, dict(BENCHMARKS)[SHARIAH_BENCH], range_, st, end, capital, cfg, fetch=bench_get)
            bmemo[st] = b.get("cagr_pct") if b["status"] == "OK" else None
        return bmemo[st]

    main_dg = cache.digest(cfg)
    done = {}

    def side(name, label, c, rtext):
        reg = regimes.get(rtext) if rtext not in (None, "off") else None
        key = (cache.digest(c), rtext or "off")
        if key not in done:
            base = sim if key == (main_dg, main_regime or "off") else None
            done[key] = robust_section([(name, label, used, c, rtext or "off", reg, base)], params, uni, n, cache,
                                       bench_cagr, progress)[name]
        return done[key]

    out_cmp = None
    if robust_sides:
        a, b = [side(*x) for x in robust_sides]
        out_cmp = {"a": a, "b": b, "compare": compare_summary(paired(a["runs"], b["runs"])), "note": ROBUST_NOTE}
    out = None
    if not robust_sides or params.get("robust_given"):
        label = tc.settings_snapshot(cfg)["label"]
        out = dict(side("main", label, cfg, main_regime or "off"))     # a copy: it may be side A's runs, reused
        out["settings"] = dict(out["settings"], label=label)
        out["note"] = ROBUST_NOTE
    return out, out_cmp


def run_id(params, label, syms):
    """<to>_<mode>_<from>_<hash>; v0.2.8: a basket adds _sym<N> or _hold<N> before the hash. An "all" run's id is the
    one it always had (universe_mode "all" is left out of the hash)."""
    p = {k: v for k, v in params.items() if not (k == "universe_mode" and v == "all")}
    h = hashlib.sha1(json.dumps([p, label, syms], sort_keys=True).encode("utf-8")).hexdigest()[:6]
    um = params.get("universe_mode") or "all"
    tag = "" if um == "all" else "_%s%d" % ("hold" if um == "holdings" else "sym", len(syms))
    return "%s_%s_%s%s_%s" % (params["to"], params["mode"], params["from"], tag, h)


COMPARE_KEYS = ("trades", "win_rate_pct", "expectancy_r", "profit_factor", "pnl_rs", "total_return_pct", "cagr_pct",
                "max_drawdown_pct", "exposure_pct", "total_charges_rs")


def compare_view(metrics, split):
    o = metrics["overall"]
    v = {k: o.get(k) for k in COMPARE_KEYS}
    v["by_mode"] = {m: {k: g.get(k) for k in ("trades", "win_rate_pct", "expectancy_r", "too_few")}
                    for m, g in metrics["by_mode"].items()}
    v["out_of_sample_expectancy_r"] = split["out_of_sample"]["expectancy_r"]
    return v


def late_share(trades, late, excluded=False):
    """How much of the P&L came from stocks that joined late (listed during the window): always reported, because
    today's list holds only the listings that survived and did well enough to be on it."""
    syms = {x["symbol"] for x in late}
    lt = [t for t in trades if t["symbol"] in syms]
    tot = round(sum(t["pnl_rs"] for t in trades), 2)
    lp = round(sum(t["pnl_rs"] for t in lt), 2)
    pct = round(lp / tot * 100, 1) if tot > 0 else None
    if excluded:
        text = ("Late joiners: %s, contributing 0.0%% of total P&L (left out with --no-late)."
                % tc.plural(len(syms), "stock"))
    elif pct is None:
        text = ("Late joiners: %s, contributing UNKNOWN%% of total P&L (a share of a total that is not "
                "positive means nothing: theirs %s, total %s; %s)." % (tc.plural(len(syms), "stock"), tc.fmt_rs(lp, 0), tc.fmt_rs(tot, 0),
                                                                       tc.plural(len(lt), "trade")))
    else:
        text = ("Late joiners: %s, contributing %.1f%% of total P&L (%s of %s; %s)."
                % (tc.plural(len(syms), "stock"), pct, tc.fmt_rs(lp, 0), tc.fmt_rs(tot, 0), tc.plural(len(lt), "trade")))
    return {"stocks": len(syms), "trades": 0 if excluded else len(lt), "pnl_rs": 0.0 if excluded else lp,
            "total_pnl_rs": tot, "pct_of_total": 0.0 if excluded else pct, "excluded": excluded, "text": text}


def load_regime(params, cfg, range_, days, index_fn, extra=(), extra_days=()):
    """-> (index info, {variant: regime dict or None}) for --regime, --regime-compare and (v0.2.6) the regime of a
    --robust-compare side (`extra`), with the index fetched once. States are also worked out for `extra_days`
    (robust runs that start a day early); the counts and ranges stay those of the window's days."""
    wanted = {v for v in extra if v and v != "off"}
    if params.get("regime") and params["regime"] != "off":
        wanted.add(params["regime"])
    if params.get("regime_compare"):
        wanted |= set(REGIME_VARIANTS) - {"off"}
    if not wanted:
        return None, {}
    idx = (cfg.get("regime") or {}).get("index") or "^NSEI"
    info = {"index": idx, "name": tc.REGIME_INDEXES.get(idx, idx), "status": "OK", "reason": None}
    try:
        bars, _ = (index_fn or tc.get_daily_bars)(idx, range_=range_)
    except tc.FetchError as e:
        bars = []
        info.update(status="UNKNOWN", reason="could not be fetched: %s" % str(e)[:200])
    out, by_rule, all_days = {}, {}, sorted(set(days) | set(extra_days))
    for v in sorted(wanted):
        r = parse_regime(v)
        if r["rule"] not in by_rule:
            by_rule[r["rule"]] = regime_states(bars, all_days, r["rule"], idx)
        out[v] = dict(r, states=by_rule[r["rule"]])
    if extra_days:
        win = set(days)
        by_rule = {rule: {d: x for d, x in sts.items() if d in win} for rule, sts in by_rule.items()}
    if bars:
        st = by_rule[sorted(by_rule)[0]]
        info["risk_off_days"] = {rule: sum(1 for x in sts.values() if x["state"] == "risk-off") for rule, sts in by_rule.items()}
        info["risk_off_ranges"] = {rule: risk_off_ranges(sts) for rule, sts in by_rule.items()}
        info["unknown_days"] = sum(1 for x in st.values() if x["state"] == "UNKNOWN")
    return info, out


def _memo_fetch(fetch):
    """Benchmark prices fetched once per symbol and range (the robust runs ask for the ETF from several starts)."""
    memo = {}
    fn = fetch or tc.get_daily_bars

    def get(sym, range_="2y"):
        k = (sym, range_)
        if k not in memo:
            try:
                memo[k] = ("ok", fn(sym, range_=range_))
            except tc.FetchError as e:
                memo[k] = ("err", e)
        kind, v = memo[k]
        if kind == "err":
            raise v
        return v
    return get


def run(params, cfg, uni, data_fn=load_bars, bench_fn=None, progress=None, index_fn=None, robust_sides=None):
    """The whole backtest -> result dict (no file is written here). robust_sides (v0.2.6, --robust-compare): the
    two settings [(name, label, cfg, regime text)] from parse_settings."""
    all_syms, status_counts = halal_universe(uni)
    um = params.get("universe_mode") or "all"
    if um not in UNIVERSE_MODES:
        raise ValueError("universe_mode must be one of %s" % ", ".join(UNIVERSE_MODES))
    if um == "all":
        syms = all_syms
    else:                                  # v0.2.8: only the chosen stocks; checked again here (never a non-compliant one)
        syms = list(params.get("symbols") or [])
        bad = [e for e in (tc.symbol_refusal(s, uni) for s in syms) if e]
        if bad or not syms or len(syms) > tc.BT_MAX_SYMBOLS:
            raise ValueError("; ".join(bad) or "choose 1 to %d stocks" % tc.BT_MAX_SYMBOLS)
    start, end, split = params["from"], params["to"], params["split"]
    first = tc.parse_date(start) - dt.timedelta(days=365 * TM_YEARS + 10)
    range_ = yahoo_range(first, tc.today_ist())
    data, skipped, late = data_fn(syms, range_, start, end, progress=progress)
    no_late = not params.get("late", True)
    late_syms = {x["symbol"] for x in late}
    early = {s: b for s, b in data.items() if s not in late_syms}       # the same bars, late joiners left out
    capital = float(cfg["capital"])
    used = early if no_late else data
    all_days = sorted({b["date"] for bs in used.values() for b in bs if start <= b["date"] <= end})
    robust_n = params.get("robust")
    early_days = []
    if robust_n:
        dates = sorted({b["date"] for bs in used.values() for b in bs if b["date"] <= end})
        early_days = [shifted_start(dates, start, -1)]
    rinfo, regimes = load_regime(params, cfg, range_, all_days, index_fn or bench_fn,
                                 extra=[x[3] for x in robust_sides or []], extra_days=early_days)
    main_regime = params.get("regime") if params.get("regime") not in (None, "off") else None
    cache = RunCache() if robust_n else None
    sim = simulate(used, cfg, start, end, params["mode"], params["setups"],
                   params["max_positions"], progress, uni=uni, take_warn=params["take_warn"], rank="tm",
                   regime=regimes.get(main_regime) if main_regime else None, cache=cache)
    regime_cmp = None
    if params.get("regime_compare"):
        cols = []
        for v in REGIME_VARIANTS:
            if progress:
                progress("regime compare: %s" % v)
            if v == (main_regime or "off"):
                sv = sim
            else:
                sv = simulate(used, cfg, start, end, params["mode"], params["setups"], params["max_positions"],
                              progress, uni=uni, take_warn=params["take_warn"], rank="tm", regime=regimes.get(v))
            cols.append(regime_column(v, sv, capital, split))
        regime_cmp = {"index": rinfo, "columns": cols,
                      "note": "Each column is the same window, data, ranking, sizing and risk check; only the regime "
                              "rule changes which new plans are placed (or at what risk) on risk-off days, computed "
                              "from the index's bars up to that day. Information for deciding; the default stays off."}
    metrics, spl = all_metrics(sim, capital, split)
    compare = None
    if params.get("compare"):
        if progress:
            progress("compare (b): the same window ranked by setup score only")
        sim_b = simulate(early if no_late else data, cfg, start, end, params["mode"], params["setups"],
                         params["max_positions"], progress, uni=uni, take_warn=params["take_warn"], rank="score")
        mb, sb = all_metrics(sim_b, capital, split)
        compare = {"as_run": compare_view(metrics, spl), "score_only": compare_view(mb, sb), "no_late": None,
                   "note": "(a) as run: tayyib-daily's ranking with the time machine; (b) the same days, data, "
                           "sizing and risk check, picks ranked by setup score only: the difference is what the "
                           "time-machine ranking added (or cost); (c) as run without the stocks that joined late "
                           "(listed during the window): the difference is how much the result leans on recent "
                           "listings that survived to be on today's list."}
        if no_late:
            compare["no_late_note"] = "(c) is (a): this run already leaves late joiners out (--no-late)."
            compare["no_late"] = compare["as_run"]
        else:
            if progress:
                progress("compare (c): the same window without late joiners")
            sim_c = simulate(early, cfg, start, end, params["mode"], params["setups"], params["max_positions"],
                             progress, uni=uni, take_warn=params["take_warn"], rank="tm")
            mc, sc = all_metrics(sim_c, capital, split)
            compare["no_late"] = compare_view(mc, sc)
    bench_get = _memo_fetch(bench_fn)
    robust = robust_cmp = None
    if robust_n:
        robust, robust_cmp = robust_results(params, cfg, uni, used, sim, main_regime, regimes, robust_sides, cache,
                                            bench_get, range_, capital, progress)
    benches = {}
    for sym, name in BENCHMARKS:
        benches[sym] = benchmark(sym, name, range_, start, end, capital, cfg, fetch=bench_get)
    basket = stocks_tbl = None
    if um != "all":
        basket = basket_benchmark(syms, data, skipped, late, sim["days"], capital, cfg, no_late)
        stocks_tbl = stock_table(syms, sim["trades"], basket, uni)
    snap = tc.settings_snapshot(cfg)
    res = {
        "id": run_id(params, snap["hash"], syms),
        "version": tc.VERSION,
        "run_at": tc.now_ist().isoformat(timespec="seconds"),
        "params": dict(params, universe_mode=um),
        "settings": {"label": snap["label"], "hash": snap["hash"], "differs_from_default": snap["differs_from_default"],
                     "capital": capital, "risk_per_trade_pct": cfg["max_risk_per_trade_pct"],
                     "max_position_pct": cfg["max_position_pct"], "broker": cfg["broker"]},
        "window": {"from": start, "to": end, "split": split, "first_day": sim["days"][0] if sim["days"] else None,
                   "last_day": sim["days"][-1] if sim["days"] else None, "trading_days": len(sim["days"]),
                   "price_range": range_, "end_rule": params.get("end_rule")},
        "universe": {"list_updated": uni.get("updated"), "statuses": status_counts, "compliant": len(all_syms),
                     "tested": len(early) if no_late else len(data), "joined_late": len(late),
                     "late_excluded": no_late, "skipped": len(skipped), "mode": um},
        "skipped": skipped,
        "joined_late": late,
        "late_joiners": late_share(sim["trades"], late, excluded=no_late),
        "banners": [],
        "metrics": metrics,
        "split": spl,
        "benchmarks": benches,
        "counts": sim["counts"],
        "rules": [
            "Signals, liquidity, plans, ranking and the risk check on each day use that day's bars and earlier "
            "only; fills from the next session.",
            "A stock joins on the first day it has %d bars of history; stocks listed later join when they get "
            "there (joined_late[])%s." % (WARMUP_BARS, "; with --no-late they are left out" if no_late else ""),
            "The window ends on %s." % (params.get("end_rule") or "--to"),
            "Each day's stocks are picked and ranked like tayyib-daily (scanner top max(2 x daily.top, 25), one "
            "setup per stock, rank_key with the time machine on the stock's last 2 years; ties by symbol).",
            "Sized with tayyib-budget's rule on the configured capital, in rank order (each sized plan uses up "
            "cash for the next, as live); then tayyib-risk's check_order against held positions + waiting plans "
            "+ plans approved earlier that day: portfolio heat, max open positions, positions per industry, "
            "net reward:risk, loss at stop, max position %%, cash, halal status, plan expiry, the time-machine "
            "WARN. BLOCK is never placed; WARN %s." % ("is placed (--take-warn)" if params["take_warn"]
                                                       else "is not placed (--no-take-warn)"),
            "Not replayed (no history of them): news / HALAL-WATCH and the halal list's age.",
            "At most max_positions held or waiting; one per stock; no margin. A plan waits as a buy-stop until "
            "valid_until; it fills at max(open, entry) and then follows trade_outcome: a gap through the stop "
            "fills at the open, a day touching stop and target is the stop, swing breakeven at +1R, time stop "
            "at that day's close.",
            "Sale proceeds can pay for fills from the next trading day, not the same day; a gap up that needs "
            "more cash than is free cuts the quantity.",
            "Zerodha delivery charges (or your broker in config) on every buy and sell. Positions still open on "
            "the last day are valued at the last close after the sell charges (exit reason %s)." % EXIT_AT_END],
        "trades": sim["trades"],
        "equity_curve": sim["curve"],
        "disclaimer": tc.DISCLAIMER,
    }
    if um != "all":
        res["universe"].update(symbols=list(syms), chosen=len(syms))
        res["basket"] = basket
        res["stocks"] = stocks_tbl
        res["rules"].insert(0, "Universe: only the %s you chose (%s), each compliant on today's halal list; every "
                               "other rule is the same as for all halal stocks." % (
                                   tc.plural(len(syms), "stock"), ", ".join(syms)))
    if compare:
        res["compare"] = compare
    res["regime"] = {"variant": main_regime or "off", "index": rinfo}
    if regime_cmp:
        res["regime_compare"] = regime_cmp
    if robust:
        res["robust"] = robust
    if robust_cmp:
        res["robust_compare"] = robust_cmp
    res["banners"] = (basket_banners(len(used), metrics["overall"], basket) if um != "all" else []) +         banners(metrics["overall"], spl, benches)
    if rinfo and rinfo.get("status") != "OK":
        res["banners"].append(BANNER_REGIME_UNKNOWN)
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
            ("profit factor", "no losing trades" if m.get("profit_factor_note") else fmt(m["profit_factor"])),
            ("P&L", fmt(m["pnl_rs"], "Rs")),
            ("total return", fmt(m.get("total_return_pct"), "%")), ("CAGR", fmt(m.get("cagr_pct"), "%")),
            ("max drawdown", dd), ("longest losing streak", str(m["longest_losing_streak"])),
            ("exposure", fmt(m.get("exposure_pct"), "%", 1)), ("charges", fmt(m["total_charges_rs"], "Rs"))]


def table(cols):
    """cols: [(title, metrics)] -> markdown table with one column per title ("(too few to judge)" when the
    group has under MIN_TRADES trades)."""
    names = [r[0] for r in metrics_rows(cols[0][1])]
    vals = [dict(metrics_rows(m)) for _, m in cols]
    heads = [t + (" " + TOO_FEW if m.get("too_few") else "") for t, m in cols]
    L = ["| | " + " | ".join(heads) + " |", "|---" * (len(cols) + 1) + "|"]
    for n in names:
        L.append("| %s | %s |" % (n, " | ".join(v[n] for v in vals)))
    return L


def counts_md(c):
    L = ["Plans placed %d; never triggered %d; no free slot %d; not sized %d; no cash at the fill %d; quantity "
         "cut at the fill %d." % (c["plans"], c["not_triggered"], c["no_slot"], c["not_sized"], c["no_cash_at_fill"],
                                  c["qty_cut_at_fill"]),
         "", "Risk check (tayyib-risk, replayed): %d plans checked, %d blocked, WARN placed %d, WARN skipped %d."
         % (c["risk_checked"], c["risk_blocked_plans"], c["warn_taken"], c["warn_skipped"])]
    if c["risk_blocked"]:
        L += ["", "| blocked by | plans |", "|---|---|"] + \
             ["| %s | %d |" % (k, v) for k, v in sorted(c["risk_blocked"].items(), key=lambda kv: (-kv[1], kv[0]))]
    if c["risk_warned"]:
        L += ["", "| warned by | plans |", "|---|---|"] + \
             ["| %s | %d |" % (k, v) for k, v in sorted(c["risk_warned"].items(), key=lambda kv: (-kv[1], kv[0]))]
    L += ["", "Not replayed (skipped on every checked plan): " +
          ", ".join("%s %d" % kv for kv in c["not_replayed"].items()) + "."]
    return L


def compare_md(cp):
    a, b, c = cp["as_run"], cp["score_only"], cp.get("no_late")
    cols = [a, b] + ([c] if c else [])
    rows = (("trades", "trades", ""), ("win rate", "win_rate_pct", "%"), ("expectancy", "expectancy_r", "R"),
            ("profit factor", "profit_factor", ""), ("P&L", "pnl_rs", "Rs"), ("total return", "total_return_pct", "%"),
            ("CAGR", "cagr_pct", "%"), ("max drawdown", "max_drawdown_pct", "%"), ("exposure", "exposure_pct", "%"),
            ("out-of-sample expectancy", "out_of_sample_expectancy_r", "R"))
    heads = ["(a) as run", "(b) score only"] + (["(c) as run without late joiners"] if c else [])
    L = ["## Compare: (a) as run, (b) score only, (c) without late joiners", "", cp["note"], ""]
    if cp.get("no_late_note"):
        L += [cp["no_late_note"], ""]
    L += ["| | " + " | ".join(heads) + " |", "|---" * (len(heads) + 1) + "|"]
    for name, k, u in rows:
        L.append("| %s | %s |" % (name, " | ".join(str(x[k]) if k == "trades" else fmt(x[k], u) for x in cols)))
    for m in sorted(set().union(*[x["by_mode"] for x in cols])):
        cells = []
        for x in cols:
            g = x["by_mode"].get(m) or {}
            cells.append("%s / %s%s" % (g.get("trades", 0), fmt(g.get("expectancy_r"), "R"),
                                        " " + TOO_FEW if g.get("too_few") else ""))
        L.append("| %s: trades / expectancy | %s |" % (m, " | ".join(cells)))
    return L + [""]


def regime_md(rc):
    cols = rc["columns"]
    yr = lambda w: "UNKNOWN" if not w else "%d: %s%s" % (w["year"], fmt(w["return_pct"], "%"), " (part)" if w["partial"] else "")
    rows = (("trades", lambda c: str(c["trades"]) + (" " + TOO_FEW if c["too_few"] else "")),
            ("win rate", lambda c: fmt(c["win_rate_pct"], "%", 1)), ("expectancy", lambda c: fmt(c["expectancy_r"], "R")),
            ("CAGR", lambda c: fmt(c["cagr_pct"], "%")), ("max drawdown", lambda c: fmt(c["max_drawdown_pct"], "%")),
            ("worst year", lambda c: yr(c["worst_year"])),
            ("swing: trades / expectancy", lambda c: "%d / %s" % (c["swing_trades"], fmt(c["swing_expectancy_r"], "R"))),
            ("pullback: trades / expectancy", lambda c: "%d / %s" % (c["pullback_trades"], fmt(c["pullback_expectancy_r"], "R"))),
            ("risk-off days", lambda c: str(c["risk_off_days"])), ("plans held back", lambda c: str(c["picks_held_back"])))
    ix = rc.get("index") or {}
    L = ["## Market regime compare", "", rc["note"], "",
         "Index: %s (%s)%s." % (ix.get("name"), ix.get("index"), "" if ix.get("status") == "OK" else ": UNKNOWN, " + str(ix.get("reason"))), "",
         "| | " + " | ".join(c["variant"] for c in cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for name, f in rows:
        L.append("| %s | %s |" % (name, " | ".join(f(c) for c in cols)))
    return L + [""] + ranges_md(ix)


def ranges_md(ix):
    """The risk-off date ranges per rule (v0.2.5), to check against a chart of the index."""
    L = []
    for rule, rs in sorted(((ix or {}).get("risk_off_ranges") or {}).items()):
        L += ["### Risk-off date ranges: %s (%s)" % (rule, ix.get("name")), "",
              "%d range%s, %d trading days." % (len(rs), "" if len(rs) == 1 else "s", sum(r["days"] for r in rs)), ""]
        if rs:
            L += ["| start | end | days |", "|---|---|---|"] + ["| %s | %s | %d |" % (r["start"], r["end"], r["days"])
                                                              for r in rs]
        L.append("")
    return L


def render_md(r):
    w, u, s = r["window"], r["universe"], r["settings"]
    L = ["**%s**" % b for b in r["banners"]] + ["", "# Backtest %s" % r["id"], "",
         "%s mode%s, %s to %s (%d trading days), split %s. Capital %s, risk %s%% a trade, max %d positions, "
         "settings %s, broker %s, WARN plans %s." % (
             r["params"]["mode"], " (%s)" % ", ".join(r["params"]["setups"]) if r["params"]["setups"] else "",
             w["first_day"], w["last_day"], w["trading_days"], w["split"], tc.fmt_rs(s["capital"], 0),
             tc._fmt_val(s["risk_per_trade_pct"]), r["params"]["max_positions"], s["label"], s["broker"],
             "taken" if r["params"].get("take_warn", True) else "not taken"),
         universe_md(r), "",
         "## Overall", ""]
    L += table([("strategy", r["metrics"]["overall"])]) + [""]
    if r["metrics"]["by_setup"]:
        L += ["## By setup", ""] + table(list(r["metrics"]["by_setup"].items())) + [""]
    if r["metrics"]["by_mode"]:
        L += ["## By mode", ""] + table(list(r["metrics"]["by_mode"].items())) + [""]
    L += ["Setup and mode columns: return, CAGR and drawdown are on the capital plus those trades' realised "
          "P&L. A column marked %s has under %d trades: its numbers are noise." % (TOO_FEW, MIN_TRADES), "",
          "## In-sample vs out-of-sample (split %s, by signal date)" % w["split"], ""]
    L += table([("in-sample", r["split"]["in_sample"]), ("out-of-sample", r["split"]["out_of_sample"])]) + [""]
    L += ["## Benchmarks (buy and hold, one buy and one sell charge)", "",
          "| | total return | CAGR | max drawdown | note |", "|---|---|---|---|---|",
          "| strategy | %s | %s | %s | |" % (fmt(r["metrics"]["overall"]["total_return_pct"], "%"),
                                           fmt(r["metrics"]["overall"]["cagr_pct"], "%"),
                                           fmt(r["metrics"]["overall"]["max_drawdown_pct"], "%"))]
    bk = r.get("basket")
    if bk:
        if bk["status"] != "OK":
            L.append("| %s | UNKNOWN | UNKNOWN | UNKNOWN | %s |" % (bk["name"], bk.get("reason")))
        else:
            L.append("| %s (%d stocks) | %s | %s | %s | %s to %s; %s each; charges %s |" % (
                bk["name"], bk["in_basket"], fmt(bk["total_return_pct"], "%"), fmt(bk["cagr_pct"], "%"),
                fmt(bk["max_drawdown_pct"], "%"), bk["start"], bk["end"], tc.fmt_rs(bk["share_rs"], 0),
                tc.fmt_rs(bk["charges_rs"], 0)))
    for b in r["benchmarks"].values():
        if b["status"] != "OK":
            L.append("| %s (%s) | UNKNOWN | UNKNOWN | UNKNOWN | %s |" % (b["name"], b["symbol"], b["reason"]))
        else:
            L.append("| %s (%s) | %s | %s | %s | %s to %s%s |" % (
                b["name"], b["symbol"], fmt(b["total_return_pct"], "%"), fmt(b["cagr_pct"], "%"),
                fmt(b["max_drawdown_pct"], "%"), b["start"], b["end"], "; " + b["note"] if b.get("note") else ""))
    L += ["", "The Nifty 50 is not halal-screened: it is there for reference only, not as a halal option.", ""]
    if bk:
        L += ["%s" % bk["note"], ""]
    if r.get("stocks"):
        L += stocks_md(r["stocks"])
    if r.get("compare"):
        L += compare_md(r["compare"])
    if r.get("regime_compare"):
        L += regime_md(r["regime_compare"])
    if r.get("robust"):
        L += robust_md(r["robust"])
    if r.get("robust_compare"):
        L += robust_compare_md(r["robust_compare"])
    if (r.get("regime") or {}).get("variant", "off") != "off":
        L += ["Regime filter in this run: %s (index %s)." % (r["regime"]["variant"], (r["regime"].get("index") or {}).get("name")), ""]
        if not r.get("regime_compare"):
            L += ranges_md(r["regime"].get("index"))
    if w.get("end_rule"):
        L += ["Window end: %s." % w["end_rule"], ""]
    L += ["## What happened to the plans", ""] + counts_md(r["counts"]) + [""]
    if r.get("late_joiners"):
        L += ["## Late joiners", "", r["late_joiners"]["text"], ""]
    if r.get("joined_late"):
        L += ["## Joined late (listed recently)", ""] + \
             ["- %s: joined %s (data starts %s)" % (x["symbol"], x["join_date"], x["data_starts"])
              for x in r["joined_late"]] + [""]
    if r["skipped"]:
        L += ["## Skipped stocks", ""] + ["- %s: %s" % (x["symbol"], x["reason"]) for x in r["skipped"]] + [""]
    L += ["## Rules", ""] + ["- " + x for x in r["rules"]] + ["", "## Trades", "",
          "| signal | stock | setup | check | entry | price | exit | price | reason | qty | charges | P&L | R |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in r["trades"]:
        L.append("| %s | %s | %s %s | %s | %s | %.2f | %s | %.2f | %s | %d | %.2f | %.2f | %+.2f |" % (
            t["signal_date"], t["symbol"], t["mode"], t["setup"], t.get("risk", "-"), t["entry_date"], t["entry_price"],
            t["exit_date"], t["exit_price"], t["exit_reason"], t["qty"], t["charges"], t["pnl_rs"], t["r"]))
    L += ["", r["disclaimer"]]
    return "\n".join(L) + "\n"


def universe_md(r):
    u = r["universe"]
    if (u.get("mode") or "all") == "all":
        return ("Universe: %d compliant stocks on today's halal list (built %s): %d tested (%d of them joined late), %d "
                "skipped." % (u["compliant"], u["list_updated"], u["tested"], u.get("joined_late", 0), u["skipped"]))
    return ("Universe: %s (%s), each compliant on today's halal list (built %s): %d tested (%d of them joined late), "
            "%d skipped." % (universe_label(r), "the stocks you hold" if u["mode"] == "holdings" else "your choice",
                             u["list_updated"], u["tested"], u.get("joined_late", 0), u["skipped"]))


def stocks_md(st):
    L = ["## Your stocks: strategy vs holding", "", st["note"], "",
         "| stock | trades | wins | win rate | total R | P&L | strategy on its slice | holding it | strategy vs holding |",
         "|---|---|---|---|---|---|---|---|---|"]
    for x in st["rows"]:
        hold = fmt(x["hold_return_pct"], "%") if x["hold_status"] == "OK" else "UNKNOWN (%s)" % x.get("hold_note")
        L.append("| %s | %d%s | %d | %s | %s | %s | %s | %s | %s |" % (
            x["symbol"], x["trades"], " " + TOO_FEW if x["too_few"] and x["trades"] else "", x["wins"],
            fmt(x["win_rate_pct"], "%", 1) if x["trades"] else "-", fmt(x["total_r"], "R") if x["trades"] else "-",
            fmt(x["pnl_rs"], "Rs"), fmt(x["strategy_return_pct"], "%") if x["trades"] else "-", hold, x["vs"]))
    t = st["totals"]
    L += ["| total | %d | %d | | %s | %s | | | |" % (t["trades"], t["wins"], fmt(t["total_r"], "R"), fmt(t["pnl_rs"], "Rs")),
          ""]
    return L


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
            "mode": res["params"]["mode"], "universe": universe_label(res), "settings": res["settings"]["label"],
            "trades": m["trades"],
            "total_return_pct": m["total_return_pct"], "cagr_pct": m["cagr_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"], "banners": len(res["banners"]),
            "version": res.get("version")}


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
    r.add_argument("--max-positions", type=int, default=None,
                   help="default: max_open_positions in your settings (6 unless you changed it; v0.2.7)")
    r.add_argument("--split", help="in-sample / out-of-sample date (default: the start of the last third)")
    r.add_argument("--take-warn", dest="take_warn", action="store_true", default=True,
                   help="place plans the risk check WARNs about, as you can live (default)")
    r.add_argument("--no-take-warn", dest="take_warn", action="store_false", help="place PASS plans only")
    r.add_argument("--no-late", dest="late", action="store_false", default=True,
                   help="leave out stocks that joined late (listed during the window)")
    r.add_argument("--compare", action="store_true",
                   help="also run (b) ranked by setup score only and (c) without late joiners, side by side")
    r.add_argument("--regime", default="off", help="market regime filter for this run: off (default) or RULE:ACTION, "
                   "e.g. close_below_200dma:no_new_swing (rules %s; actions %s)" % (", ".join(tc.REGIME_RULES),
                                                                                  ", ".join(tc.REGIME_ACTIONS)))
    r.add_argument("--regime-compare", action="store_true",
                   help="also run %s on the same bars, side by side" % ", ".join(REGIME_VARIANTS))
    r.add_argument("--robust", type=int, nargs="?", const=ROBUST_DEFAULT, default=None, metavar="N",
                   help="also run the same window N times (default %d, at most %d) on the same prices, each seed changing "
                        "only the order of equal-ranked signals and the start by one trading day, plus max positions "
                        "3 / 5 / 8: the spread of the results" % (ROBUST_DEFAULT, ROBUST_MAX))
    r.add_argument("--robust-compare", nargs=2, metavar=("A", "B"),
                   help="the --robust runs for settings A and settings B on the same prices and seeds, paired seed by "
                        "seed, with a verdict. Each is 'default' or KEY=VALUE pairs over your config, e.g. "
                        "\"pullback=on\" \"pullback=off\", or \"regime=off\" \"regime=close_below_200dma:half_risk\"")
    r.add_argument("--symbols", default=None, metavar="SYM1,SYM2,...",
                   help="My stocks (v0.2.8): test only these 1 to %d stocks, each compliant on today's halal list, "
                        "against buying and holding them" % tc.BT_MAX_SYMBOLS)
    r.add_argument("--holdings", action="store_true",
                   help="test only the stocks you hold (positions.json: open trades and imported holdings)")
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
            print("%s  %s to %s  %s  %s  %s  %d trades  return %s  CAGR %s  max drawdown %s  (v%s)"
                  % (x["id"], x["from"], x["to"], x["mode"], x["universe"], x["settings"], x["trades"],
                     fmt(x["total_return_pct"], "%"), fmt(x["cagr_pct"], "%"), fmt(x["max_drawdown_pct"], "%"),
                     x.get("version") or "?"))
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

    if a.symbols is not None and a.holdings:
        tc.die("--symbols and --holdings can't be combined: choose one")
    cfg = tc.load_config()
    tc.report_config(cfg)
    if a.capital is not None:
        if a.capital <= 0:
            tc.die("--capital must be positive")
        cfg["capital"] = a.capital
    mp_from = "--max-positions" if a.max_positions is not None else "config max_open_positions"
    if a.max_positions is None:                           # v0.2.7: the user's own setting, not a fixed 5
        a.max_positions = cfg["max_open_positions"]
    if a.max_positions < 1:
        tc.die("--max-positions must be at least 1")
    setups = None
    if a.setups:
        setups = [x.strip() for x in a.setups.split(",") if x.strip()]
        bad = [x for x in setups if x not in tc.SWING_SETUPS + tc.DELIVERY_SETUPS]
        if bad:
            tc.die("unknown setup %s (choose from %s)" % (", ".join(bad), ", ".join(tc.SWING_SETUPS + tc.DELIVERY_SETUPS)))
    try:
        parse_regime(a.regime)
    except ValueError as e:
        tc.die(str(e))
    robust_n = a.robust if a.robust is not None else (ROBUST_DEFAULT if a.robust_compare else None)
    if robust_n is not None and not 1 <= robust_n <= ROBUST_MAX:
        tc.die("--robust N must be 1 to %d (got %d)" % (ROBUST_MAX, robust_n))
    sides = None
    if a.robust_compare:
        raw = tc.read_json("config.json", None) or {}
        sides = []
        for name, text in zip(("a", "b"), a.robust_compare):
            try:
                label, c, rtext = parse_settings(text, raw)
            except ValueError as e:
                tc.die("--robust-compare %s (%r): %s" % (name.upper(), text, e))
            if a.capital is not None:
                c["capital"] = a.capital
            sides.append((name, label, c, rtext))
    start, end, split, end_rule = window(a, tc.now_ist(), cfg)
    uni = tc.load_universe()
    if not uni.get("stocks"):
        tc.die("no halal universe yet: run tayyib-halal/halal.py build first")
    um, chosen = "all", None                       # v0.2.8: checked before anything is downloaded
    if a.symbols is not None:
        chosen, errs = tc.check_backtest_symbols(a.symbols, uni)
        if errs:
            tc.die("--symbols refused: " + "; ".join(errs))
        um = "symbols"
    elif a.holdings:
        chosen, errs = tc.check_holdings(tc.read_json("positions.json", {}) or {}, uni)
        if errs:
            tc.die("--holdings refused: " + "; ".join(errs))
        um = "holdings"
    params = {"mode": a.mode, "setups": setups, "from": start, "to": end, "split": split,
              "max_positions": a.max_positions, "max_positions_from": mp_from, "top": cfg["daily"]["top"], "warmup_bars": WARMUP_BARS,
              "tm_runs": TM_RUNS, "tm_seed": TM_SEED, "take_warn": a.take_warn, "compare": a.compare,
              "late": a.late, "end_rule": end_rule, "universe_mode": um}
    if chosen is not None:
        params["symbols"] = chosen
    if a.regime != "off" or a.regime_compare:              # v0.2.4 (left out when off, so earlier ids stay the same)
        params.update(regime=a.regime, regime_compare=a.regime_compare)
    if robust_n is not None:                                # v0.2.6 (left out when not used: earlier ids unchanged)
        params.update(robust=robust_n, robust_given=a.robust is not None)
        if sides:
            params["robust_compare"] = [x[1] for x in sides]
    t0 = time.time()
    progress = None if a.json else (lambda m: sys.stderr.write("  %s\n" % m))
    res = run(params, cfg, uni, progress=progress, robust_sides=sides)
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
