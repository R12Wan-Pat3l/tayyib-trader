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


class SecondRun(OfflineCase):
    def test_html_unescaped(self):
        it = tc.parse_feed(b"<rss><channel><item><title>Indian Metals &amp;amp; Ferro Alloys</title></item></channel></rss>")[0]
        self.assertEqual(it["title"], "Indian Metals & Ferro Alloys")

    def test_pick_list_no_false_halal_watch(self):
        self.assertEqual(news.tag("Dhamaka stocks: 5 promising picks for Diwali"), (["pick-list"], []))
        # watch words in another company's summary no longer count: tags come from the title
        self.assertEqual(news.tag("Eternal shares rise 2%")[1], [])

    def test_scan_stop_matches_plan(self):
        self.build_universe()
        for c in self.run_script("tayyib-scanner/scan.py")["candidates"]:
            self.assertGreaterEqual(c["plan_stop"], c["invalidation"] - 0.01)
            if c["mode"] == "delivery":
                self.assertLessEqual(c["stop_pct"], 15.1)

    def test_mode_flag(self):
        self.build_universe()
        self.run_script("tayyib-scanner/scan.py")
        self.assertEqual(self.run_script("tayyib-entry/entry.py", "check", "ALFA", "--mode", "swing")[0]["mode"], "swing")
        self.assertEqual(self.run_script("tayyib-exit/exit.py", "plan", "ALFA", "--mode", "swing")[0]["mode"], "swing")
        self.run_script("tayyib-scanner/scan.py", "--mode", "swing")          # default follows the scan
        self.assertEqual(self.run_script("tayyib-exit/exit.py", "plan", "ALFA")[0]["mode"], "swing")

    def test_accept_income_reviews(self):
        self.build_universe()
        self.run_script("tayyib-halal/halal.py", "override", "BRVO", "--status", "review", as_json=False)
        u = self.read("halal_universe.json")
        u["stocks"]["CHRL"]["status"] = "review"
        u["stocks"]["CHRL"]["reasons"] = ["non-compliant income is 4.00%", "only the income test failed, by under 2x the limit"]
        self.write("halal_universe.json", u)
        p = os.path.join(self.dir, "t.csv")
        with open(p, "w") as f:
            f.write("Symbol\nCHRL\nDLTA\n")
        self.run_script("tayyib-halal/halal.py", "compare", p, "--accept-income-reviews", as_json=False)
        ov = self.read("halal_overrides.json")
        self.assertEqual(ov["CHRL"]["status"], "compliant")
        self.assertNotIn("DLTA", ov)                     # debt failure is never auto-accepted
        self.assertEqual(ov["BRVO"]["status"], "review")


class Dedupe(OfflineCase):
    def test_same_headline_from_two_feeds_once(self):
        self.assertEqual(
            news.re.sub(r"[^a-z0-9]+", " ", news.re.sub(r"\s+-\s+[^-]+$", "", "Coforge shares rise - MarketsMojo".lower())).strip(),
            news.re.sub(r"[^a-z0-9]+", " ", news.re.sub(r"\s+-\s+[^-]+$", "", "Coforge Shares Rise! - Mojo".lower())).strip())


class ThirdRun(unittest.TestCase):
    def test_single_company_multibagger_keeps_flags(self):
        tags, watch = news.tag("What drives Welspun Living's multibagger rally? Board approves QIP")
        self.assertNotIn("pick-list", tags)
        self.assertIn("new debt", watch)
        self.assertEqual(news.tag("5 multibagger stocks to bet on this Diwali")[0], ["pick-list"])

    def test_swing_stop_capped_at_10pct(self):
        sig = {"setup": "breakout", "mode": "swing", "date": "2026-10-30", "trigger": 100.0,
               "invalidation": 85.0, "atr": 6.0, "valid_days": 3}         # 15% structure, within 3 ATR
        p = tc.plan_trade(sig, tc.DEFAULT_CONFIG)
        self.assertEqual(p["stop"], 90.0)
        self.assertIn("10% max swing stop", p["stop_method"])
        cfg = tc.deep_merge(tc.DEFAULT_CONFIG, {"modes": {"swing": {"max_stop_pct": 20.0}}})
        self.assertEqual(tc.plan_trade(sig, cfg)["stop"], 85.0)            # user can widen it


class FourthRun(unittest.TestCase):
    def test_delivery_stop_capped_at_15pct(self):
        sig = {"setup": "trend", "mode": "delivery", "date": "2026-10-30", "trigger": 100.0,
               "invalidation": 76.0, "atr": 3.0, "valid_days": 5}          # 24% structure
        p = tc.plan_trade(sig, tc.DEFAULT_CONFIG)
        self.assertEqual(p["stop"], 85.0)
        self.assertIn("15% max stop", p["stop_method"])

    def test_delivery_min_atr_still_applies(self):
        sig = {"setup": "trend", "mode": "delivery", "date": "2026-10-30", "trigger": 100.0,
               "invalidation": 99.0, "atr": 4.0, "valid_days": 5}
        self.assertEqual(tc.plan_trade(sig, tc.DEFAULT_CONFIG)["stop"], 94.0)     # 1.5 x ATR

    def test_every_mode_respects_its_cap(self):
        for mode, cap in (("swing", 10.0), ("delivery", 15.0)):
            sig = {"setup": "breakout" if mode == "swing" else "trend", "mode": mode, "date": "2026-10-30",
                   "trigger": 200.0, "invalidation": 100.0, "atr": 40.0, "valid_days": 3}
            p = tc.plan_trade(sig, tc.DEFAULT_CONFIG)
            self.assertLessEqual((p["entry"] - p["stop"]) / p["entry"] * 100, cap + 0.05, mode)

    def test_near_repeat_headlines(self):
        a = news.title_key("Coforge Ltd Sees Significant Open Interest Surge Amid Strong Market Momentum - MarketsMojo")
        b = news.title_key("Coforge Ltd Sees Significant Open Interest Surge Amidst Strong Market Momentum")
        self.assertTrue(news.near_same(a, b))
        self.assertFalse(news.near_same(news.title_key("Coforge Q2 results: profit up 12%"),
                                        news.title_key("Coforge wins $200 million deal")))


