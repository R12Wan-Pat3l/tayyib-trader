"""v0.1.10: the NEWS checks split into two lines, "Media news" and "Exchange filings (NSE)", with a distinct
"Not available" state when NSE refuses automated access (neutral, ok=None, never a pass). Display only:
no decision changes (the baseline tests cover that)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _util import FIX, NOW, OfflineCase, ROOT, tc


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK = _load("tayyib_check_v110", os.path.join(ROOT, "tayyib-risk", "check.py"))
DAILY = _load("tayyib_daily_v110", os.path.join(ROOT, "tayyib-daily", "daily.py"))
DASH = _load("tayyib_dashboard_v110", os.path.join(ROOT, "tayyib-dashboard", "dashboard.py"))
NA = "NSE blocks automated access → check yourself"


def news(**src):
    base = {"asof": "2026-10-30T18:00+05:30", "hours": 72, "errors": [], "symbols": {"ALFA": []},
            "feeds": {"answered": ["moneycontrol_markets", "et_markets"], "failed": {}},
            "sources": {"ALFA": {"answered": ["Google News", "NSE announcements"], "failed": {}}}}
    base["sources"]["ALFA"].update(src)
    return base


class States(unittest.TestCase):
    def lines(self, n):
        return {x["check"]: x for x in CHECK.news_why("ALFA", n, "2026-10-30")}

    def test_two_lines_none_flagged(self):
        w = CHECK.news_why("ALFA", news(), "2026-10-30")
        self.assertEqual([(x["check"], x["value"], x["ok"]) for x in w],
                         [("Media news", "none flagged", True), ("Exchange filings (NSE)", "none flagged", True)])
        self.assertIn("answered: Google News, 2 RSS feeds", w[0]["note"])

    def test_nse_refused_is_not_available_never_a_pass(self):
        for reason in ("NSE refused automated access", "NSE refused: too many requests",
                       "not tried: NSE refused automated access earlier in this run"):
            w = self.lines(news(answered=["Google News"], failed={"NSE announcements": reason}))
            f = w["Exchange filings (NSE)"]
            self.assertEqual((f["value"], f["op"], f["ok"]), ("Not available", "not_available", None), reason)
            self.assertEqual(f["note"], "%s (%s)" % (NA, reason))
            self.assertIs(w["Media news"]["ok"], True)                  # the media line is still checked

    def test_real_nse_failure_stays_unknown(self):
        for reason in ("NSE failed: HTTP 503", "NSE could not be reached", "NSE answered with something that is not data"):
            f = self.lines(news(answered=["Google News"], failed={"NSE announcements": reason}))["Exchange filings (NSE)"]
            self.assertEqual((f["value"], f["op"], f["ok"]), (None, None, None))
            self.assertEqual(f["note"], "UNKNOWN: NSE announcements failed (%s)" % reason)

    def test_media_unknown_when_google_or_every_media_source_failed(self):
        n = news(answered=["NSE announcements"], failed={"Google News": "Google News did not answer"})
        m = self.lines(n)["Media news"]
        self.assertEqual((m["value"], m["ok"]), (None, None))
        self.assertTrue(m["note"].startswith("UNKNOWN: Google News failed for this stock"))
        n["feeds"] = {"answered": [], "failed": {"et_markets": "et_markets did not answer"}}
        m = self.lines(n)["Media news"]
        self.assertIsNone(m["ok"])
        self.assertIn("failed: Google News: Google News did not answer; et_markets: et_markets did not answer", m["note"])
        # a market feed failing while Google News answered: still checked, and the failure is named
        n = news()
        n["feeds"]["failed"] = {"livemint_markets": "livemint_markets did not answer"}
        m = self.lines(n)["Media news"]
        self.assertIs(m["ok"], True)
        self.assertIn("failed: livemint_markets", m["note"])

    def test_flagged_headlines_by_source(self):
        n = news()
        n["symbols"]["ALFA"] = [
            {"title": "Alfa Ltd to raise Rs 500 cr via NCD issue", "source": "Google News", "published": None,
             "tags": [], "halal_watch": ["new debt"]},
            {"title": "Board meeting: financial results for Q2", "source": "NSE announcement", "published": None,
             "tags": ["results"], "halal_watch": []}]
        w = CHECK.news_why("ALFA", n, "2026-10-30")
        self.assertEqual([(x["check"], x["ok"]) for x in w], [("Media news", False), ("Exchange filings (NSE)", False)])
        self.assertEqual(w[0]["value"], "Alfa Ltd to raise Rs 500 cr via NCD issue")
        self.assertTrue(w[0]["note"].startswith("HALAL-WATCH: new debt: WARN"))
        self.assertTrue(w[1]["note"].startswith("results news in the window: gaps are likely: WARN"))

    def test_turned_off_and_not_fetched(self):
        n = news(answered=["Google News"])
        f = self.lines(n)["Exchange filings (NSE)"]
        self.assertEqual((f["value"], f["ok"]), ("not checked", None))
        w = CHECK.news_why("ALFA", {"symbols": {}}, "2026-10-30")
        self.assertEqual([(x["check"], x["value"], x["ok"]) for x in w],
                         [("Media news", None, None), ("Exchange filings (NSE)", None, None)])

    def test_decisions_do_not_read_the_why_lines(self):
        """warn[] (and so PASS / WARN / BLOCK) comes from the headlines, not from these display lines."""
        src = open(os.path.join(ROOT, "core", "tayyib_core.py"), encoding="utf-8").read()   # v0.2.1: moved to core
        body = src[src.index("def risk_check_order("):]
        self.assertIn('warn.append("HALAL-WATCH news: %s', body)
        self.assertIn('warn.append("results news in the window: gaps are likely', body)
        self.assertEqual(tc.DEFAULTS_VERSION, 2)


class Display(unittest.TestCase):
    def test_why_view_mark_is_neutral(self):
        w = CHECK.news_why("ALFA", news(answered=["Google News"],
                                        failed={"NSE announcements": "NSE refused automated access"}), "2026-10-30")
        view = DASH.why_view(w)
        items = {i["check"]: i for g in view for i in g["items"]}
        self.assertEqual((items["Exchange filings (NSE)"]["mark"], items["Exchange filings (NSE)"]["symbol"],
                          items["Exchange filings (NSE)"]["value"]), ("na", "–", "Not available"))
        self.assertIsNone(items["Exchange filings (NSE)"]["limit"])
        self.assertEqual((items["Media news"]["mark"], items["Media news"]["symbol"]), ("ok", "✓"))

    def test_news_lines_for_cards(self):
        w = CHECK.news_why("ALFA", news(answered=["Google News"],
                                        failed={"NSE announcements": "NSE refused automated access"}), "2026-10-30")
        self.assertEqual(DASH.news_lines(w), [
            {"label": "Media news", "state": "ok", "text": "none flagged"},
            {"label": "Exchange filings (NSE)", "state": "na",
             "text": "Not available: NSE blocks automated access → check yourself"}])
        u = CHECK.news_why("ALFA", news(failed={"NSE announcements": "NSE failed: HTTP 503"}), "2026-10-30")
        self.assertEqual(DASH.news_lines(u)[1]["state"], "unknown")
        self.assertTrue(DASH.news_lines(u)[1]["text"].startswith("UNKNOWN: NSE announcements failed"))
        old = [tc.why_item("NEWS", "HALAL-WATCH news", "none", None, None, True, None, "x")]   # a pre-0.1.10 list
        self.assertEqual(DASH.news_lines(old), [])

    def test_md_lines(self):
        w = CHECK.news_why("ALFA", news(answered=["Google News"],
                                        failed={"NSE announcements": "NSE refused automated access"}), "2026-10-30")
        md = DAILY.why_md(w)
        self.assertIn("    - NEWS:", md)
        self.assertIn("      - Exchange filings (NSE): Not available: %s" % NA, md)
        self.assertTrue(any(x.startswith("      - Media news: ✓ none flagged (") for x in md), md)

    def test_page(self):
        page = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertIn('na:["na", "–", "Not available"]', page)
        self.assertIn('else if (kind === "na")', page)                 # its own neutral icon, never the ✓
        body = page[page.index("function newsEl"):page.index("function whyGroups")]
        self.assertIn("linksEl(links)", body)                          # NSE link + Copy ISIN next to the lines
        self.assertNotIn("✓", body)


class EndToEnd(OfflineCase):
    def test_daily_with_nse_refusing(self):
        tmp = tempfile.mkdtemp(prefix="tayyib-v110-")
        self.addCleanup(shutil.rmtree, tmp, True)
        fix = os.path.join(tmp, "f")
        shutil.copytree(FIX, fix)
        for f in os.listdir(os.path.join(fix, "nse")):
            if f.startswith("announcements_"):
                with open(os.path.join(fix, "nse", f), "wb") as h:
                    h.write(b"HTTP 403")
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=fix, TAYYIB_NOW=NOW)
        for args in (["tayyib-halal/halal.py", "build"], ["tayyib-daily/daily.py", "--no-rebuild"]):
            p = subprocess.run([sys.executable, os.path.join(ROOT, args[0])] + args[1:] + ["--json"],
                               capture_output=True, encoding="utf-8", env=env, cwd=self.dir)
            self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        for r in out["rows"]:
            f = [w for w in r["why"] if w["check"] == "Exchange filings (NSE)"]
            if f:
                self.assertEqual([(w["value"], w["ok"]) for w in f], [("Not available", None)])
            self.assertNotIn("news_lines", r)                           # daily rows: unchanged keys
        md = open(os.path.join(self.dir, "daily", out["date"] + ".md"), encoding="utf-8").read()
        if out["top_picks"]:
            self.assertIn("Exchange filings (NSE): Not available: %s" % NA, md)
        today = DASH.api_today({})
        for r in today["top_picks"]:
            if not r.get("halal_changed"):
                self.assertEqual(r["news_lines"][1]["state"], "na")


if __name__ == "__main__":
    unittest.main()
