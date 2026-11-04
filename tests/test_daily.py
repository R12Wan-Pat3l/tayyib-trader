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
        self.assertTrue(alfa["reasons"][0].startswith("WARN: HALAL-WATCH"))   # labelled, halal first
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

    def test_needs_universe_when_rebuild_is_off(self):
        p = self.run_script("tayyib-daily/daily.py", "--no-rebuild", ok=False)
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
        self.assertTrue(any("removed 3 earlier unplaced" in n for n in out["notes"]))
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


class DailyFixes2(OfflineCase):
    def test_check_symbol_counts_other_tickets(self):
        self.build_universe()
        self.write("config.json", {"max_open_positions": 1})
        self.run_script("tayyib-daily/daily.py", "--no-news")
        full = {r["symbol"]: r["status"] for r in self.run_script("tayyib-risk/check.py")}
        self.assertEqual(sorted(full.values()).count("BLOCK"), 1)
        blocked = [s for s, st in full.items() if st == "BLOCK"][0]
        one = self.run_script("tayyib-risk/check.py", blocked)
        self.assertEqual([r["symbol"] for r in one], [blocked])          # only the requested one reported
        self.assertEqual(one[0]["status"], "BLOCK")                       # still counts the other ticket
        saved = {o["symbol"]: o["status"] for o in self.read("orders.json")["orders"]}
        self.assertEqual(saved, full)

    def test_held_stock_skipped_and_second_ticket_blocked(self):
        self.build_universe()
        self.run_script("tayyib-daily/daily.py", "--mode", "swing", "--no-news")
        o = self.read("orders.json")
        alfa = [x for x in o["orders"] if x["symbol"] == "ALFA"][0]
        alfa["status"] = "PLACED"
        self.write("orders.json", o)
        out = self.run_script("tayyib-daily/daily.py", "--mode", "swing", "--no-news")
        self.assertNotIn("ALFA", [r["symbol"] for r in out["rows"]])
        self.assertTrue(any("skipped ALFA" in n for n in out["notes"]))
        # a manual second ticket for the same signal is BLOCKed by the risk check
        o = self.read("orders.json")
        dup = dict(alfa, id=alfa["id"] + "-2", status="SIZED")
        o["orders"].append(dup)
        self.write("orders.json", o)
        r = [x for x in self.run_script("tayyib-risk/check.py") if x["id"] == dup["id"]][0]
        self.assertEqual(r["status"], "BLOCK")
        self.assertTrue(any("already placed" in b for b in r["block"]))

    def test_removed_vs_replaced_notes(self):
        self.build_universe()
        self.run_script("tayyib-daily/daily.py", "--no-news")                   # all modes: ALFA swing, CHRL delivery
        self.write("orders.json", {"orders": self.read("orders.json")["orders"] + [
            {"id": "GONE-1", "symbol": "GONE", "side": "BUY", "product": "CNC", "qty": 1, "trigger_price": 10,
             "stop": 9, "target": 12, "status": "PASS"}]})
        out = self.run_script("tayyib-daily/daily.py", "--mode", "delivery", "--no-news")
        n = " | ".join(out["notes"])
        self.assertIn("removed", n)
        self.assertIn("GONE-1", n)
        self.assertIn("replaced ALFA-", n)                                  # swing ticket swapped for delivery


class DailyAuto(OfflineCase):
    def test_first_run_builds_the_halal_list(self):
        out = self.run_script("tayyib-daily/daily.py", "--no-news")
        self.assertTrue(any("rebuilt the halal list (first run)" in n for n in out["notes"]))
        self.assertTrue(out["rows"])

    def test_rebuilds_when_a_month_old(self):
        self.build_universe()
        u = self.read("halal_universe.json")
        u["updated"] = "2026-09-20"                                   # 40 days before the pinned date
        self.write("halal_universe.json", u)
        out = self.run_script("tayyib-daily/daily.py", "--no-news")
        self.assertTrue(any("list was 40 days old" in n for n in out["notes"]))
        self.assertEqual(self.read("halal_universe.json")["updated"], "2026-10-30")
        u["updated"] = "2026-09-20"
        self.write("halal_universe.json", u)
        out = self.run_script("tayyib-daily/daily.py", "--no-news", "--no-rebuild")
        self.assertFalse(any("rebuilt" in n for n in out["notes"]))

    def test_top_picks(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py", "--no-news")
        passed = [r["symbol"] for r in out["rows"] if r["risk"] == "PASS"]
        self.assertEqual(out["top_picks"], passed[:3])
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertIn("Today's top picks", md)
