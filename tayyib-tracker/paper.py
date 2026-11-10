"""tayyib-tracker paper account and the shareable report (v0.2.9).

The paper account copies what you would do with real money: only PASS picks, from lists dated on or after
paper.start, in each list's own order, one position per symbol, at most max_open_positions open or waiting at
once, cash never below zero (it starts at the capital; sale proceeds pay for buys from the next day), the
quantity the list sized. A PASS pick that can't be taken is SKIPPED with the reason. Fills, stops, targets,
time exits and charges are the tracker's own (tracker.follow -> tc.trade_outcome), so a pick's result is the
same in both. Measurement only: nothing here changes a pick, and nothing is bought.

Writes trader/paper_account.json and (report) trader/reports/DATE.md and DATE.json.
"""
import datetime as dt
import os
import re

import tayyib_core as tc
import tracker as T

PAPER_FILE = "paper_account.json"
REPORTS_DIR = "reports"
BENCH_SYM, BENCH_NAME = "SHARIABEES.NS", "Nippon India ETF Shariah BeES"
BENCH_RANGE = "2y"
BANNER_PAPER = "Paper only: nothing was bought."
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(json|md)$")
MAX_TABLE = 20                     # rows per report table; the rest are in the .json
RULES = ("Only PASS picks, from lists dated on or after the start date, in each list's own order.",
         "One position per stock; at most max_open_positions open or waiting to buy at once.",
         "Cash starts at the capital and never goes below zero; sale proceeds pay for buys from the next day.",
         "Quantity as sized in the list. Fills, stops, targets, time exits and charges are the tracker's own; a day "
         "that touches both the stop and the target counts as the stop.",
         "Open positions are valued at the last close, after the sell charges.")

# skip reasons (the text starts with a stable word, so counts can group them)
HELD, WAITING, SLOTS, CASH, CASH_AT_FILL, NO_QTY, NO_PRICES = (
    "already held", "already waiting to buy", "slots full", "not enough cash", "not enough cash at the fill price",
    "no quantity in the list", "UNKNOWN: no prices")


def early_banner(n):
    return "Too early to judge: %s (need %d+)." % (tc.plural(n, "closed trade"), tc.MIN_TRADES)


# --- inputs ----------------------------------------------------------------------------------------

def load_lists(start, today):
    """The saved daily lists dated start..today, oldest first."""
    d = tc.path("daily")
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        m = DATE_RE.match(fn)
        if m and m.group(2) == "json" and start <= m.group(1) <= today:
            doc = tc.read_json(os.path.join("daily", fn))
            if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
                doc.setdefault("date", m.group(1))
                out.append(doc)
    return out


def pass_rows(doc):
    """A list's PASS rows in the list's own order, as tracker rows (rows with no levels are left out)."""
    h = (doc.get("settings") or {}).get("hash") or T.PRE
    rows = []
    for r in doc.get("rows", []):
        if r.get("risk") == "PASS":
            row = T.list_row(doc, r, h)
            if row is not None:
                rows.append(row)
    return rows


def fetch_bars(symbols, get=None):
    """symbol -> daily bars (None when the fetch failed), and symbol -> the error text."""
    get = get or tc.get_daily_bars
    bars, errors = {}, {}
    for s in sorted(set(symbols)):
        try:
            bars[s] = get(s)[0]
        except tc.FetchError as e:
            bars[s] = None
            errors[s] = str(e)[:160]
    return bars, errors


# --- the account -----------------------------------------------------------------------------------

def _buy_cost(qty, price, cfg):
    return qty * price + tc.order_charges("BUY", price, qty, cfg)["total"]


def _close_on(bars, d):
    """The last close on or before d (None before the first bar)."""
    px = None
    for b in bars or ():
        if b["date"] > d:
            break
        px = b["close"]
    return px


