import os
import unittest

from _util import OfflineCase


class Daily(OfflineCase):
    def test_one_command_list(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py")
        syms = [r["symbol"] for r in out["rows"]]
        self.assertEqual(sorted(syms), ["ALFA", "CHRL"])              # halal + liquid + armed only
        for r in out["rows"]:
            self.assertTrue(r["entry"] > r["stop"])
            self.assertTrue(r["target"] > r["entry"])
            self.assertLessEqual(r["stop_pct"], 15.0)
            self.assertIn(r["risk"], ("PASS", "WARN", "BLOCK"))
            self.assertLessEqual(r["loss_at_stop_rs"], 1000.0)
            self.assertIsNotNone(r["expectancy_r"])
        alfa = [r for r in out["rows"] if r["symbol"] == "ALFA"][0]
        self.assertEqual(alfa["risk"], "WARN")
        self.assertIn("HALAL-WATCH", alfa["reasons"][0])                # halal warnings listed first
        self.assertEqual(out["rows"][0]["risk"], "PASS")                 # PASS sorted before WARN
        self.assertTrue(os.path.exists(os.path.join(self.dir, "daily", "2026-10-30.md")))
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertIn("| ALFA |", md)
        self.assertIn("Place it yourself", md)

    def test_only_todays_stocks_are_touched(self):
        self.build_universe()
        self.write("orders.json", {"orders": [{"id": "OLD-1", "symbol": "XYZ", "status": "PLACED"}]})
        self.run_script("tayyib-daily/daily.py", "--no-news")
        ids = [o["id"] for o in self.read("orders.json")["orders"]]
        self.assertIn("OLD-1", ids)

    def test_swing_only(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py", "--mode", "swing", "--no-news")
        self.assertTrue(out["rows"])
        self.assertTrue(all(r["mode"] == "swing" and r["stop_pct"] <= 10.0 for r in out["rows"]))

    def test_needs_universe(self):
        p = self.run_script("tayyib-daily/daily.py", ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("halal", p.stderr)

    def test_market_hours_note(self):
        self.build_universe()
        os.environ["TAYYIB_NOW"] = "2026-10-30 11:00"
        try:
            import subprocess, sys, json
            from _util import ROOT, FIX
            p = subprocess.run([sys.executable, os.path.join(ROOT, "tayyib-daily", "daily.py"), "--no-news", "--json"],
                               capture_output=True, text=True,
                               env=dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=FIX, TAYYIB_NOW="2026-10-30 11:00"))
            self.assertTrue(any("market is open" in n for n in json.loads(p.stdout)["notes"]))
        finally:
            os.environ["TAYYIB_NOW"] = "2026-10-30 18:00"


if __name__ == "__main__":
    unittest.main()


class DailyFixes(OfflineCase):
    def _placed_alfa(self):
        self.build_universe()
        self.run_script("tayyib-daily/daily.py", "--mode", "swing", "--no-news")
        o = self.read("orders.json")
        alfa = [x for x in o["orders"] if x["symbol"] == "ALFA"][0]
        alfa["status"] = "PLACED"
        self.write("orders.json", o)
        return alfa["id"]

    def test_statuses_match_a_plain_risk_check(self):
        self.build_universe()
        self.write("orders.json", {"orders": [
            {"id": "OLD-%d" % k, "symbol": "OLD%d" % k, "side": "BUY", "product": "CNC", "qty": 1,
             "trigger_price": 100, "stop": 95, "target": 110, "status": "PASS"} for k in range(3)]})
        out = self.run_script("tayyib-daily/daily.py", "--no-news")
        self.assertTrue(any("replaced 3 earlier unplaced" in n for n in out["notes"]))
        plain = {r["id"]: r["status"] for r in self.run_script("tayyib-risk/check.py")}
        for r in out["rows"]:
            self.assertEqual(r["risk"], plain[r["order_id"]], r["symbol"])

    def test_no_duplicate_ids_with_a_placed_order(self):
        placed_id = self._placed_alfa()
        self.run_script("tayyib-daily/daily.py", "--mode", "swing", "--no-news")
        ids = [x["id"] for x in self.read("orders.json")["orders"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(placed_id, ids)                                  # placed order kept, untouched

    def test_mode_all_mixes_swing_and_delivery(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py", "--no-news", "--top", "2")
        self.assertEqual(sorted(r["symbol"] for r in out["rows"]), ["ALFA", "CHRL"])
        self.assertEqual(sorted(r["mode"] for r in out["rows"]), ["delivery", "swing"])

    def test_negative_expectancy_warns(self):
        import sys
        from _util import ROOT, tc
        sys.path.insert(0, os.path.join(ROOT, "tayyib-risk"))
        import check
        o = {"id": "X", "symbol": "ALFA", "side": "BUY", "product": "CNC", "qty": 1, "trigger_price": 100,
             "stop": 95, "target": 112, "setup": "breakout", "loss_at_stop_rs": 6, "reward_risk_net": 1.9}
        sim = {"results": {"ALFA": {"plan": {"setup": "breakout"}, "monte_carlo": {"expectancy_r": -0.14}}}}
        self.build_universe()
        r = check.check_order(o, tc.load_config(), [], tc.load_universe(), {}, sim=sim)
        self.assertTrue(any("expectancy is negative" in w for w in r["warn"]))
