"""v0.2.9: the paper account (PASS picks only, one cash account; tayyib-tracker/paper.py), the shareable report
(trader/reports/DATE.md and .json, every report.every_days), tracker.py summary / paper / report [--if-due], the
dashboard's paper card and /reports/DATE.md, the email attachment, the metrics moved to core, and the release.
Offline: small synthetic bars and daily lists only (plus the fixtures for the subprocess runs); the clock is fixed
at 2026-10-30 18:00 IST (a Friday) by _util, so "today" below is 2026-10-30."""
import copy
import datetime as dt
import json
import os
import re
import sys
import unittest
from unittest import mock

from _util import ROOT, OfflineCase, tc

for d in ("tayyib-tracker", "tayyib-dashboard", "tayyib-email", "tayyib-backtest"):
    sys.path.insert(0, os.path.join(ROOT, d))
import paper as P  # noqa: E402
import tracker as T  # noqa: E402
import dashboard as DASH  # noqa: E402
import email_report as ER  # noqa: E402
import backtest as bt  # noqa: E402

TODAY = "2026-10-30"
START = "2026-09-01"
H = "abcd1234"


def _weekdays(a, b):
    d, end, out = tc.parse_date(a), tc.parse_date(b), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


DAYS = _weekdays("2026-08-03", "2026-11-30")          # series() stops at TODAY


def nxt(d, k=1):
    return DAYS[DAYS.index(d) + k]


FILL = (100.0, 102.0, 99.5, 101.5)      # reaches the 101 entry (fill 101), stays above the 95 stop
WIN = (102.0, 112.0, 101.5, 111.0)      # reaches the 110 target
LOSS = (100.0, 100.5, 94.0, 94.5)       # reaches the 95 stop
BOTH = (100.0, 112.0, 94.0, 100.0)      # touches the stop and the target


def series(events=None, base=100.0, upto=TODAY):
    events = events or {}
    out = []
    for d in DAYS:
        if d > upto:
            break
        o, h, l, c = events.get(d, (base, base, base, base))
        out.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 100000})
    return out


def pick(sym, date, risk="PASS", entry=101.0, stop=95.0, target=110.0, qty=10, valid=None, mode="swing",
         setup="breakout", hold=20):
    return {"symbol": sym, "mode": mode, "setup": setup, "risk": risk, "entry": entry, "stop": stop,
            "target": target, "qty": qty, "valid_until": valid or nxt(date, 3), "max_hold_days": hold}


def doc(date, rows):
    return {"date": date, "settings": {"hash": H}, "rows": rows}


def bench_ok(sym, range_=None):
    return series(base=50.0), {}


def bench_err(sym, range_=None):
    raise tc.FetchError("offline: no %s" % sym)


def config(**over):
    c = copy.deepcopy(tc.validate_config({})[0])
    c["paper"]["start"] = START
    c["capital"] = 100000
    c["max_open_positions"] = 6
    c.update(over)
    return c


def buy_cost(cfg, qty, px):
    return round(qty * px + tc.order_charges("BUY", px, qty, cfg)["total"], 2)


def many(per_day=2, last=None, first=START, repeat_every=0):
    """A list every weekday from `first` to `last`, `per_day` PASS picks each (a new symbol each, unless
    repeat_every), each filling the next day and closing 3 days after the list (target or stop, alternating), or
    still open at the end. Plus one WARN and one BLOCK row per list that would have won."""
    last = last or nxt(TODAY, -2)          # the last lists are still open today
    lists, bars = [], {}
    for i, d in enumerate(x for x in DAYS if first <= x <= last):
        rows = []
        for j in range(per_day):
            sym = "S%03d%d" % (i, j)
            if repeat_every and i % repeat_every == 0 and j == 0 and i:
                sym = "S%03d%d" % (i - 1, 0)          # the stock of the day before again: held / waiting
            ev = {nxt(d, 1): FILL}
            if nxt(d, 3) <= TODAY:
                ev[nxt(d, 3)] = WIN if (i + j) % 2 else LOSS
            bars.setdefault(sym, series(ev))
            rows.append(pick(sym, d, setup=("breakout", "pullback")[j % 2]))
        for risk in ("WARN", "BLOCK"):
            sym = "%s%03d" % (risk[0], i)
            bars[sym] = series({nxt(d, 1): FILL, nxt(d, 3): WIN} if nxt(d, 3) <= TODAY else {nxt(d, 1): FILL})
            rows.append(pick(sym, d, risk=risk))
        lists.append(doc(d, rows))
    return lists, bars


def build(cfg, lists, bars, fe=None, bench=bench_ok, today=TODAY):
    return P.build(cfg, today, lists=lists, bars_by=bars, fetch_errors=fe or {}, bench_fetch=bench)


def tracker_store(lists, bars, cfg):
    rows = []
    for dd in lists:
        for r in dd["rows"]:
            row = T.list_row(dd, r, H)
            if row and bars.get(row["symbol"]):
                row.update(T.follow(row, bars[row["symbol"]], cfg, TODAY))
            if row:
                rows.append(row)
    return {"rows": rows, "settings": {}}