def simulate(cfg, lists, bars_by, today, fetch_errors=None):
    """-> (positions, skipped, ledger). Day by day over every list date, fill date and exit date: fills first
    (paid from cash settled before that day), then exits (their proceeds settle the next day), then that day's
    list (decided after the close)."""
    capital = float(cfg["capital"])
    max_open = int(cfg["max_open_positions"])
    fetch_errors = fetch_errors or {}
    cands = []                                         # (list date, k, row, outcome or None)
    for doc in lists:
        for k, row in enumerate(pass_rows(doc)):
            bars = bars_by.get(row["symbol"])
            cands.append((doc["date"], k, row, T.follow(row, bars, cfg, today) if bars else None))
    days = sorted({c[0] for c in cands} | {o[f] for c in cands if c[3] for o in [c[3]]
                                           for f in ("filled", "exited") if o.get(f)})
    positions, skipped, ledger = [], [], []           # ledger: (date, amount, kind) cash moves

    def settled(before=None):
        """capital + every buy paid + the proceeds of sales before `before` (all sales so far when None)."""
        return capital + sum(a for d, a, kind in ledger if kind == "buy" or before is None or d < before)

    def skip(c, why, when=None):
        d, k, row, out = c
        skipped.append({"list_date": d, "order": k + 1, "symbol": row["symbol"], "mode": row["mode"],
                        "setup": row["setup"], "entry": row["entry"], "qty": row.get("qty"),
                        "reason": why, "on": when or d})

    for day in days:
        for p in positions:                            # 1. buys that fill today, in the order they were taken
            if p["state"] == "waiting" and p["filled"] == day:
                cost = round(_buy_cost(p["qty"], p["fill"], cfg), 2)
                cash = settled(before=day)
                if cost > cash + 1e-9:
                    p["state"] = "skipped"
                    skip(p["_c"], "%s: needs %s, cash %s" % (CASH_AT_FILL, tc.fmt_rs(cost), tc.fmt_rs(cash)), day)
                    continue
                ledger.append((day, -cost, "buy"))
                p.update(state="open", cost_rs=cost)
        for p in positions:                            # 2. exits today: proceeds usable from tomorrow
            if p["state"] == "open" and p.get("exited") == day:
                proceeds = round(p["cost_rs"] + p["pnl_rs"], 2)
                ledger.append((day, proceeds, "sale"))
                p.update(state="closed", proceeds_rs=proceeds)
        for p in positions:                            # buy-stops that expired unfilled free their slot
            if p["state"] == "waiting" and not p["filled"] and p["status"] == "NOT TRIGGERED" \
                    and (p.get("valid_until") or p["list_date"]) <= day:
                p["state"] = "not_triggered"
        for c in [c for c in cands if c[0] == day]:    # 3. today's list, after the close, in its own order
            d, k, row, out = c
            sym = row["symbol"]
            live = [p for p in positions if p["state"] in ("open", "waiting")]
            mine = [p for p in live if p["symbol"] == sym]
            if mine:
                held = mine[0]["state"] == "open"
                skip(c, "%s (list %s)" % (HELD if held else WAITING, mine[0]["list_date"]))
                continue
            if out is None:
                skip(c, "%s (%s)" % (NO_PRICES, fetch_errors.get(sym, "could not be fetched")))
                continue
            qty = int(row.get("qty") or 0)
            if qty <= 0:
                skip(c, NO_QTY)
                continue
            if len(live) >= max_open:
                skip(c, "%s: %d of %d open or waiting to buy" % (SLOTS, len(live), max_open))
                continue
            need = round(_buy_cost(qty, float(row["entry"]), cfg), 2)
            reserved = sum(p["reserved_rs"] for p in live if p["state"] == "waiting")
            free = settled() - reserved
            if need > free + 1e-9:
                skip(c, "%s: needs %s, free %s" % (CASH, tc.fmt_rs(need), tc.fmt_rs(free)))
                continue
            p = dict(row, list_date=d, order=k + 1, qty=qty, reserved_rs=need, state="waiting", _c=c)
            p.update(out)
            positions.append(p)
    for p in positions:                                # end of data: expired orders and the ones still waiting
        if p["state"] == "waiting" and not (p["filled"] and p["filled"] <= today) and p["status"] == "NOT TRIGGERED":
            p["state"] = "not_triggered"
        p.pop("_c", None)
    return [p for p in positions if p["state"] != "skipped"], skipped, ledger