class FifthRun(unittest.TestCase):
    def test_different_numbers_are_different_stories(self):
        a = news.title_key("Coforge Ltd Hits All-Time High of Rs 2,086.05 Amid Strong Momentum")
        b = news.title_key("Coforge Ltd Hits All-Time High of Rs 2,125.9 Amid Strong Momentum")
        self.assertFalse(news.near_same(a, b))

    def test_far_apart_in_time_not_merged(self):
        a = news.title_key("Coforge Ltd Sees Significant Open Interest Surge Amid Strong Market Momentum")
        b = news.title_key("Coforge Ltd Sees Significant Open Interest Surge Amidst Strong Market Momentum")
        self.assertTrue(news.near_same(a, b, "2026-11-03T07:23:00+05:30", "2026-11-03T13:24:00+05:30"))
        self.assertFalse(news.near_same(a, b, "2026-11-01T07:23:00+05:30", "2026-11-03T13:24:00+05:30"))

    def test_verdict_warns_when_loss_most_likely(self):
        sys.path.insert(0, os.path.join(ROOT, "tayyib-timemachine"))
        import timemachine
        mc = {"expectancy_r": 0.82, "probabilities_pct": {"target": 44.0, "stop": 53.0, "breakeven": 0, "time": 3.0},
              "r_percentiles": {"p10": -1.1, "p50": -1.02, "p90": 2.9}}
        v = timemachine.verdict(mc, {"trades": 2})
        self.assertIn("leans positive", v)
        self.assertIn("most likely single outcome is a loss", v)
        mc2 = dict(mc, probabilities_pct={"target": 60.0, "stop": 35.0, "breakeven": 0, "time": 5.0},
                   r_percentiles={"p10": -1, "p50": 0.5, "p90": 2})
        self.assertNotIn("most likely", timemachine.verdict(mc2, {"trades": 2}))


class SixthRun(OfflineCase):
    def test_12h_window(self):
        a = news.title_key("Coforge Ltd Sees Sharp Open Interest Surge Amidst Strong Market Momentum")
        b = news.title_key("Coforge Ltd Sees Significant Open Interest Surge Amid Strong Market Momentum")
        self.assertFalse(news.near_same(a, b, "2026-11-02T18:37:00+05:30", "2026-11-03T07:23:00+05:30"))

    def test_more_line(self):
        self.build_universe()
        txt = self.run_script("tayyib-news/news.py", "--symbols", "ALFA", "--show", "2", as_json=False)
        self.assertIn("+2 more", txt)


class SeventhRun(OfflineCase):
    def test_cap_is_strict(self):
        for mode, cap in (("swing", 10.0), ("delivery", 15.0)):
            sig = {"setup": "breakout" if mode == "swing" else "trend", "mode": mode, "date": "2026-10-30",
                   "trigger": 4480.95, "invalidation": 3000.0, "atr": 150.0, "valid_days": 3}
            p = tc.plan_trade(sig, tc.DEFAULT_CONFIG)
            self.assertLessEqual((p["entry"] - p["stop"]) / p["entry"] * 100, cap + 1e-9, mode)

    def test_verdict_no_contradiction(self):
        sys.path.insert(0, os.path.join(ROOT, "tayyib-timemachine"))
        import timemachine
        mc = {"expectancy_r": 0.39, "probabilities_pct": {"target": 19.0, "stop": 22.0, "breakeven": 9.0, "time": 50.0},
              "r_percentiles": {"p10": -1, "p50": 0.22, "p90": 2}}
        self.assertNotIn("most likely single outcome is a loss", timemachine.verdict(mc, {"trades": 10, "expectancy_r": 0.12}))

    def test_cancelled_alerts_labelled(self):
        self.write("alerts.json", {"alerts": [{"n": 1, "symbol": "ALFA", "kind": "below", "level": 1, "note": "STOP: sell 1",
                                               "fired": "cancelled: position closed", "created": "x"}]})
        txt = self.run_script("tayyib-alerts/alerts.py", "list", as_json=False)
        self.assertIn("cancelled", txt)
        self.assertNotIn("rang", txt)


class EighthRun(unittest.TestCase):
    def test_election_results_not_company_results(self):
        self.assertNotIn("results", news.tag("US Midterm Election Results Impact Decoded for Indian markets")[0])
        self.assertIn("results", news.tag("Nykaa Q2 results: profit doubles")[0])

    def test_skill_docs_mention_windows_and_no_memory(self):
        import glob
        for f in glob.glob(os.path.join(ROOT, "tayyib-*", "SKILL.md")):
            s = open(f, encoding="utf-8").read()
            self.assertIn("use `py` instead", s, f)
            self.assertIn("Never give halal status", s, f)

    def test_gst_includes_ipft(self):
        c = tc.order_charges("BUY", 4480.95, 100, tc.DEFAULT_CONFIG)
        self.assertEqual(c["total"], 532.07)                    # matches Zerodha's published rates