class Base(OfflineCase):
    def reasons(self, skipped, sym):
        return [s["reason"] for s in skipped if s["symbol"] == sym]

    def assertSettledNeverNegative(self, cfg, ledger):
        cap = float(cfg["capital"])
        for d in sorted({x[0] for x in ledger}):
            settled = cap + sum(a for x, a, k in ledger if (k == "buy" and x <= d) or (k == "sale" and x < d))
            self.assertGreaterEqual(settled, -1e-6, "settled cash negative on %s: %s" % (d, settled))
        run = cap
        for x, a, k in sorted(ledger, key=lambda e: (e[0], e[2] != "buy")):
            run += a
            self.assertGreaterEqual(run, -1e-6, (x, a, k))


# --- 1. PASS only, from paper.start ----------------------------------------------------------------

class PassOnly(Base):
    def scenario(self):
        early, d1 = "2026-08-31", START
        lists = [doc(early, [pick("EARLY", early)]),
                 doc(d1, [pick("WARNX", d1, risk="WARN"), pick("PASSA", d1), pick("BLOCKX", d1, risk="BLOCK")])]
        bars = {s: series({nxt(early, 1): FILL, nxt(d1, 1): FILL, nxt(d1, 3): WIN})
                for s in ("EARLY", "WARNX", "PASSA", "BLOCKX")}
        return lists, bars

    def check(self, acct):
        syms = {p["symbol"] for p in acct["positions"]} | {s["symbol"] for s in acct["skipped"]}
        self.assertEqual(syms, {"PASSA"})
        self.assertEqual(acct["lists"], [START])

    def test_given_lists(self):
        lists, bars = self.scenario()
        self.check(build(config(), lists, bars))

    def test_saved_lists(self):
        lists, bars = self.scenario()
        os.makedirs(os.path.join(self.dir, "daily"))
        for dd in lists:
            self.write("daily/%s.json" % dd["date"], dd)
        self.assertEqual([x["date"] for x in P.load_lists(START, TODAY)], [START])
        self.check(P.build(config(), TODAY, bars_by=bars, fetch_errors={}, bench_fetch=bench_ok))

    def test_warn_block_never_skipped_even_when_full(self):
        d = START
        cfg = config(max_open_positions=1)
        lists = [doc(d, [pick("A", d), pick("W", d, risk="WARN"), pick("B", d, risk="BLOCK"), pick("C", d)])]
        bars = {s: series({nxt(d, 1): FILL}) for s in "AWBC"}
        pos, sk, _ = P.simulate(cfg, lists, bars, TODAY)
        self.assertEqual([p["symbol"] for p in pos], ["A"])
        self.assertEqual([s["symbol"] for s in sk], ["C"])


# --- 2. skip reasons -------------------------------------------------------------------------------

