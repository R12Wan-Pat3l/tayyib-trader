"""v0.1.7 review fixes: near vs over halal limit, the dashboard's labels (older lists, no closed trades,
current vs list settings, crore / lakh, not checked), ticket ordering, full headlines, and the exit
planner no longer reusing an earlier day's waiting signal. All offline, on the fixtures."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _util import FIX, NOW, OfflineCase, ROOT, tc

DAILY, H = "tayyib-daily/daily.py", "tayyib-halal/halal.py"
DASH = os.path.join(ROOT, "tayyib-dashboard", "dashboard.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D = _load(DASH, "tayyib_dashboard_review")


class NearAndOverLimit(unittest.TestCase):
    LIM = 25.0

    def test_below_near_at_over(self):
        cases = {10.0: (False, False),        # below the near band
                 22.4: (False, False),        # just under 90% of 25 = 22.5
                 22.5: (True, False),         # 90%: near
                 24.99: (True, False),        # still under the limit: near
                 25.0: (False, True),         # at the limit: over, not near
                 37.34: (False, True)}        # AARTIIND's debt: over, not near
        for v, (near, over) in cases.items():
            self.assertEqual(tc.is_near_limit(v, self.LIM, 90), near, v)
            self.assertEqual(tc.is_over_limit(v, self.LIM), over, v)
        self.assertFalse(tc.is_near_limit(None, self.LIM, 90))
        self.assertFalse(tc.is_over_limit(None, self.LIM))

    def test_lists_and_why_items(self):
        h = tc.validate_config({})[0]["halal"]
        ratios = {"debt_to_assets_pct": 37.34, "interest_income_pct": 2.8, "noncompliant_income_pct": 5.15,
                  "assumed_return_pct": 2.55, "cash_receivables_to_assets_pct": 85.0}
        self.assertEqual(tc.near_limits(ratios, h), ["interest_income_pct", "cash_receivables_to_assets_pct"])
        self.assertEqual(tc.over_limits(ratios, h), ["debt_to_assets_pct", "noncompliant_income_pct"])
        w = {x["check"]: x for x in tc._ratio_why(ratios, h, "test")}
        debt = w["debt / total assets"]
        self.assertEqual((debt["near_limit"], debt["over_limit"], debt["ok"]), (False, True, False))
        cash = w["cash + receivables / total assets"]
        self.assertEqual((cash["near_limit"], cash["over_limit"]), (True, False))

    def test_older_items_flagged_near_are_corrected(self):
        """The first v0.1.7 build marked over-limit ratios as near: halal_why recomputes both flags."""
        item = tc.why_item("HALAL", "debt / total assets", 37.34, 25.0, "<", False, "%", None)
        item["near_limit"] = True
        hw = tc.halal_why({"status": "compliant", "why": [item]}, {})
        d = [x for x in hw if x["check"] == "debt / total assets"][0]
        self.assertEqual((d["near_limit"], d["over_limit"]), (False, True))


class DashboardLabels(unittest.TestCase):
    def test_crore_and_lakh(self):
        self.assertEqual(D.inr_short(5237000000), "₹523.7 cr")
        self.assertEqual(D.inr_short(20000000), "₹2 cr")
        self.assertEqual(D.inr_short(1250000), "₹12.5 lakh")
        self.assertEqual(D.inr_short(100000), "₹1,00,000")
        self.assertEqual(D.inr_short(None), "UNKNOWN")
        v = D.why_view([tc.why_item("LIQUIDITY", "20-day average traded value", 5237000000, 20000000, ">=", True,
                                    "Rs", None)])[0]["items"][0]
        self.assertEqual("%s %s" % (v["value"], v["limit"]), "₹523.7 cr ≥ ₹2 cr")

    def test_no_closed_trades_is_said_not_zero(self):
        s = {"listed": 3, "triggered": 1, "closed": 0, "win_rate_pct": None, "avg_r": None, "total_r": 0.0,
             "pnl_rs": 0.0}
        self.assertEqual(D.stats_display(s), {k: "no closed trades" for k in ("win_rate_pct", "avg_r", "total_r",
                                                                              "pnl_rs")})
        d = D.stats_display(dict(s, closed=2, win_rate_pct=50.0, avg_r=0.4, total_r=0.8, pnl_rs=120.0))
        self.assertEqual(d["pnl_rs"], "₹120.00")

    def test_older_list_label(self):
        r = {"symbol": "X", "expectancy_r": 2.47, "past_trades": 2, "why": []}
        older = D.row_view(dict(r), 0, older=True)
        self.assertEqual(older["expectancy_use"], "older list: ranked by expectancy only")
        self.assertNotIn("ranked (", older["expectancy_use"])
        new = D.row_view(dict(r), 8)
        self.assertEqual(new["expectancy_use"], "information only (2 trades)")

    def test_halal_badge_over_vs_near(self):
        over = tc.why_item("HALAL", "debt / total assets", 37.0, 25.0, "<", False, "%", None)
        near = tc.why_item("HALAL", "debt / total assets", 23.0, 25.0, "<", True, "%", None)
        ok = tc.why_item("HALAL", "debt / total assets", 3.0, 25.0, "<", True, "%", None)
        self.assertEqual(D.halal_badge([over])["state"], "over")
        self.assertEqual(D.halal_badge([near])["state"], "near")
        self.assertEqual(D.halal_badge([ok])["state"], "ok")
        ov = tc.why_item("HALAL", "your override", "compliant", None, None, True, None, "scholar")
        self.assertIn("override", D.halal_badge([ov, over])["label"])
        self.assertEqual(D.halal_badge([])["state"], "unknown")

    def test_ladder(self):
        lad = D.ladder({"entry": 100.0, "stop": 90.0, "target": 130.0})
        self.assertEqual((lad["stop"]["r"], lad["entry"]["r"], lad["target"]["r"]), ("−1R", "0R", "+3.0R"))
        self.assertEqual(lad["entry"]["pos"], 25.0)
        self.assertIsNone(D.ladder({"entry": 100.0, "stop": None, "target": 130.0}))


class ServerLabels(OfflineCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix="tayyib-review-")
        env = dict(os.environ, TAYYIB_DIR=cls.data, TAYYIB_FIXTURES=FIX, TAYYIB_NOW=NOW)
        for args in ((H, "build"), (DAILY, "--no-news", "--no-rebuild")):
            p = subprocess.run([sys.executable, os.path.join(ROOT, args[0])] + list(args[1:]) + ["--json"],
                               capture_output=True, encoding="utf-8", env=env, cwd=cls.data)
            assert p.returncode == 0, p.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.data, ignore_errors=True)

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.dir)
        shutil.copytree(self.data, self.dir)

    def daily(self):
        return self.read("daily/2026-10-30.json")

    def test_current_vs_list_settings(self):
        self.assertEqual(D.api_meta({})["settings_header"],
                         "Current settings: " + ("default@%d" % tc.DEFAULTS_VERSION))
        t = D.api_today({})
        self.assertEqual(t["made_with"], "This list was made with: " + ("default@%d" % tc.DEFAULTS_VERSION))
        self.assertFalse(t["older_list"])
        self.assertIn("at least 8 past trades", t["rank_note"])
        self.assertEqual(t["checks"][0], "PASS") if "PASS" in t["checks"] else None

    def test_older_list(self):
        d = self.daily()
        del d["settings"]["values"]["daily"]["min_past_trades_for_rank"]
        d["settings"]["label"] = "default@1"
        for r in d["rows"]:
            r.pop("expectancy_use", None)
            r.pop("ranked_by", None)
        self.write("daily/2026-10-30.json", d)
        t = D.api_today({})
        self.assertTrue(t["older_list"])
        self.assertEqual(t["rank_note"], "Older list: ranked by expectancy only (made before the thin-evidence rule)")
        self.assertEqual(t["made_with"], "This list was made with: default@1")
        self.assertNotIn("at least 0", json.dumps(t))
        for r in t["rows"]:
            if not r.get("halal_changed"):
                self.assertFalse(r["expectancy_use"].startswith("ranked ("), r["expectancy_use"])

    def test_tracker_without_closed_trades(self):
        tr = D.api_tracker({})
        self.assertEqual(tr["closed"], 0)
        for v in tr["kpis"]["win_rate_pct"], tr["kpis"]["avg_r"], tr["kpis"]["total_r"], tr["kpis"]["pnl_rs"]:
            self.assertEqual(v, "no closed trades")
        for g in tr["groups"]:
            self.assertEqual(g["display"]["pnl_rs"], "no closed trades")
        self.assertNotIn("₹0.00", json.dumps(tr["groups"], ensure_ascii=False))
        self.assertEqual(tr["ring"]["label"], "0 of 30 closed trades")
        for r in tr["rows"]:
            if r["status"] == "WAITING":
                self.assertEqual((r["display"]["filled"], r["display"]["r"]), ("not yet", "not closed"))
        html = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertIn("Triggered (paper)", html)
        self.assertNotIn('title:"Bought', html)

    def test_halal_list_records_near_and_over(self):
        uni = self.read("halal_universe.json")
        h = tc.validate_config({})[0]["halal"]
        screened = [x for x in uni["stocks"].values() if x.get("ratios")]
        self.assertTrue(screened)
        for x in screened:
            self.assertEqual(x["near_limit"], tc.near_limits(x["ratios"], h))
            self.assertEqual(x["over_limit"], tc.over_limits(x["ratios"], h))
            self.assertFalse(set(x["near_limit"]) & set(x["over_limit"]))

    def test_halal_not_checked_and_over(self):
        uni = self.read("halal_universe.json")
        sym = sorted(uni["stocks"])[0]
        uni["stocks"][sym].update(status="excluded", ratios=None, reasons=["business: alcohol"])
        self.write("halal_universe.json", uni)
        h = D.api_halal({})
        s = [x for x in h["stocks"] if x["symbol"] == sym][0]
        self.assertTrue(s["not_checked"])
        self.assertEqual({b["value_text"] for b in s["ratios"]}, {"not checked (business excluded)"})
        self.assertEqual({b["state"] for b in s["ratios"]}, {"not_checked"})
        for x in h["stocks"]:
            for b in x["ratios"]:
                if b["value"] is not None and b["limit"] is not None and b["value"] >= b["limit"]:
                    self.assertEqual((b["state"], b["near_limit"], b["over"]), ("over", False, True))
        self.assertEqual(sum(sg["count"] for sg in h["donut"]["segments"]), len(h["stocks"]))

    def test_ticket_order(self):
        o = self.read("orders.json")
        statuses = ["BLOCK", "WARN", "PASS", "BLOCK", "PASS"]
        base = o["orders"][0]
        o["orders"] = [dict(base, id="T%d" % k, status=st) for k, st in enumerate(statuses)]
        self.write("orders.json", o)
        ti = D.api_tickets({})
        self.assertEqual([t["status"] for t in ti["ready"]], ["PASS", "PASS", "WARN"])
        self.assertEqual([t["status"] for t in ti["blocked"]], ["BLOCK", "BLOCK"])
        self.assertEqual([t["status"] for t in ti["tickets"]], ["PASS", "PASS", "WARN", "BLOCK", "BLOCK"])
        self.assertEqual(ti["blocked_title"], "Blocked (not tickets)")
        self.assertEqual(ti["totals"]["pnl_rs"], "no closed trades")

    def test_full_headline_in_why(self):
        d = self.daily()
        r = [x for x in d["rows"] if x.get("why")][0]
        full = "Company announces board meeting to consider quarterly results and a new borrowing programme"
        r["why"].append(tc.why_item("NEWS", "results news in the window", full[:70], None, None, False, None, "x"))
        self.write("daily/2026-10-30.json", d)
        self.write("news.json", {"symbols": {r["symbol"]: [{"title": full}]}})
        row = [x for x in D.api_today({})["rows"] if x["symbol"] == r["symbol"]][0]
        news = [i for g in row["why_view"] if g["group"] == "NEWS" for i in g["items"]
                if i["check"] == "results news in the window" and i["value"] != "UNKNOWN"]
        self.assertEqual(news[-1]["value"], full)
        src = open(os.path.join(ROOT, "tayyib-risk", "check.py"), encoding="utf-8").read()
        self.assertNotIn('it["title"][:90], None', src)                     # stored in full from now on
        self.assertNotIn('it["title"][:70], None', src)


class PluralsAndScroll(OfflineCase):
    def test_plural(self):
        self.assertEqual(tc.plural(1, "day"), "1 day")
        self.assertEqual(tc.plural(0, "day"), "0 days")
        self.assertEqual(tc.plural(30, "day"), "30 days")
        self.assertEqual(tc.plural(1, "session"), "1 session")

    def test_no_unpluralised_day_counts(self):
        import re
        bad = re.compile(r"%d (days|sessions)\b|\+ \" days")      # a count printed with a fixed plural
        dirs = [os.path.join(ROOT, "core")] + [os.path.join(ROOT, x) for x in os.listdir(ROOT)
                                               if x.startswith("tayyib-") and os.path.isdir(os.path.join(ROOT, x))]
        for d in dirs:
            for f in os.listdir(d):
                if not f.endswith((".py", ".html")) or (f == "tayyib_core.py" and not d.endswith("core")):
                    continue                                          # the synced copies equal core
                src = open(os.path.join(d, f), encoding="utf-8").read()
                m = bad.search(src)
                self.assertIsNone(m, "%s/%s: %s" % (os.path.basename(d), f, m and m.group(0)))
        self.assertIsNotNone(bad.search('"%d days old" % n'))           # the pattern does catch one

    def test_halal_age_text(self):
        self.build_universe()
        h = D.api_halal({})
        self.assertEqual(h["age_text"], tc.plural(h["age_days"], "day") + " ago")
        html = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertNotIn('" days ago"', html)

    def test_tab_switch_scrolls_to_top(self):
        html = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        body = html[html.index("function show(name, focus)"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("if (changed) window.scrollTo(0, 0);", body)     # click, keys, hash, back / forward
        self.assertIn('history.scrollRestoration = "manual"', html)


class ExitSignalNotStale(OfflineCase):
    """WELSPUNLIV-2026-11-04-trend on the 2026-11-05 list: a WAITING entries.json record from an earlier day
    replaced today's scan. A newer scan signal now wins; a triggered record still wins."""

    def setUp(self):
        super().setUp()
        self.build_universe()
        self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.scan = self.read("scan.json")
        self.c = self.scan["candidates"][0]
        self.ex = _load(os.path.join(ROOT, "tayyib-exit", "exit.py"), "tayyib_exit_review")

    def entry(self, status):
        old = dict(self.c, date="2026-10-20", trigger=round(self.c["trigger"] * 0.9, 2))
        self.write("entries.json", {self.c["symbol"]: {"status": status, "symbol": self.c["symbol"],
                                                       "setup": self.c["setup"], "mode": self.c["mode"],
                                                       "signal_date": "2026-10-20", "signal": old}})

    def test_newer_scan_wins_over_waiting_record(self):
        self.entry("WAITING")
        sig, ent = self.ex.signal_for(self.c["symbol"], self.c["setup"], tc.load_config(), self.c["mode"])
        self.assertEqual(sig["date"], self.c["date"])
        self.assertIsNone(ent)

    def test_triggered_record_still_wins(self):
        self.entry("TRIGGERED")
        sig, ent = self.ex.signal_for(self.c["symbol"], self.c["setup"], tc.load_config(), self.c["mode"])
        self.assertEqual(sig["date"], "2026-10-20")
        self.assertIsNotNone(ent)


if __name__ == "__main__":
    unittest.main()