def curve(cfg, positions, ledger, bars_by, start, today, extra_days=()):
    """A point per trading day from the start: cash (incl. proceeds not yet settled) + the open positions at that
    day's close after the sell charges."""
    capital = float(cfg["capital"])
    held = [p for p in positions if p["state"] in ("open", "closed")]
    days = {b["date"] for p in held for b in (bars_by.get(p["symbol"]) or ()) if start <= b["date"] <= today}
    days |= {d for d in extra_days if start <= d <= today}
    days |= {d for d, _, _ in ledger}
    out = []
    for d in sorted(days):
        cash = capital + sum(a for x, a, _ in ledger if x <= d)
        value, n = 0.0, 0
        for p in held:
            if p["filled"] <= d and not (p.get("exited") and p["exited"] <= d):
                px = _close_on(bars_by.get(p["symbol"]), d)
                if px is None:
                    px = p["fill"]
                value += p["qty"] * px - tc.order_charges("SELL", px, p["qty"], cfg)["total"]
                n += 1
        out.append({"date": d, "cash": round(cash, 2), "positions_value": round(value, 2),
                    "equity": round(cash + value, 2), "open_positions": n})
    return out


def _trade(p, cfg):
    return {"symbol": p["symbol"], "r": p["r"], "pnl_rs": p["pnl_rs"], "exit_date": p["exited"],
            "charges": tc.round_trip(p["fill"], p["exit"], p["qty"], cfg)}


def stats(trades):
    m = tc.trade_stats(trades)
    m["too_few"] = m["trades"] < tc.MIN_TRADES
    return m


def view(cfg, acct, frm, to):
    """The account between two dates: equity, return, closed trades and their stats, drawdown and streak, from
    the equity at the close before `frm` (the capital before the first day)."""
    capital = float(cfg["capital"])
    pts = [c for c in acct["equity_curve"] if c["date"] <= to]
    before = [c for c in pts if c["date"] < frm]
    base = before[-1]["equity"] if before else capital
    inside = [(c["date"], c["equity"], c["open_positions"] > 0) for c in pts if c["date"] >= frm]
    series = [(frm, base, False)] + inside
    cs = tc.curve_stats(series)
    closed = [p for p in acct["positions"] if p["state"] == "closed" and frm <= p["exited"] <= to]
    m = stats([_trade(p, cfg) for p in closed])
    return {"from": frm, "to": to, "start_equity": round(base, 2), "equity": cs["end_equity"],
            "return_pct": cs["total_return_pct"], "pnl_change_rs": round(cs["end_equity"] - base, 2),
            "closed_trades": m["trades"], "win_rate_pct": m["win_rate_pct"], "avg_r": m["avg_r"],
            "pnl_rs": m["pnl_rs"], "max_drawdown_pct": cs["max_drawdown_pct"], "drawdown_peak": cs["drawdown_peak"],
            "drawdown_trough": cs["drawdown_trough"], "longest_losing_streak": m["longest_losing_streak"],
            "too_few": m["too_few"]}


def benchmark(cfg, frm, to, fetch=None):
    b = tc.buy_hold_benchmark(BENCH_SYM, BENCH_NAME, BENCH_RANGE, frm, to, float(cfg["capital"]), cfg, fetch=fetch)
    b.pop("curve", None)
    return b


def memo(fetch=None):
    """One fetch per symbol per run (the benchmark is asked for twice: since the start and the period)."""
    got, fn = {}, fetch or tc.get_daily_bars

    def f(sym, range_=BENCH_RANGE):
        if (sym, range_) not in got:
            try:
                got[(sym, range_)] = ("ok", fn(sym, range_=range_))
            except tc.FetchError as e:
                got[(sym, range_)] = ("err", e)
        kind, v = got[(sym, range_)]
        if kind == "err":
            raise v
        return v
    return f