class Skips(Base):
    def test_slots_count_waiting_and_list_order_decides(self):
        d = START
        bars = {s: series({nxt(d, 1): FILL}) for s in "ABC"}
        cfg = config(max_open_positions=2)
        for order, out in (("ABC", "C"), ("CAB", "B"), ("BCA", "A")):
            pos, sk, _ = P.simulate(cfg, [doc(d, [pick(s, d) for s in order])], bars, TODAY)
            self.assertEqual(sorted(p["symbol"] for p in pos), sorted(set(order) - {out}), order)
            self.assertEqual([s["symbol"] for s in sk], [out])
            self.assertTrue(sk[0]["reason"].startswith(P.SLOTS), sk[0]["reason"])
            self.assertIn("2 of 2 open or waiting", sk[0]["reason"])

    def test_slots_count_open(self):
        d1, d3 = START, nxt(START, 2)
        bars = {"A": series({nxt(d1, 1): FILL}), "B": series({nxt(d1, 1): FILL}), "C": series({nxt(d3, 1): FILL})}
        lists = [doc(d1, [pick("A", d1), pick("B", d1)]), doc(d3, [pick("C", d3)])]
        pos, sk, _ = P.simulate(config(max_open_positions=2), lists, bars, TODAY)
        self.assertEqual(sorted(p["symbol"] for p in pos), ["A", "B"])             # both open on d3 (time exit later)
        self.assertTrue(all(p["filled"] == nxt(d1, 1) for p in pos))
        self.assertTrue(self.reasons(sk, "C")[0].startswith(P.SLOTS))

    def test_cash_at_list_time_reserved_by_waiting(self):
        d = START
        cfg = config()
        need = buy_cost(cfg, 10, 101.0)
        cfg["capital"] = round(2.5 * need, 2)
        bars = {s: series({nxt(d, 1): FILL}) for s in "ABC"}
        pos, sk, _ = P.simulate(cfg, [doc(d, [pick(s, d) for s in "ABC"])], bars, TODAY)
        self.assertEqual(sorted(p["symbol"] for p in pos), ["A", "B"])
        r = self.reasons(sk, "C")
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0].startswith(P.CASH + ":"), r)
        self.assertFalse(r[0].startswith(P.CASH_AT_FILL), r)
        pos, sk, _ = P.simulate(cfg, [doc(d, [pick("C", d)])], bars, TODAY)      # alone it fits
        self.assertEqual([p["symbol"] for p in pos], ["C"])

    def test_cash_at_fill_price_gap_up(self):
        d = START
        cfg = config()
        cfg["capital"] = buy_cost(cfg, 10, 101.0) + 10
        bars = {"A": series({nxt(d, 1): (105.0, 106.0, 104.0, 105.5)})}
        pos, sk, ledger = P.simulate(cfg, [doc(d, [pick("A", d, target=130.0)])], bars, TODAY)
        self.assertEqual(pos, [])
        self.assertEqual(len(sk), 1)
        self.assertTrue(sk[0]["reason"].startswith(P.CASH_AT_FILL), sk[0]["reason"])
        self.assertEqual(sk[0]["on"], nxt(d, 1))
        self.assertEqual(ledger, [])

    def test_held_and_waiting(self):
        d1 = START
        d2, d3 = nxt(d1, 1), nxt(d1, 2)
        bars = {"A": series({d2: FILL}),                                   # bought on d2
                "W": series({nxt(d1, 3): FILL})}                           # waiting until d1+3
        lists = [doc(d1, [pick("A", d1), pick("W", d1)]),
                 doc(d2, [pick("W", d2)]),
                 doc(d3, [pick("A", d3)])]
        pos, sk, _ = P.simulate(config(), lists, bars, TODAY)
        self.assertEqual(sorted((p["symbol"], p["list_date"]) for p in pos), [("A", d1), ("W", d1)])
        self.assertTrue(self.reasons(sk, "A")[0].startswith(P.HELD), sk)
        self.assertTrue(self.reasons(sk, "W")[0].startswith(P.WAITING), sk)
        self.assertIn(d1, self.reasons(sk, "A")[0])

    def test_no_prices_no_qty_and_banner(self):
        d = START
        lists = [doc(d, [pick("NOPX", d), pick("ZERO", d, qty=0), pick("OKAY", d)])]
        bars = {"ZERO": series({nxt(d, 1): FILL}), "OKAY": series({nxt(d, 1): FILL}), "NOPX": None}
        acct = build(config(), lists, bars, fe={"NOPX": "offline: missing fixture"})
        r = {s["symbol"]: s["reason"] for s in acct["skipped"]}
        self.assertTrue(r["NOPX"].startswith(P.NO_PRICES), r)
        self.assertIn("offline: missing fixture", r["NOPX"])
        self.assertTrue(r["ZERO"].startswith(P.NO_QTY), r)
        self.assertEqual([p["symbol"] for p in acct["positions"]], ["OKAY"])
        self.assertTrue(any("NOPX" in b and b.startswith("Prices could not be fetched") for b in acct["banners"]),
                        acct["banners"])
        self.assertEqual(acct["banners"][0], P.BANNER_PAPER)


# --- 3 / 4. the tracker's own fills and exits ----------------------------------------------------

FIELDS = ("filled", "fill", "exited", "exit", "r", "pnl_rs", "status")


class SameAsTracker(Base):
    def scenario(self):
        d = START
        d_open, d_wait = nxt(TODAY, -3), nxt(TODAY, -1)
        lists = [doc(d, [pick("TGT", d), pick("STP", d), pick("TIM", d, hold=3), pick("BEV", d),
                         pick("NTR", d), pick("GAP", d, target=120.0), pick("FDS", d), pick("BTH", d),
                         pick("DLV", d, mode="delivery", setup="trend", hold=None)]),
                 doc(d_open, [pick("OPN", d_open)]),
                 doc(d_wait, [pick("WAI", d_wait, valid="2026-11-04")])]
        f, e2, e3 = nxt(d, 1), nxt(d, 2), nxt(d, 3)
        bars = {"TGT": series({f: FILL, e3: WIN}), "STP": series({f: FILL, e2: LOSS}), "TIM": series({f: FILL}),
                "BEV": series({f: FILL, e2: (101.0, 108.0, 101.0, 107.0), e3: (106.0, 106.0, 100.0, 100.5)}),
                "NTR": series(), "GAP": series({f: (103.0, 104.0, 102.5, 103.5), nxt(d, 4): (110, 121, 109, 120)}),
                "FDS": series({f: (100.0, 102.0, 94.0, 96.0)}), "BTH": series({f: FILL, e2: BOTH}),
                "DLV": series({f: FILL, nxt(d, 6): WIN}),
                "OPN": series({nxt(d_open, 1): (100.0, 102.0, 99.5, 101.5), TODAY: (101.0, 104.0, 100.5, 103.0)}),
                "WAI": series()}
        return lists, bars

    def test_each_position_equals_follow(self):
        lists, bars = self.scenario()
        cfg = config(max_open_positions=20)
        pos, sk, _ = P.simulate(cfg, lists, bars, TODAY)
        self.assertEqual(sk, [])
        self.assertEqual(len(pos), 11)
        for p in pos:
            dd = next(x for x in lists if x["date"] == p["list_date"])
            r = next(x for x in dd["rows"] if x["symbol"] == p["symbol"])
            want = T.follow(T.list_row(dd, r, H), bars[p["symbol"]], cfg, TODAY)
            self.assertEqual({k: p[k] for k in FIELDS}, {k: want[k] for k in FIELDS}, p["symbol"])
        st = {p["symbol"]: p["status"] for p in pos}
        self.assertEqual(st, {"TGT": "TARGET", "STP": "STOP", "TIM": "TIME EXIT", "BEV": "BREAKEVEN",
                              "NTR": "NOT TRIGGERED", "GAP": "TARGET", "FDS": "STOP", "BTH": "STOP",
                              "DLV": "TARGET", "OPN": "OPEN", "WAI": "WAITING"})
        state = {p["symbol"]: p["state"] for p in pos}
        self.assertEqual((state["NTR"], state["OPN"], state["WAI"], state["TGT"]),
                         ("not_triggered", "open", "waiting", "closed"))
        gap = next(p for p in pos if p["symbol"] == "GAP")
        self.assertEqual(gap["fill"], 103.0)

    def test_both_touched_is_stop(self):
        lists, bars = self.scenario()
        pos, _, _ = P.simulate(config(max_open_positions=20), lists, bars, TODAY)
        b = next(p for p in pos if p["symbol"] == "BTH")
        self.assertEqual((b["status"], b["exit"], b["exited"], b["state"]), ("STOP", 95.0, nxt(START, 2), "closed"))
        self.assertLess(b["pnl_rs"], 0)

    def test_equals_tracker_update(self):
        lists, bars = self.scenario()
        cfg = config(max_open_positions=20)
        pos, _, _ = P.simulate(cfg, lists, bars, TODAY)
        store = {"rows": [T.list_row(dd, r, H) for dd in lists for r in dd["rows"]], "settings": {}}
        with mock.patch.object(tc, "get_daily_bars", side_effect=lambda s, *a, **k: (bars[s], {})):
            n, errors = T.update(store, cfg)
        self.assertEqual((n, errors), (11, []))
        got = {(r["date"], r["symbol"]): r for r in store["rows"]}
        for p in pos:
            r = got[(p["list_date"], p["symbol"])]
            self.assertEqual({k: p[k] for k in FIELDS}, {k: r[k] for k in FIELDS}, p["symbol"])


