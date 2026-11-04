"""Regression tests for the bugs found in the first live run (Windows, Nov 2026)."""
import json
import os
import sys
import unittest

from _util import OfflineCase, ROOT, tc

sys.path.insert(0, os.path.join(ROOT, "tayyib-results"))
sys.path.insert(0, os.path.join(ROOT, "tayyib-news"))
import results  # noqa: E402
import news     # noqa: E402


class Plurals(unittest.TestCase):          # bug 1
    def test_plural_names_caught(self):
        self.assertEqual(tc.business_screen("ABDL", "Allied Blenders and Distillers Ltd.", "Fast Moving Consumer Goods")[0], "excluded")
        self.assertEqual(tc.business_screen("XYZ", "Xyz Spirits Ltd.", "Beverages")[0], "excluded")
        self.assertEqual(tc.business_screen("INDHOTEL", "The Indian Hotels Company Ltd.", "Consumer Services")[0], "review")
        self.assertEqual(tc.business_screen("LEMONTREE", "Lemon Tree Hotels Ltd.", "Consumer Services")[0], "review")
        self.assertEqual(tc.business_screen("TCS", "Tata Consultancy Services Ltd.", "Information Technology")[0], "pass")


class GrowthByDate(unittest.TestCase):     # bug 2
    def test_missing_quarter_gives_no_growth(self):
        q = {"TotalRevenue": [("2025-06-30", 100.0), ("2025-12-31", 110.0), ("2026-03-31", 120.0),
                              ("2026-06-30", 130.0), ("2026-09-30", 140.0)]}       # 2025-09 missing
        rows = {r["quarter"]: r for r in results.quarter_table(q, 10)}
        self.assertIsNone(rows["2025-12-31"]["TotalRevenue_qoq"])                   # previous quarter missing
        self.assertAlmostEqual(rows["2026-03-31"]["TotalRevenue_qoq"], 9.1)
        self.assertIsNone(rows["2026-09-30"]["TotalRevenue_yoy"])                  # 2025-09 missing
        self.assertAlmostEqual(rows["2026-06-30"]["TotalRevenue_yoy"], 30.0)


class InsiderUnknown(OfflineCase):         # bug 3
    def test_failed_source_is_unknown_not_zero(self):
        out = self.run_script("tayyib-insider/insider.py", "CHRL")["symbols"]["CHRL"]   # no NSE fixtures for CHRL
        self.assertIsNone(out["pit"])
        self.assertIsNone(out["promoter_net_rs"])
        self.assertIsNone(out["deals"])
        txt = self.run_script("tayyib-insider/insider.py", "CHRL", as_json=False)
        self.assertIn("UNKNOWN", txt)


class BOM(OfflineCase):                    # bug 4
    def test_config_with_bom(self):
        with open(os.path.join(self.dir, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"capital": 250000}, f)
        self.assertEqual(tc.load_config()["capital"], 250000)
        self.build_universe()                                        # a script still runs


class RiskMissingFields(OfflineCase):      # bug 5
    def test_missing_trigger_blocks(self):
        self.build_universe()
        self.write("orders.json", {"orders": [{"id": "X-1", "symbol": "ALFA", "side": "BUY",
                                               "product": "CNC", "qty": 3, "stop": 90, "target": 120,
                                               "status": "SIZED"}]})
        r = self.run_script("tayyib-risk/check.py")[0]
        self.assertEqual(r["status"], "BLOCK")
        self.assertIn("trigger_price", r["block"][0])


class Placeholder(unittest.TestCase):      # bug 6
    def test_dummy_rows_dropped(self):
        rows = tc.read_index_csv("Company Name,Industry,Symbol,Series,ISIN Code\n"
                                 "Dummy Hegde,Textiles,DUMMYHEG,EQ,INE000X\nReal Ltd.,Chemicals,REAL,EQ,INE1\n")
        self.assertEqual([r["symbol"] for r in rows], ["REAL"])


class NewsRelevance(unittest.TestCase):    # bug 7
    def test_other_mahindra_company_does_not_match(self):
        it = {"title": "Kotak Mahindra Bank shares rise 3%", "summary": ""}
        self.assertFalse(news.mentions(it, "TECHM", "Tech Mahindra Ltd."))
        self.assertTrue(news.mentions({"title": "Tech Mahindra wins deal", "summary": ""}, "TECHM", "Tech Mahindra Ltd."))
        self.assertTrue(news.mentions({"title": "TECHM shares jump", "summary": ""}, "TECHM", "Tech Mahindra Ltd."))

    def test_pick_lists_not_results(self):
        tags, watch = news.tag("Stocks to buy today: 5 picks after strong quarterly earnings")
        self.assertEqual(tags, ["pick-list"])
        self.assertIn("results", news.tag("Tech Mahindra Q2 results: net profit up 10%")[0])
        self.assertNotIn("results", news.tag("Profit booking drags Nifty lower")[0])


class TrendStop(OfflineCase):              # bug 8
    def test_trend_invalidation_is_a_recent_low(self):
        for sym in ("ALFA", "CHRL"):
            bars, _ = tc.get_daily_bars(sym)
            sig = tc.detect_all(bars, "delivery")[0]
            low20 = min(b["low"] for b in bars[-20:])
            self.assertGreaterEqual(sig["invalidation"], round(low20, 2) - 0.05)


class DuplicateSetups(OfflineCase):        # bug 9
    def test_other_setups_reported(self):
        self.build_universe()
        self.run_script("tayyib-scanner/scan.py")
        ev = self.run_script("tayyib-entry/entry.py", "check", "ALFA")[0]
        self.assertTrue(ev["other_setups"])
        txt = self.run_script("tayyib-exit/exit.py", "plan", "ALFA", as_json=False)
        self.assertIn("also armed as", txt)


if __name__ == "__main__":
    unittest.main()


class Compare(OfflineCase):
    def test_compare_buckets(self):
        self.build_universe()
        p = os.path.join(self.dir, "trusted.csv")
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("Symbol,Status\nALFA,Compliant\nCHRL,Non-Compliant\nGOLF,Compliant\nNEWCO,Compliant\n")
        out = self.run_script("tayyib-halal/halal.py", "compare", p)
        self.assertEqual(out["agree"], 1)                                                # ALFA
        self.assertEqual([r["symbol"] for r in out["we_say_compliant_they_do_not"]], ["CHRL"])
        self.assertEqual([r["symbol"] for r in out["they_say_compliant_we_block"]], ["GOLF"])
        self.assertEqual([r["symbol"] for r in out["not_in_our_universe"]], ["NEWCO"])
