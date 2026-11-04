import os
import sys
import unittest
import zipfile

from _util import OfflineCase, ROOT, tc

sys.path.insert(0, os.path.join(ROOT, "tayyib-tracker"))
import tracker  # noqa: E402


def bar(d, o, h, l, c):
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1}


PLAN = {"date": "2026-10-01", "entry": 100.0, "stop": 95.0, "target": 110.0, "valid_until": "2026-10-06",
        "max_hold_days": 20, "mode": "swing", "qty": 10}
CFG = tc.DEFAULT_CONFIG
B0 = [bar("2026-10-01", 98, 99, 97, 98.5)]


class Outcome(unittest.TestCase):
    def o(self, bars, **kw):
        return tc.trade_outcome(B0 + bars, dict(PLAN, **kw), CFG, today="2026-11-04")

    def test_target(self):
        r = self.o([bar("2026-10-02", 99, 101, 98.5, 100.5), bar("2026-10-05", 101, 111, 100.5, 109)])
        self.assertEqual((r["status"], r["filled"], r["fill"], r["exit"], r["days"]), ("TARGET", "2026-10-02", 100.0, 110.0, 2))
        self.assertGreater(r["r"], 1.5)                   # 2R gross, less charges on a small position
        self.assertGreater(r["pnl_rs"], 0)

    def test_stop_and_gap(self):
        r = self.o([bar("2026-10-02", 99, 101, 98.5, 100.5), bar("2026-10-05", 99, 99.5, 94, 95)])
        self.assertEqual((r["status"], r["exit"]), ("STOP", 95.0))
        r = self.o([bar("2026-10-02", 99, 101, 98.5, 100.5), bar("2026-10-05", 92, 93, 91, 92)])
        self.assertEqual((r["status"], r["exit"]), ("STOP", 92.0))          # gap through the stop
        self.assertLess(r["r"], -1.0)

    def test_fill_day_stop_and_both_touched(self):
        r = self.o([bar("2026-10-02", 99, 101, 94, 96)])
        self.assertEqual(r["status"], "STOP")
        r = self.o([bar("2026-10-02", 99, 101, 98.5, 100.5), bar("2026-10-05", 100, 112, 94, 105)])
        self.assertEqual(r["status"], "STOP")                                 # both touched: stop

    def test_breakeven_swing_only(self):
        bars = [bar("2026-10-02", 99, 101, 98.5, 100.5), bar("2026-10-05", 101, 106, 101, 105),
                bar("2026-10-06", 104, 104, 99.5, 100)]
        self.assertEqual(self.o(bars)["status"], "BREAKEVEN")
        self.assertEqual(self.o(bars, mode="delivery")["status"], "OPEN")

    def test_waiting_not_triggered_open_time(self):
        self.assertEqual(tc.trade_outcome(B0 + [bar("2026-10-02", 98, 99, 97, 98)], PLAN, CFG,
                                          today="2026-10-02")["status"], "WAITING")
        flat = [bar("2026-10-0%d" % d, 98, 99, 97, 98) for d in (2, 5, 6, 7)]
        self.assertEqual(self.o(flat)["status"], "NOT TRIGGERED")
        r = self.o([bar("2026-10-02", 99, 101, 98.5, 100.5), bar("2026-10-05", 101, 103, 100, 102)])
        self.assertEqual(r["status"], "OPEN")
        days = [bar("2026-10-02", 99, 101, 98.5, 100.5)] + [bar("2026-10-%02d" % d, 100.5, 101, 99, 100.5)
                                                             for d in range(5, 9)]
        self.assertEqual(self.o(days, max_hold_days=3)["status"], "TIME EXIT")


class TrackerFlow(OfflineCase):
    def test_daily_records_and_exports(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py", "--no-news")
        self.assertTrue(out["tracker"])
        t = self.read("tracker.json")["rows"]
        self.assertEqual(sorted(r["symbol"] for r in t), sorted(r["symbol"] for r in out["rows"]))
        self.assertTrue(all(r["status"] == "WAITING" for r in t))         # no bars after today yet
        x = os.path.join(self.dir, "tracker.xlsx")
        with zipfile.ZipFile(x) as z:
            self.assertIsNone(z.testzip())
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("ALFA", sheet)
            self.assertIn("Buy above", sheet)
            self.assertIn("Summary", z.read("xl/workbook.xml").decode())
        csvt = open(os.path.join(self.dir, "tracker.csv"), encoding="utf-8-sig").read()
        self.assertTrue(csvt.startswith("List date,Stock"))
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertIn("How earlier lists did", md)
        self.run_script("tayyib-daily/daily.py", "--no-news")             # same day again: no duplicates
        self.assertEqual(len(self.read("tracker.json")["rows"]), len(t))

    def test_earlier_rows_followed_on_real_bars(self):
        bars, _ = tc.get_daily_bars("ALFA")
        k = len(bars) - 30
        d0, d1 = bars[k]["date"], bars[k + 1]["date"]
        rows = [
            {"date": d0, "symbol": "ALFA", "name": "", "mode": "swing", "setup": "breakout", "check": "PASS",
             "entry": bars[k + 1]["low"], "stop": bars[k + 1]["low"] * 0.5, "target": bars[k + 1]["low"] * 1.0001,
             "qty": 5, "valid_until": bars[k + 3]["date"], "max_hold_days": 20, "status": "WAITING"},
            {"date": d0, "symbol": "ALFA", "name": "", "mode": "swing", "setup": "pullback", "check": "BLOCK",
             "entry": 999999.0, "stop": 1.0, "target": 9999999.0, "qty": 5, "valid_until": d1,
             "max_hold_days": 20, "status": "WAITING"},
        ]
        self.write("tracker.json", {"rows": rows})
        self.run_script("tayyib-tracker/tracker.py", "update")
        got = {r["setup"]: r for r in self.read("tracker.json")["rows"]}
        self.assertEqual(got["breakout"]["status"], "TARGET")
        self.assertEqual(got["breakout"]["filled"], d1)
        self.assertEqual(got["pullback"]["status"], "NOT TRIGGERED")
        rep = self.run_script("tayyib-tracker/tracker.py", "report")
        self.assertEqual(rep["summary"]["all"]["target"], 1)
        self.assertEqual(rep["summary"]["check: PASS"]["closed"], 1)
        self.run_script("tayyib-tracker/tracker.py", "export")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "tracker.xlsx")))


if __name__ == "__main__":
    unittest.main()