# --- 5. proceeds settle the next day --------------------------------------------------------------

class Settlement(Base):
    def scenario(self, b_fill_day):
        d0 = START
        d1, d2, d3 = nxt(d0, 1), nxt(d0, 2), nxt(d0, 3)
        cfg = config()
        need = buy_cost(cfg, 10, 101.0)
        cfg["capital"] = round(2 * need + 5, 2)
        gap = (120.0, 121.0, 119.0, 120.0)
        bars = {"A": series({d1: FILL, d3: WIN}), "B": series({b_fill_day: gap})}
        lists = [doc(d0, [pick("A", d0)]), doc(d2, [pick("B", d2, target=150.0, valid=nxt(d2, 3))])]
        return cfg, lists, bars, d3

    def test_buy_on_exit_day_cannot_use_the_proceeds(self):
        cfg, lists, bars, d3 = self.scenario(nxt(START, 3))
        pos, sk, ledger = P.simulate(cfg, lists, bars, TODAY)
        a = next(p for p in pos if p["symbol"] == "A")
        self.assertEqual((a["exited"], a["status"]), (d3, "TARGET"))
        cost_b = buy_cost(cfg, 10, 120.0)
        self.assertGreater(cost_b, cfg["capital"] - a["cost_rs"])                       # needs the proceeds
        self.assertLessEqual(cost_b, cfg["capital"] - a["cost_rs"] + a["proceeds_rs"])  # fits with them
        self.assertEqual([p["symbol"] for p in pos], ["A"])
        self.assertEqual(len(sk), 1)
        self.assertTrue(sk[0]["reason"].startswith(P.CASH_AT_FILL), sk[0]["reason"])
        self.assertEqual(sk[0]["on"], d3)
        self.assertSettledNeverNegative(cfg, ledger)

    def test_buy_the_day_after_uses_them(self):
        cfg, lists, bars, d3 = self.scenario(nxt(START, 4))
        pos, sk, ledger = P.simulate(cfg, lists, bars, TODAY)
        self.assertEqual(sk, [])
        b = next(p for p in pos if p["symbol"] == "B")
        self.assertEqual(b["filled"], nxt(START, 4))
        self.assertIn((nxt(START, 4), -b["cost_rs"], "buy"), ledger)
        self.assertSettledNeverNegative(cfg, ledger)

    def test_never_negative_on_a_busy_tight_account(self):
        lists, bars = many(per_day=3)
        cfg = config(max_open_positions=4)
        cfg["capital"] = round(3.3 * buy_cost(cfg, 10, 101.0), 2)
        pos, sk, ledger = P.simulate(cfg, lists, bars, TODAY)
        self.assertTrue(any(s["reason"].startswith(P.CASH) for s in sk))
        self.assertSettledNeverNegative(cfg, ledger)


# --- 6. totals ---------------------------------------------------------------------------------------

