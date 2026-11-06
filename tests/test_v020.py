"""v0.2.0: tayyib-backtest. Offline: the fixture charts plus small synthetic charts built here."""
import copy
import datetime as dt
import glob
import json
import os
import re
import sys
import unittest

from _util import FIX, OfflineCase, ROOT, tc

sys.path.insert(0, os.path.join(ROOT, "tayyib-backtest"))
import backtest as bt  # noqa: E402

for d in ("tayyib-budget", "tayyib-timemachine", "tayyib-daily"):
    sys.path.insert(0, os.path.join(ROOT, d))
import size as size_mod  # noqa: E402
import timemachine as tm_mod  # noqa: E402
import daily as daily_mod  # noqa: E402

CFG = tc.validate_config({})[0]
SYMS = ("ALFA", "BRVO", "CHRL", "DLTA", "ECHO", "THIN")


def weekdays(start, n):
    d, out = tc.parse_date(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def flat(n, start="2026-01-01", price=100.0, vol=1_000_000):
    return [{"date": d, "open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": vol}
            for d in weekdays(start, n)]


def plan_for(sym, date, entry, stop, target, valid_until, mode="swing", hold=20):
    return {"symbol": sym, "mode": mode, "setup": "breakout" if mode == "swing" else "trend", "signal_date": date,
            "date": date, "entry": entry, "stop": stop, "target": target, "valid_until": valid_until,
            "max_hold_days": hold, "risk_per_share": round(entry - stop, 2)}


class FakeScan:
    """Stands in for bt.scan_day: the picks given for each date (held stocks dropped, like the real one), so the
    account rules are tested on their own."""

    def __init__(self, by_date):
        self.by_date = by_date

    def __call__(self, books, date, cfg, mode, setups, held):
        out = []
        for pl, score in self.by_date.get(date, []):
            if pl["symbol"] in held:
                continue
            i = books[pl["symbol"]].idx[date]
            out.append({"symbol": pl["symbol"], "setup": pl["setup"], "mode": pl["mode"], "score": score,
                        "sig": {"date": date}, "plan": copy.deepcopy(pl), "i": i})
        return out


class Patched(unittest.TestCase):
    def setUp(self):
        self._scan = bt.scan_day

    def tearDown(self):
        bt.scan_day = self._scan

    def sim(self, data, by_date, start, end, max_positions=5, cfg=CFG, uni=None, take_warn=True):
        bt.scan_day = FakeScan(by_date)
        uni = uni or {"stocks": {s: {"status": "compliant", "industry": "industry %s" % s} for s in data}}
        return bt.simulate(data, cfg, start, end, "all", None, max_positions, uni=uni, take_warn=take_warn)


def fixture_bars():
    return {s: tc.get_daily_bars(s)[0] for s in SYMS}


class SameFunctionsAsLive(unittest.TestCase):
    """The refactor into core changed nothing: the old names are the core functions."""

    def test_aliases(self):
        self.assertIs(size_mod.size, tc.size_trade)
        self.assertIs(tm_mod.history, tc.tm_history)
        self.assertIs(tm_mod.monte_carlo, tc.tm_monte_carlo)
        self.assertIs(tm_mod.walk, tc.tm_walk)
        self.assertIs(daily_mod.choose, tc.choose_candidates)

    def test_detect_at_equals_detect_all_on_history(self):
        for s, bars in fixture_bars().items():
            ind = tc.indicators(bars)
            for i in range(200, len(bars), 3):
                self.assertEqual(tc.detect_at(bars, ind, i, "all", None, 0.05, CFG),
                                 tc.detect_all(bars[:i + 1], "all", cfg=CFG), (s, i))

    def test_index_symbol(self):
        self.assertEqual(tc.yahoo_symbol("^NSEI"), "^NSEI")
        self.assertEqual(tc.yahoo_symbol("SHARIABEES.NS"), "SHARIABEES.NS")
        self.assertEqual(tc.yahoo_symbol("TCS"), "TCS.NS")


class NoLookAhead(unittest.TestCase):
    def test_signals_and_plans_ignore_later_bars(self):
        data = fixture_bars()
        books = {s: bt.Book(b) for s, b in data.items()}
        seen = 0
        dates = data["ALFA"][210:]
        for k, b in enumerate(dates[::5]):
            t = b["date"]
            changed = {}
            for s, bars in data.items():
                nb = []
                for x in bars:
                    if x["date"] > t:   # every later bar different: prices up 40%, volume x3
                        x = dict(x, open=x["open"] * 1.4, high=x["high"] * 1.5, low=x["low"] * 1.3,
                                 close=x["close"] * 1.4, volume=x["volume"] * 3)
                    nb.append(x)
                changed[s] = nb
            books2 = {s: bt.Book(b) for s, b in changed.items()}
            a = bt.scan_day(books, t, CFG, "all", None, set())
            c = bt.scan_day(books2, t, CFG, "all", None, set())
            strip = lambda ps: [{k: v for k, v in p.items()} for p in ps]
            self.assertEqual(strip(a), strip(c), t)
            if a:
                seen += 1
                ra = bt.rank_day(books, copy.deepcopy(a), CFG, all_mc=True)     # the full time machine
                rc = bt.rank_day(books2, copy.deepcopy(c), CFG, all_mc=True)
                self.assertEqual(ra, rc, t)
        self.assertGreater(seen, 3, "the fixtures should arm setups on several of these days")


class OneTrade(Patched):
    def test_matches_trade_outcome(self):
        bars = flat(30)
        d = [b["date"] for b in bars]
        bars[11].update(open=100, high=102, low=99.5, close=101.8)       # fills at 101
        for k in range(12, 30):
            bars[k].update(open=102, high=103, low=101.5, close=102.5)
        bars[15].update(open=103, high=114, low=102, close=113)          # target 113
        pl = plan_for("AAA", d[10], 101.0, 95.0, 113.0, d[13])
        res = self.sim({"AAA": bars}, {d[10]: [(pl, 60)]}, d[5], d[-1])
        self.assertEqual(len(res["trades"]), 1)
        t = res["trades"][0]
        qty = tc.size_trade(pl, CFG, CFG["capital"])["qty"]
        o = tc.trade_outcome(bars, dict(pl, qty=qty), CFG, today=d[-1])
        self.assertEqual((t["entry_date"], t["entry_price"], t["exit_date"], t["exit_price"], t["exit_reason"]),
                         (o["filled"], o["fill"], o["exited"], o["exit"], o["status"]))
        self.assertEqual((t["r"], t["pnl_rs"], t["qty"]), (o["r"], o["pnl_rs"], qty))
        self.assertAlmostEqual(t["charges"], tc.round_trip(o["fill"], o["exit"], qty, CFG), places=2)
        self.assertEqual(t["exit_reason"], "TARGET")
        final = res["curve"][-1]["equity"]
        self.assertAlmostEqual(final, CFG["capital"] + t["pnl_rs"], places=2)

    def test_gap_through_stop_fills_at_open(self):
        bars = flat(30)
        d = [b["date"] for b in bars]
        bars[11].update(open=100, high=102, low=99.5, close=101.5)
        bars[12].update(open=93, high=94, low=92, close=93.5)             # opens under the 95 stop
        pl = plan_for("AAA", d[10], 101.0, 95.0, 113.0, d[13])
        t = self.sim({"AAA": bars}, {d[10]: [(pl, 60)]}, d[5], d[-1])["trades"][0]
        self.assertEqual((t["exit_reason"], t["exit_price"], t["exit_date"]), ("STOP", 93.0, d[12]))
        self.assertLess(t["r"], -1)

    def test_stop_and_target_same_day_is_the_stop(self):
        bars = flat(30)
        d = [b["date"] for b in bars]
        bars[11].update(open=100, high=102, low=99.5, close=101.5)
        bars[12].update(open=101, high=114, low=94, close=110)            # touches 95 and 113
        pl = plan_for("AAA", d[10], 101.0, 95.0, 113.0, d[13])
        t = self.sim({"AAA": bars}, {d[10]: [(pl, 60)]}, d[5], d[-1])["trades"][0]
        self.assertEqual((t["exit_reason"], t["exit_price"]), ("STOP", 95.0))


class Account(Patched):
    def test_cash_slots_one_per_symbol_and_expiry(self):
        n = 60
        syms = ["S%02d" % k for k in range(8)]
        data = {}
        for k, s in enumerate(syms):
            bars = flat(n, price=100.0)
            for j in range(11, n):                                       # drifts up slowly: fills, rarely exits
                p = 100 + (j - 10) * 0.2
                bars[j].update(open=p, high=p + 1.2, low=p - 0.3, close=p + 0.1)
            data[s] = bars
        data["NEVER"] = flat(n, price=50.0)                               # never reaches its entry
        d = [b["date"] for b in data["S00"]]
        cfg = copy.deepcopy(CFG)
        cfg["max_position_pct"] = 40.0                                    # big positions: cash runs out first
        by_date = {}
        for j in range(10, n - 2):
            day = []
            for s in syms:
                p = data[s][j]["close"]
                day.append((plan_for(s, d[j], round(p + 0.5, 2), round(p - 1.5, 2), round(p + 30, 2),
                                     d[min(j + 3, n - 1)]), 50 + j % 7))
            day.append((plan_for("NEVER", d[j], 60.0, 55.0, 70.0, d[min(j + 3, n - 1)]), 99))
            by_date[d[j]] = day
        res = self.sim(data, by_date, d[5], d[-1], max_positions=3, cfg=cfg)
        for c in res["curve"]:
            self.assertGreaterEqual(c["cash"], 0, c)
            self.assertLessEqual(c["open_positions"] + c["waiting_plans"], 3, c)
        self.assertTrue(res["trades"])
        by_sym = {}
        for t in res["trades"]:
            by_sym.setdefault(t["symbol"], []).append((t["entry_date"], t["exit_date"]))
        for s, spans in by_sym.items():
            spans.sort()
            for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                self.assertLess(a1, b0, "two positions in %s at once" % s)
        self.assertNotIn("NEVER", by_sym)
        self.assertGreater(res["counts"]["not_triggered"], 0)            # NEVER's plans expired...
        self.assertGreater(res["counts"]["plans"], res["counts"]["not_triggered"])   # ...and freed their slot

    def test_expired_plan_frees_its_slot(self):
        bars_a, bars_b = flat(30), flat(30)
        d = [b["date"] for b in bars_a]
        for k in range(20, 30):
            bars_b[k].update(high=103)
        pa = plan_for("AAA", d[10], 110.0, 105.0, 120.0, d[13])           # never trades up to 110
        pb = plan_for("BBB", d[14], 102.0, 98.0, 120.0, d[25])
        res = self.sim({"AAA": bars_a, "BBB": bars_b}, {d[10]: [(pa, 60)], d[12]: [(pb, 60)], d[14]: [(pb, 60)]},
                       d[5], d[-1], max_positions=1)
        self.assertEqual([t["symbol"] for t in res["trades"]], ["BBB"])
        self.assertEqual(res["trades"][0]["signal_date"], d[14])           # d[12]: the slot was still AAA's
        self.assertEqual(res["counts"]["not_triggered"], 1)


class Universe(OfflineCase):
    def test_only_compliant_and_overrides_win(self):
        uni = {"stocks": {"AAA": {"status": "compliant"}, "BBB": {"status": "review"},
                          "CCC": {"status": "excluded"}, "DDD": {"status": "compliant"},
                          "EEE": {"status": "unknown"}, "ITC": {"status": "compliant"}}}
        self.write("halal_overrides.json", {"DDD": {"status": "excluded", "note": "my scholar"},
                                            "BBB": {"status": "compliant", "note": "annual report checked"}})
        syms, counts = bt.halal_universe(uni)
        self.assertEqual(syms, ["AAA", "BBB"])
        self.assertEqual(counts["compliant"], 2)                          # ITC: known excluded, whatever the list says
        self.assertEqual(counts.get("review", 0), 0)

    def test_trades_only_compliant_stocks(self):
        self.build_universe()
        res = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1")
        uni = self.read("halal_universe.json")
        for t in res["trades"]:
            self.assertEqual(tc.halal_status(t["symbol"], uni)["status"], "compliant", t["symbol"])
        self.assertEqual(res["universe"]["compliant"], len(bt.halal_universe(uni)[0]))
        self.assertTrue(res["trades"])

    def test_missing_data_is_skipped(self):
        data, skipped, _ = bt.load_bars(["ALFA", "NODATA"], "2y", "2025-10-30", "2026-10-30", sleep=0)
        self.assertIn("ALFA", data)
        self.assertEqual([x["symbol"] for x in skipped], ["NODATA"])
        self.assertIn("no price data", skipped[0]["reason"])
        data, skipped, _ = bt.load_bars(["ALFA"], "2y", "2024-01-30", "2024-11-30", sleep=0)   # v0.2.1: never
        self.assertEqual(data, {})                                                             # reaches 250 bars
        self.assertIn("needs 250 to join", skipped[0]["reason"])


class Output(OfflineCase):
    def test_deterministic_json_and_files(self):
        self.build_universe()
        p1 = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", as_json=False)
        p2 = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", as_json=False)
        self.assertEqual(p1, p2)
        self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", "--write", as_json=False)
        f = glob.glob(os.path.join(self.dir, "backtest", "*.json"))
        self.assertEqual(len(f), 1)
        b1 = open(f[0], "rb").read()
        self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", "--write", as_json=False)
        self.assertEqual(open(f[0], "rb").read(), b1)
        res = json.loads(b1)
        for k in ("params", "settings", "window", "universe", "skipped", "trades", "equity_curve", "metrics",
                  "split", "benchmarks", "banners"):
            self.assertIn(k, res)
        self.assertEqual(res["settings"]["label"], "default@%d" % tc.DEFAULTS_VERSION)
        for k in ("symbol", "setup", "mode", "signal_date", "entry_date", "entry_price", "exit_date", "exit_price",
                  "exit_reason", "qty", "charges", "pnl_rs", "r"):
            self.assertIn(k, res["trades"][0])
        for k in ("trades", "win_rate_pct", "avg_r", "expectancy_r", "profit_factor", "total_return_pct", "cagr_pct",
                  "max_drawdown_pct", "drawdown_peak", "drawdown_trough", "longest_losing_streak", "exposure_pct",
                  "total_charges_rs"):
            self.assertIn(k, res["metrics"]["overall"])
        self.assertIn("in_sample", res["split"])
        lst = self.run_script("tayyib-backtest/backtest.py", "list")
        self.assertEqual([x["id"] for x in lst], [res["id"]])
        shown = self.run_script("tayyib-backtest/backtest.py", "show", res["id"])
        self.assertEqual(shown, res)
        self.assertTrue(os.path.exists(f[0][:-5] + ".md"))

    def test_benchmark_failure_is_unknown(self):
        self.build_universe()
        res = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1")
        for sym in ("SHARIABEES.NS", "^NSEI"):
            b = res["benchmarks"][sym]
            self.assertEqual(b["status"], "UNKNOWN")
            self.assertTrue(b["reason"])
            self.assertNotIn("total_return_pct", b)                     # never a made-up 0
        self.assertIn(bt.BANNER_NO_ETF, res["banners"])

    def test_benchmark_buy_and_hold(self):
        bars = flat(10, start="2026-01-01", price=100.0)
        bars[-1]["close"] = 110.0
        b = bt.benchmark("SHARIABEES.NS", "x", "5y", bars[0]["date"], bars[-1]["date"], 100000, CFG,
                         fetch=lambda s, range_: (bars, {}))
        self.assertEqual(b["status"], "OK")
        self.assertTrue(9.5 < b["total_return_pct"] < 10)                # 10% less one buy and one sell charge


class Banners(unittest.TestCase):
    def m(self, trades=40, cagr=10.0):
        return {"trades": trades, "cagr_pct": cagr}

    def split(self, i, o):
        return {"in_sample": {"expectancy_r": i}, "out_of_sample": {"expectancy_r": o}}

    ETF = {"SHARIABEES.NS": {"status": "OK", "cagr_pct": 12.0}}

    def test_always(self):
        b = bt.banners(self.m(), self.split(0.3, 0.3), {"SHARIABEES.NS": {"status": "OK", "cagr_pct": 5.0}})
        self.assertEqual(b, [bt.BANNER_HALAL, bt.BANNER_SURVIVOR, bt.BANNER_PAST, bt.BANNER_NEWS])   # v0.2.1: + news

    def test_few_trades(self):
        etf = {"SHARIABEES.NS": {"status": "OK", "cagr_pct": 5.0}}
        self.assertIn(bt.BANNER_FEW, bt.banners(self.m(29), self.split(0.3, 0.3), etf))
        self.assertNotIn(bt.BANNER_FEW, bt.banners(self.m(30), self.split(0.3, 0.3), etf))

    def test_overfit(self):
        self.assertTrue(bt.overfit(0.4, 0.19))
        self.assertFalse(bt.overfit(0.4, 0.2))
        self.assertTrue(bt.overfit(0.4, -0.1))                            # opposite sign
        self.assertFalse(bt.overfit(-0.2, 0.3))                           # better out of sample: not "weaker"
        self.assertFalse(bt.overfit(None, 0.1))
        self.assertIn(bt.BANNER_OVERFIT, bt.banners(self.m(), self.split(0.4, 0.1), self.ETF))

    def test_etf(self):
        self.assertIn(bt.BANNER_ETF, bt.banners(self.m(cagr=11.9), self.split(0.3, 0.3), self.ETF))
        self.assertNotIn(bt.BANNER_ETF, bt.banners(self.m(cagr=12.0), self.split(0.3, 0.3), self.ETF))
        b = bt.banners(self.m(), self.split(0.3, 0.3), {"SHARIABEES.NS": {"status": "UNKNOWN"}})
        self.assertIn(bt.BANNER_NO_ETF, b)
        self.assertNotIn(bt.BANNER_ETF, b)


class Safety(OfflineCase):
    def test_no_broker_import_and_no_order_words(self):
        src = open(os.path.join(ROOT, "tayyib-backtest", "backtest.py"), encoding="utf-8").read()
        self.assertNotRegex(src, r"tayyib-broker|import ticket|from ticket")
        for name in ("orders.json", "positions.json", "tracker", "plan.json", "config.json", "daily"):
            self.assertNotRegex(src, r"write_json\([^)]*%s" % re.escape(name))

    def test_writes_only_backtest_folder(self):
        self.build_universe()
        self.write("config.json", {"capital": 200000})
        before = {}
        for root, _, files in os.walk(self.dir):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    before[p] = fh.read()
        self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", "--write", as_json=False)
        after = {}
        for root, _, files in os.walk(self.dir):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    after[p] = fh.read()
        for p, b in before.items():
            self.assertEqual(after.get(p), b, p)
        new = [os.path.relpath(p, self.dir) for p in after if p not in before]
        self.assertTrue(new)
        for p in new:
            self.assertTrue(p.startswith("backtest" + os.sep) or p.startswith("cache" + os.sep), p)

    def test_mcp_tools_read_only(self):
        sys.path.insert(0, os.path.join(ROOT, "mcp"))
        import server
        run_args = server.TOOLS["backtest_run"][3]({"mode": "all", "years": 3, "max_positions": 4, "split": "2025-01-01"})
        self.assertNotIn("--write", run_args)
        self.assertEqual(run_args[:1], ["run"])
        self.assertIn("--max-positions", run_args)
        self.assertEqual(server.TOOLS["backtest_list"][3]({}), ["list"])
        self.assertEqual(server.TOOLS["backtest_list"][3]({"id": "x"}), ["show", "x"])
        for name in ("backtest_run", "backtest_list"):
            self.assertNotIn("write", json.dumps(server.TOOLS[name][1]))


class Version(unittest.TestCase):
    def test_version_and_defaults(self):
        self.assertGreaterEqual(tc.DEFAULTS_VERSION, 2)   # pinned exactly by the newest test file (v0.2.5: 3)              # no default changed: still default@2


if __name__ == "__main__":
    unittest.main()