def build(cfg, today=None, lists=None, bars_by=None, fetch_errors=None, bench_fetch=None):
    """The whole paper account -> the paper_account.json document (not written)."""
    today = today or tc.today_ist().isoformat()
    start = cfg["paper"]["start"]
    lists = load_lists(start, today) if lists is None else [x for x in lists if start <= x["date"] <= today]
    if bars_by is None:
        bars_by, fetch_errors = fetch_bars({r["symbol"] for d in lists for r in pass_rows(d)})
    positions, skipped, ledger = simulate(cfg, lists, bars_by, today, fetch_errors)
    bf = memo(bench_fetch)
    bench = benchmark(cfg, start, today, bf)
    try:
        bdays = [b["date"] for b in bf(BENCH_SYM, range_=BENCH_RANGE)[0]]
    except tc.FetchError:
        bdays = []
    eq = curve(cfg, positions, ledger, bars_by, start, today, extra_days=bdays + [d["date"] for d in lists])
    capital = float(cfg["capital"])
    for p in positions:
        p["result"] = {"closed": p["status"], "open": "OPEN", "waiting": "WAITING TO BUY",
                       "not_triggered": "NOT TRIGGERED"}[p["state"]]
    acct = {"positions": positions, "equity_curve": eq}
    allv = view(cfg, acct, start, today)
    opened = [p for p in positions if p["state"] == "open"]
    closed = [p for p in positions if p["state"] == "closed"]
    trades = [_trade(p, cfg) for p in closed]
    ts = stats(trades)
    cash_now = round(capital + sum(a for _, a, _ in ledger), 2)
    open_risk = sum(max(0.0, p["qty"] * (p["fill"] - p["stop"]) + tc.round_trip(p["fill"], p["stop"], p["qty"], cfg))
                    for p in opened)
    totals = {"capital": capital, "equity": eq[-1]["equity"] if eq else capital, "cash": cash_now,
              "total_return_pct": allv["return_pct"] if eq else 0.0, "closed_trades": ts["trades"],
              "open_positions": len(opened), "waiting_to_buy": sum(p["state"] == "waiting" for p in positions),
              "skipped": len(skipped), "win_rate_pct": ts["win_rate_pct"], "avg_r": ts["avg_r"],
              "total_pnl_rs": ts["pnl_rs"], "total_charges_rs": ts["total_charges_rs"],
              "unrealised_pnl_rs": round(sum(p["pnl_rs"] or 0 for p in opened), 2) if opened else None,
              "max_drawdown_pct": allv["max_drawdown_pct"], "drawdown_peak": allv["drawdown_peak"],
              "drawdown_trough": allv["drawdown_trough"], "longest_losing_streak": ts["longest_losing_streak"],
              "open_risk_rs": round(open_risk, 2),
              "open_risk_note": "loss if every open position hit its planned stop now, after charges (a swing stop "
                                "already moved to breakeven would lose less)",
              "too_few": ts["too_few"]}
    groups = {}
    for key in ("mode", "setup"):
        groups["by_" + key] = {g: stats([_trade(p, cfg) for p in closed if p[key] == g])
                               for g in sorted({p[key] for p in closed})}
    banners = [BANNER_PAPER]
    if ts["too_few"]:
        banners.append(early_banner(ts["trades"]))
    if fetch_errors:
        banners.append("Prices could not be fetched for %s: their PASS picks are SKIPPED as UNKNOWN, so the account "
                       "is incomplete." % ", ".join(sorted(fetch_errors)))
    return {"asof": tc.now_ist().isoformat(timespec="minutes"), "start": start, "today": today,
            "capital": capital, "max_open_positions": int(cfg["max_open_positions"]), "broker": cfg.get("broker"),
            "lists": [d["date"] for d in lists], "rules": list(RULES), "banners": banners, "totals": totals,
            "groups": groups, "benchmark": bench, "positions": positions, "skipped": skipped,
            "equity_curve": eq, "errors": fetch_errors or {}, "disclaimer": tc.DISCLAIMER}


def write(acct):
    tc.write_json(PAPER_FILE, acct)
    return tc.path(PAPER_FILE)


# --- the report ------------------------------------------------------------------------------------

def report_dates():
    """Dates of the saved reports, newest first."""
    d = tc.path(REPORTS_DIR)
    if not os.path.isdir(d):
        return []
    return sorted({m.group(1) for m in (DATE_RE.match(f) for f in os.listdir(d)) if m and m.group(2) == "md"},
                  reverse=True)


def report_due(cfg, today):
    """Due when the last report is report.every_days or more days old; the first one is due that many days after
    paper.start. -> (due, next_due date)."""
    every = int(cfg["report"]["every_days"])
    have = report_dates()
    last = have[0] if have else None
    base = tc.parse_date(last) if last else tc.parse_date(cfg["paper"]["start"])
    nxt = (base + dt.timedelta(days=every)).isoformat()
    return today >= nxt, nxt


def _pct(x, sign=True):
    return "UNKNOWN" if x is None else (("%+.2f%%" if sign else "%.1f%%") % x)


def _r(x):
    return "-" if x is None else "%+.2fR" % x


def _rs(x):
    return "-" if x is None else tc.fmt_rs(x, 0)