class Totals(Base):
    def check(self, cfg, acct):
        t, eq, pos = acct["totals"], acct["equity_curve"], acct["positions"]
        closed = [p for p in pos if p["state"] == "closed"]
        opened = [p for p in pos if p["state"] == "open"]
        self.assertTrue(eq)
        self.assertEqual(eq[-1]["date"], TODAY)
        self.assertEqual(t["equity"], eq[-1]["equity"])
        for c in eq:
            self.assertAlmostEqual(c["equity"], c["cash"] + c["positions_value"], delta=0.011, msg=c["date"])
        value = sum(p["qty"] * P._close_on(acct_bars(self, p), TODAY)
                    - tc.order_charges("SELL", P._close_on(acct_bars(self, p), TODAY), p["qty"], cfg)["total"]
                    for p in opened)
        self.assertAlmostEqual(t["equity"], t["cash"] + value, delta=0.05)
        self.assertAlmostEqual(t["total_pnl_rs"] or 0, sum(p["pnl_rs"] for p in closed), delta=0.011)
        self.assertAlmostEqual(t["cash"], cfg["capital"] + sum(p["pnl_rs"] for p in closed)
                               - sum(p["cost_rs"] for p in opened), delta=0.05)
        trades = [{"symbol": p["symbol"], "r": p["r"], "pnl_rs": p["pnl_rs"], "exit_date": p["exited"],
                   "charges": tc.round_trip(p["fill"], p["exit"], p["qty"], cfg)} for p in closed]
        m = tc.trade_stats(trades)
        self.assertEqual((t["closed_trades"], t["win_rate_pct"], t["avg_r"], t["total_pnl_rs"],
                          t["longest_losing_streak"], t["total_charges_rs"]),
                         (m["trades"], m["win_rate_pct"], m["avg_r"], m["pnl_rs"], m["longest_losing_streak"],
                          m["total_charges_rs"]))
        self.assertEqual(t["open_positions"], len(opened))
        self.assertEqual(t["skipped"], len(acct["skipped"]))
        self.assertEqual(t["too_few"], m["trades"] < 30)
        for key in ("by_mode", "by_setup"):
            for g, s in acct["groups"][key].items():
                self.assertEqual(s["too_few"], s["trades"] < 30, (key, g))
        return m

    def test_under_30(self):
        lists, bars = many(per_day=2, last=nxt(START, 5))
        self.bars = bars
        cfg = config()
        acct = build(cfg, lists, bars)
        m = self.check(cfg, acct)
        self.assertTrue(0 < m["trades"] < 30, m["trades"])
        self.assertTrue(acct["totals"]["too_few"])
        self.assertIn(P.early_banner(m["trades"]), acct["banners"])
        self.assertTrue(all(s["too_few"] for g in acct["groups"].values() for s in g.values()))

    def test_30_and_more_with_open_and_skips(self):
        lists, bars = many(per_day=3, repeat_every=4)
        self.bars = bars
        cfg = config()
        acct = build(cfg, lists, bars)
        m = self.check(cfg, acct)
        self.assertGreaterEqual(m["trades"], 30)
        self.assertFalse(acct["totals"]["too_few"])
        self.assertFalse(any(b.startswith("Too early") for b in acct["banners"]))
        self.assertFalse(acct["groups"]["by_mode"]["swing"]["too_few"])
        self.assertTrue(acct["skipped"])
        self.assertTrue(acct["totals"]["open_positions"])
        _, _, ledger = P.simulate(cfg, lists, bars, TODAY)
        self.assertSettledNeverNegative(cfg, ledger)


def acct_bars(case, p):
    return case.bars[p["symbol"]]


# --- 7. benchmark UNKNOWN ---------------------------------------------------------------------------

class Benchmark(Base):
    def test_fetch_error_is_unknown_with_reason(self):
        lists, bars = many(per_day=1, last=nxt(START, 3))
        cfg = config()
        acct = build(cfg, lists, bars, bench=bench_err)
        b = acct["benchmark"]
        self.assertEqual(b["status"], "UNKNOWN")
        self.assertIn("offline", b["reason"])
        self.assertNotIn("total_return_pct", b)
        rep = P.make_report(cfg, acct, 15, tracker_store(lists, bars, cfg), TODAY, bench_fetch=bench_err)
        line = next(x for x in rep["md"].splitlines() if x.startswith("| Shariah BeES"))
        self.assertIn("UNKNOWN (could not be fetched", line)
        self.assertEqual(rep["benchmark"]["period"]["status"], "UNKNOWN")

    def test_ok_benchmark(self):
        lists, bars = many(per_day=1, last=nxt(START, 3))
        acct = build(config(), lists, bars)
        self.assertEqual(acct["benchmark"]["status"], "OK")
        self.assertNotIn("curve", acct["benchmark"])


# --- 8. the report ------------------------------------------------------------------------------------

SECTIONS = ("## Paper account (PASS only)", "## Trades closed in the last", "## Positions still open",
            "## PASS picks skipped", "## For reference only: the full tracker")


class Report(Base):
    def make(self, lists, bars, cfg=None):
        cfg = cfg or config()
        acct = build(cfg, lists, bars)
        return acct, P.make_report(cfg, acct, 15, tracker_store(lists, bars, cfg), TODAY, bench_fetch=bench_ok)

    def test_banners_and_sections_in_order(self):
        lists, bars = many(per_day=2, last=nxt(START, 5))
        acct, rep = self.make(lists, bars)
        L = rep["md"].splitlines()
        n = acct["totals"]["closed_trades"]
        self.assertEqual(L[0], "# Paper account report, %s" % TODAY)
        self.assertEqual(L[2], "> **Paper only: nothing was bought.**")
        self.assertEqual(L[3], "> **Too early to judge: %d closed trades (need 30+).**" % n)
        self.assertTrue(L[4].startswith("> Not financial advice"), L[4])
        self.assertIn("Not a fatwa", L[4])
        idx = [next(i for i, x in enumerate(L) if x.startswith(s)) for s in SECTIONS]
        self.assertEqual(idx, sorted(idx))
        self.assertGreater(idx[0], 4)
        tail = "\n".join(L[idx[-1]:])
        self.assertIn("includes WARN/BLOCK picks you would not buy", tail)
        self.assertEqual(rep["tracker"]["note"], "includes WARN/BLOCK picks you would not buy")
        self.assertEqual(rep["banners"][:2], [P.BANNER_PAPER, P.early_banner(n)])

    def test_short_with_many_trades_and_skips_and_written(self):
        lists, bars = many(per_day=6, repeat_every=3)
        cfg = config(max_open_positions=10)
        acct, rep = self.make(lists, bars, cfg)
        closed = [p for p in acct["positions"] if p["state"] == "closed"
                  and rep["period"]["from"] <= p["exited"] <= TODAY]
        skipped = [s for s in acct["skipped"] if s["list_date"] >= rep["period"]["from"]]
        self.assertGreater(len(closed), P.MAX_TABLE)
        self.assertGreater(len(skipped), P.MAX_TABLE)
        self.assertGreaterEqual(acct["totals"]["closed_trades"], 30)
        L = rep["md"].splitlines()
        self.assertLess(len(L), 150, len(L))
        self.assertEqual(rep["lines"], rep["md"].count("\n"))
        self.assertNotIn("Too early", rep["md"])
        self.assertEqual(L[2], "> **Paper only: nothing was bought.**")
        self.assertTrue(L[3].startswith("> Not financial advice"))
        more = [x for x in L if x.startswith("| ... and ")]
        self.assertEqual(more, ["| ... and %d more (in the .json) | | | | | | | | | |" % (len(closed) - P.MAX_TABLE),
                                "| ... and %d more (in the .json) | | | |" % (len(skipped) - P.MAX_TABLE)])
        md, js = P.write_report(rep)
        self.assertEqual(os.path.normpath(md), os.path.join(self.dir, "reports", TODAY + ".md"))
        with open(md, encoding="utf-8") as f:
            self.assertEqual(f.read(), rep["md"])
        doc_ = self.read("reports/%s.json" % TODAY)
        self.assertNotIn("md", doc_)
        self.assertEqual(doc_["md_file"], "reports/%s.md" % TODAY)
        self.assertEqual(len(doc_["closed"]), len(closed))                     # everything in the .json
        self.assertEqual(len(doc_["skipped"]), len(skipped))
        self.assertEqual(P.report_dates(), [TODAY])


# --- 9. when the report is due ----------------------------------------------------------------------

class Due(Base):
    def cfg(self, start="2026-10-01", every=15):
        c = config()
        c["paper"]["start"], c["report"]["every_days"] = start, every
        return c

    def put(self, date):
        os.makedirs(os.path.join(self.dir, "reports"), exist_ok=True)
        with open(os.path.join(self.dir, "reports", date + ".md"), "w") as f:
            f.write("# r\n")

    def test_first_and_next(self):
        c = self.cfg()
        self.assertEqual(P.report_due(c, "2026-10-15"), (False, "2026-10-16"))
        self.assertEqual(P.report_due(c, "2026-10-16"), (True, "2026-10-16"))
        self.assertEqual(P.report_due(c, "2026-10-28")[0], True)
        self.put("2026-10-20")
        self.assertEqual(P.report_due(c, "2026-11-03"), (False, "2026-11-04"))
        self.assertEqual(P.report_due(c, "2026-11-05"), (True, "2026-11-04"))

    def test_after_a_report_and_a_changed_every_days(self):
        c = self.cfg()
        self.put("2026-10-20")
        self.assertEqual(P.report_due(c, "2026-11-03"), (False, "2026-11-04"))
        self.assertEqual(P.report_due(c, "2026-11-04"), (True, "2026-11-04"))
        c["report"]["every_days"] = 5
        self.assertEqual(P.report_due(c, "2026-10-24"), (False, "2026-10-25"))
        self.assertEqual(P.report_due(c, "2026-10-25"), (True, "2026-10-25"))
        self.put("2026-10-26")                                   # the newest counts
        self.assertEqual(P.report_due(c, "2026-10-30"), (False, "2026-10-31"))
        with open(os.path.join(self.dir, "reports", "2026-10-29.json"), "w") as f:   # a .json alone is no report
            f.write("{}")
        self.assertEqual(P.report_due(c, "2026-10-30"), (False, "2026-10-31"))

    def test_cli_if_due(self):
        os.makedirs(os.path.join(self.dir, "daily"))
        self.write("daily/2026-10-20.json", doc("2026-10-20", [pick("ALFA", "2026-10-20", entry=1e6, stop=1.0,
                                                                     target=2e6)]))
        self.write("config.json", {"paper": {"start": "2026-10-20"}})          # first due 2026-11-04 > today
        out = self.run_script("tayyib-tracker/tracker.py", "report", "--if-due")
        self.assertEqual((out["written"], out["next_due"]), (False, "2026-11-04"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "reports")) and
                         os.listdir(os.path.join(self.dir, "reports")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "paper_account.json")))
        self.write("config.json", {"paper": {"start": "2026-10-01"}})          # first due 2026-10-16 <= today
        out = self.run_script("tayyib-tracker/tracker.py", "report", "--if-due")
        self.assertTrue(out["written"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "reports", TODAY + ".md")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "reports", TODAY + ".json")))
        self.assertIn("summary", out)
        out = self.run_script("tayyib-tracker/tracker.py", "report", "--if-due")   # same day again: not due
        self.assertEqual((out["written"], out["next_due"]), (False, "2026-11-14"))
        self.assertEqual(self.read("paper_account.json")["lists"], ["2026-10-20"])

    def test_cli_summary_and_paper(self):
        self.write("tracker.json", {"rows": []})
        out = self.run_script("tayyib-tracker/tracker.py", "summary")
        self.assertIn("summary", out)
        self.assertIn("all", out["summary"])
        out = self.run_script("tayyib-tracker/tracker.py", "paper")
        self.assertEqual(out["banners"][0], P.BANNER_PAPER)
        self.assertEqual(out["totals"]["closed_trades"], 0)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "reports")))