def _num(x):
    return "-" if x is None else ("%.2f" % x)


def _dd(v):
    if v.get("max_drawdown_pct") is None:
        return "-"
    if not v.get("drawdown_trough"):
        return "0.00%"
    return "%.2f%% (%s to %s)" % (v["max_drawdown_pct"], v["drawdown_peak"], v["drawdown_trough"])


def _bench_cell(b):
    if b.get("status") != "OK":
        return "UNKNOWN (%s)" % b.get("reason", "not fetched")
    return "%s (%s to %s)" % (_pct(b.get("total_return_pct")), b["start"], b["end"])


def make_report(cfg, acct, days, tracker_store, today=None, bench_fetch=None):
    """-> the report document (json) with its markdown in ["md"]."""
    today = today or acct["today"]
    start = acct["start"]
    frm = max(start, (tc.parse_date(today) - dt.timedelta(days=days)).isoformat())
    per, allv = view(cfg, acct, frm, today), view(cfg, acct, start, today)
    fetch = memo(bench_fetch)
    b_per = benchmark(cfg, frm, today, fetch) if frm > start else acct["benchmark"]
    b_all = acct["benchmark"]
    n_closed = acct["totals"]["closed_trades"]
    banners = [BANNER_PAPER] + ([early_banner(n_closed)] if n_closed < tc.MIN_TRADES else []) + \
              [b for b in acct["banners"] if b != BANNER_PAPER and not b.startswith("Too early")]
    closed = sorted([p for p in acct["positions"] if p["state"] == "closed" and frm <= p["exited"] <= today],
                    key=lambda p: (p["exited"], p["symbol"]))
    opened = sorted([p for p in acct["positions"] if p["state"] == "open"], key=lambda p: (p["filled"], p["symbol"]))
    waiting = [p for p in acct["positions"] if p["state"] == "waiting"]
    skipped = [s for s in acct["skipped"] if s["list_date"] >= frm]
    summ = T.summary(tracker_store.get("rows", []), tracker_store)
    t = acct["totals"]
    L = ["# Paper account report, %s" % today, ""]
    for b in banners:
        L.append("> **%s**" % b)
    L.append("> %s" % tc.DISCLAIMER)
    L += ["", "PASS picks only, since %s; capital %s, at most %d open, broker %s. Prices to %s."
          % (start, _rs(acct["capital"]), acct["max_open_positions"], acct.get("broker") or "-", today), ""]
    L += ["## Paper account (PASS only)", "",
          "| | Last %s (%s to %s) | Since %s |" % (tc.plural(days, "day"), frm, today, start), "|---|---|---|"]
    rows = (("Equity", _rs(per["equity"]), _rs(allv["equity"])),
            ("Return", _pct(per["return_pct"]), _pct(allv["return_pct"])),
            ("Closed trades", str(per["closed_trades"]), str(allv["closed_trades"])),
            ("Win rate", _pct(per["win_rate_pct"], False) if per["closed_trades"] else "-",
             _pct(allv["win_rate_pct"], False) if allv["closed_trades"] else "-"),
            ("Average R", _r(per["avg_r"]), _r(allv["avg_r"])),
            ("P&L of closed trades", _rs(per["pnl_rs"]), _rs(allv["pnl_rs"])),
            ("Max drawdown", _dd(per), _dd(allv)),
            ("Longest losing streak", str(per["longest_losing_streak"]), str(allv["longest_losing_streak"])),
            ("Shariah BeES, bought and held", _bench_cell(b_per), _bench_cell(b_all)))
    L += ["| %s | %s | %s |" % r for r in rows]
    L += ["", "Now: %s open (unrealised %s), %s waiting to buy, cash %s, open risk %s at the planned stops."
          % (t["open_positions"], _rs(t["unrealised_pnl_rs"]), t["waiting_to_buy"], _rs(t["cash"]),
             _rs(t["open_risk_rs"])), ""]

    def table(title, head, items, fmt, empty):
        out = ["## %s" % title, ""]
        if not items:
            return out + [empty, ""]
        out += ["| %s |" % " | ".join(head), "|%s" % ("---|" * len(head))]
        out += ["| %s |" % " | ".join(fmt(x)) for x in items[:MAX_TABLE]]
        if len(items) > MAX_TABLE:
            out.append("| ... and %d more (in the .json) |%s" % (len(items) - MAX_TABLE, " |" * (len(head) - 1)))
        return out + [""]

    L += table("Trades closed in the last %s" % tc.plural(days, "day"),
               ("Stock", "Setup", "Mode", "Bought", "Entry", "Exit on", "Exit", "Result", "R", "P&L"), closed,
               lambda p: (p["symbol"], p["setup"], p["mode"], p["filled"], _num(p["fill"]), p["exited"],
                          _num(p["exit"]), p["status"], _r(p["r"]), _rs(p["pnl_rs"])), "None.")
    L += table("Positions still open",
               ("Stock", "Setup", "Mode", "Bought", "Entry", "Last close", "Stop", "Target", "R now"), opened,
               lambda p: (p["symbol"], p["setup"], p["mode"], p["filled"], _num(p["fill"]), _num(p.get("last")),
                          _num(p["stop"]), _num(p["target"]), _r(p["r"])), "None.")
    if waiting:
        L += ["Waiting to buy: %s." % ", ".join("%s (list %s, above %s, until %s)" % (
            p["symbol"], p["list_date"], _num(p["entry"]), p.get("valid_until") or "-") for p in waiting), ""]
    L += table("PASS picks skipped in the last %s" % tc.plural(days, "day"), ("List", "Stock", "Setup", "Why"), skipped,
               lambda s: (s["list_date"], s["symbol"], s["setup"], s["reason"]), "None.")
    L += ["## For reference only: the full tracker", "",
          "Every pick of every list, PASS, WARN and BLOCK: **includes WARN/BLOCK picks you would not buy**. "
          "Not the paper account.", ""]
    a = summ["all"]
    L.append("- all: %d listed, %d bought, %d closed, %d open, %d waiting; win rate %s, average %s, P&L %s"
             % (a["listed"], a["triggered"], a["closed"], a["open"], a["waiting"],
                _pct(a["win_rate_pct"], False) if a["closed"] else "-", _r(a["avg_r"]), _rs(a["pnl_rs"])))
    for g, v in summ.items():
        if g != "all" and not g.startswith("settings: "):
            L.append("- %s: %d listed, %d closed; win rate %s, average %s"
                     % (g, v["listed"], v["closed"], _pct(v["win_rate_pct"], False) if v["closed"] else "-",
                        _r(v["avg_r"])))
    split = T.settings_split(tracker_store)
    if split:
        L.append("- By settings: " + "; ".join("%s %d closed, average %s" % (h, v["stats"]["closed"],
                                                                            _r(v["stats"]["avg_r"]))
                                               for h, v in split.items()))
    L += ["", "---", "Made by tayyib-trader %s on %s. %s" % (tc.VERSION, acct["asof"], tc.DISCLAIMER)]
    md = "\n".join(L) + "\n"
    return {"date": today, "days": days, "period": {"from": frm, "to": today}, "since": start,
            "banners": banners, "paper": {"period": per, "since_start": allv, "totals": t},
            "benchmark": {"period": b_per, "since_start": b_all},
            "closed": [_slim(p) for p in closed], "open": [_slim(p) for p in opened],
            "waiting": [_slim(p) for p in waiting], "skipped": skipped,
            "tracker": {"note": "includes WARN/BLOCK picks you would not buy", "summary": summ},
            "lines": md.count("\n"), "disclaimer": tc.DISCLAIMER, "md": md}


SLIM = ("list_date", "symbol", "name", "mode", "setup", "entry", "stop", "target", "qty", "valid_until", "status",
        "result", "state", "filled", "fill", "exited", "exit", "days", "r", "pnl_rs", "last")


def _slim(p):
    return {k: p.get(k) for k in SLIM}


def write_report(rep):
    os.makedirs(tc.path(REPORTS_DIR), exist_ok=True)
    md = tc.path(REPORTS_DIR, rep["date"] + ".md")
    with open(md, "w", encoding="utf-8", newline="\n") as f:
        f.write(rep["md"])
    doc = {k: v for k, v in rep.items() if k != "md"}
    doc["md_file"] = os.path.join(REPORTS_DIR, rep["date"] + ".md").replace(os.sep, "/")
    tc.write_json(os.path.join(REPORTS_DIR, rep["date"] + ".json"), doc)
    return md, tc.path(REPORTS_DIR, rep["date"] + ".json")