# --- 10. config ---------------------------------------------------------------------------------------

class Config(unittest.TestCase):
    def test_invalid_values_fall_back(self):
        for user, key, dflt in (({"paper": {"start": "2026-13-01"}}, "paper.start", "2026-11-10"),
                                ({"paper": {"start": 5}}, "paper.start", "2026-11-10"),
                                ({"paper": {"start": "2026-1-5"}}, "paper.start", "2026-11-10"),
                                ({"report": {"every_days": 0}}, "report.every_days", 15),
                                ({"report": {"every_days": 91}}, "report.every_days", 15),
                                ({"report": {"every_days": 7.5}}, "report.every_days", 15),
                                ({"report": {"every_days": "7"}}, "report.every_days", 15)):
            cfg, notes = tc.validate_config(user)
            sec, k = key.split(".")
            self.assertEqual(cfg[sec][k], dflt, user)
            self.assertTrue(any(n.startswith("CONFIG: %s" % key) and "invalid" in n for n in notes), (user, notes))

    def test_valid_values_kept_and_outside_the_hash(self):
        base = tc.settings_snapshot(tc.validate_config({})[0])
        self.assertEqual(base["label"], "default@5")
        for user in ({"paper": {"start": "2026-10-01"}}, {"report": {"every_days": 1}},
                     {"report": {"every_days": 90}},
                     {"paper": {"start": "2027-01-04"}, "report": {"every_days": 30}}):
            cfg, notes = tc.validate_config(user)
            self.assertEqual(notes, [], user)
            for sec, v in user.items():
                self.assertEqual(cfg[sec], v)
            snap = tc.settings_snapshot(cfg)
            self.assertEqual((snap["hash"], snap["label"]), (base["hash"], "default@5"), user)
            self.assertEqual(snap["differs_from_default"], [])
        self.assertIn("paper.start", tc.SETTINGS_EXCLUDE)
        self.assertIn("report.every_days", tc.SETTINGS_EXCLUDE)
        self.assertEqual(tc.DEFAULT_CONFIG_DOCS["paper.start"]["type"], "date")
        d = tc.DEFAULT_CONFIG_DOCS["report.every_days"]
        self.assertEqual((d["type"], d["min"], d["max"]), ("int", 1, 90))
        self.assertEqual((tc.DEFAULT_CONFIG["paper"]["start"], tc.DEFAULT_CONFIG["report"]["every_days"]),
                         ("2026-11-10", 15))
        self.assertFalse(any(k.startswith(("paper.", "report.")) for k in tc.default_values()))


# --- 11. dashboard ------------------------------------------------------------------------------------

class Dashboard(Base):
    def test_paper_card_and_reports(self):
        lists, bars = many(per_day=1, last=nxt(START, 5))
        cfg = config()
        acct = build(cfg, lists, bars)
        P.write(acct)
        self.write("tracker.json", tracker_store(lists, bars, cfg))
        os.makedirs(os.path.join(self.dir, "reports"))
        for name in ("2026-11-25.md", "2026-11-25.json", "2026-10-30.md", "notes.md", "x.md"):
            with open(os.path.join(self.dir, "reports", name), "w", encoding="utf-8", newline="\n") as f:
                f.write("# report %s\n" % name)
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            f.write("{}")
        res = DASH.api_tracker({})
        pv = res["paper"]
        n = acct["totals"]["closed_trades"]
        self.assertFalse(pv["missing"])
        self.assertEqual(pv["closed"], n)
        self.assertEqual(pv["too_early"], "Too early to judge: %d closed trades (need 30+)." % n)
        self.assertEqual(set(pv["tiles"]), {"equity", "return", "closed", "win_rate", "avg_r", "bench", "open"})
        self.assertEqual(pv["tiles"]["closed"], str(n))
        self.assertEqual([r["date"] for r in pv["reports"]], ["2026-11-25", "2026-10-30"])
        self.assertEqual([r["url"] for r in DASH.report_list()], ["/reports/2026-11-25.md", "/reports/2026-10-30.md"])
        self.assertEqual(DASH.report_file("/reports/2026-11-25.md"), b"# report 2026-11-25.md\n")
        for bad in ("/reports/../config.json", "/reports/x.md", "/reports/2026-11-25.json", "/reports/notes.md",
                    "/reports/2026-11-26.md", "/reports/..%2Fconfig.json", "/reports/2026-11-25.md/",
                    "/reports//2026-11-25.md"):
            self.assertIsNone(DASH.report_file(bad), bad)

    def test_missing_account(self):
        self.assertNotIn("paper", DASH.api_tracker({}))   # nothing at all: the plain "missing" answer (test_v017)
        pv = DASH.paper_view()
        self.assertTrue(pv["missing"])
        self.assertEqual(pv["reports"], [])
        self.assertEqual(pv["banner"], P.BANNER_PAPER)


# --- 12. email --------------------------------------------------------------------------------------

class Email(Base):
    def test_attaches_the_report_only_when_it_exists(self):
        from test_v023 import daily
        self.write("config.json", {"email": {"from": "me@example.com"}})
        cfg = tc.load_config()
        os.makedirs(os.path.join(self.dir, "daily"))
        self.write("daily/%s.json" % TODAY, daily())
        rep = ER.build(tc.parse_date(TODAY), cfg)
        self.assertNotEqual(rep["kind"], "failed")

        def names(msg):
            return [p.get_filename() for p in msg.iter_attachments()]
        self.assertNotIn("paper-report-%s.md" % TODAY, names(ER.message(rep, cfg, "me@example.com",
                                                                          ["me@example.com"])))
        os.makedirs(os.path.join(self.dir, "reports"))
        with open(os.path.join(self.dir, "reports", "2026-10-29.md"), "w") as f:     # another day's: not attached
            f.write("# old\n")
        self.assertFalse([n for n in names(ER.message(rep, cfg, "me@example.com", ["me@example.com"]))
                          if n and n.startswith("paper-report")])
        with open(os.path.join(self.dir, "reports", TODAY + ".md"), "w", encoding="utf-8") as f:
            f.write("# Paper account report, %s\n" % TODAY)
        msg = ER.message(rep, cfg, "me@example.com", ["me@example.com"])
        self.assertIn("paper-report-%s.md" % TODAY, names(msg))
        att = next(p for p in msg.iter_attachments() if p.get_filename() == "paper-report-%s.md" % TODAY)
        self.assertIn("Paper account report", att.get_content())
        self.assertNotIn("paper-report-%s.md" % TODAY,
                         names(ER.message(rep, cfg, "me@example.com", ["me@example.com"], attach=False)))


# --- daily run ----------------------------------------------------------------------------------------

class DailyRun(Base):
    def test_daily_stores_paper(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py", "--no-news")
        self.assertTrue(out["tracker"])
        self.assertIn("all", out["tracker"])
        self.assertIn("paper", out)
        self.assertEqual(set(out["paper"]), {"totals", "report", "next_report"})
        self.assertIsNone(out["paper"]["report"])                 # paper.start 2026-11-10 by default: not due
        self.assertEqual(out["paper"]["next_report"], "2026-11-25")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "paper_account.json")))
        self.assertEqual(self.read("daily/%s.json" % TODAY)["paper"], out["paper"])


# --- 13. release and baseline -----------------------------------------------------------------------

class Release(unittest.TestCase):
    def text(self, *p):
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_versions(self):
        self.assertEqual(tc.VERSION, "0.2.9")
        self.assertEqual(json.loads(self.text(".claude-plugin", "plugin.json"))["version"], "0.2.9")
        self.assertIn('"0.2.9"', self.text(".claude-plugin", "marketplace.json"))
        self.assertRegex(self.text("mcp", "server.py"), r'(?m)^VERSION = "0\.2\.9"$')
        top = next(x for x in self.text("CHANGELOG.md").splitlines() if x.startswith("## "))
        self.assertTrue(top.startswith("## v0.2.9"), top)

    def test_defaults_and_baseline(self):
        import baseline
        self.assertEqual(tc.DEFAULTS_VERSION, 5)
        self.assertEqual(tc.settings_snapshot(tc.validate_config({})[0])["label"], "default@5")
        self.assertEqual(baseline.load_defaults()["5"], tc.default_values())

    def test_metrics_in_core(self):
        self.assertIs(bt.curve_stats, tc.curve_stats)
        self.assertIs(bt.trade_stats, tc.trade_stats)
        self.assertEqual(bt.MIN_TRADES, tc.MIN_TRADES)
        self.assertEqual(tc.MIN_TRADES, 30)
        self.assertEqual(P.MAX_TABLE, 20)

    def test_skill_copies_in_sync(self):
        core = self.text("core", "tayyib_core.py")
        for d in ("tayyib-tracker", "tayyib-dashboard", "tayyib-email", "tayyib-daily", "tayyib-backtest"):
            self.assertEqual(self.text(d, "tayyib_core.py"), core, d)


if __name__ == "__main__":
    unittest.main()
