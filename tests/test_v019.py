"""v0.1.9: honest requests to NSE (and BSE), why[] NEWS naming its sources, the clearer source-failure banner
and the "Check announcements yourself" links. No decision changes (the baseline tests cover that)."""
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from _util import FIX, NOW, OfflineCase, ROOT, tc


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK = _load("tayyib_check_v019", os.path.join(ROOT, "tayyib-risk", "check.py"))
DAILY = _load("tayyib_daily_v019", os.path.join(ROOT, "tayyib-daily", "daily.py"))
DASH = _load("tayyib_dashboard_v019", os.path.join(ROOT, "tayyib-dashboard", "dashboard.py"))
PY = [os.path.join(dp, f) for dp, _, fs in os.walk(ROOT) if ".git" not in dp and "__pycache__" not in dp
      for f in fs if f.endswith(".py")]


class Refused(Exception):
    pass


class HonestRequests(unittest.TestCase):
    """NSE gets the honest user agent and nothing else: no browser UA, no fingerprint headers, no warm-up."""

    def setUp(self):
        self.sent = []

        def urlopen(req, timeout=None):
            self.sent.append(req)
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
        p1 = mock.patch.object(tc, "fixtures_dir", lambda: None)
        p2 = mock.patch.object(urllib.request, "urlopen", urlopen)
        p3 = mock.patch.object(tc.time, "sleep", lambda s: None)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_nse_sends_the_honest_user_agent_and_no_warm_up(self):
        sess = tc.NSESession()
        with self.assertRaises(tc.FetchError) as e:
            sess.get_json("/api/corporate-announcements", {"index": "equities", "symbol": "ALFA"})
        self.assertEqual(tc.fetch_reason(e.exception, "NSE"), "NSE refused automated access")
        self.assertEqual(len(self.sent), 1)                       # no homepage visit first, no retry on 403
        req = self.sent[0]
        self.assertEqual(req.full_url, "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=ALFA")
        hdrs = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(hdrs["user-agent"], "tayyib-trader/%s (+https://github.com/R12Wan-Pat3l/tayyib-trader)"
                         % tc.VERSION)
        self.assertEqual(tc.HONEST_UA, hdrs["user-agent"])
        self.assertFalse({"referer", "cookie", "origin", "x-requested-with"} & set(hdrs))
        self.assertFalse([k for k in hdrs if k.startswith("sec-")])
        self.assertNotIn("Mozilla", hdrs["user-agent"])

    def test_after_a_refusal_the_rest_are_not_tried(self):
        sess = tc.NSESession()
        for sym in ("ALFA", "CHRL", "DELT"):
            with self.assertRaises(tc.FetchError) as e:
                sess.get_json("/api/corporate-announcements", {"index": "equities", "symbol": sym})
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(str(e.exception), "not tried: NSE refused automated access earlier in this run")

    def test_no_browser_imitation_for_nse_or_bse_anywhere(self):
        src = inspect.getsource(tc.NSESession)
        for bad in ("BROWSER_UA", "Mozilla", "CookieJar", "HTTPCookieProcessor", "Referer", "_warm", "opener"):
            self.assertNotIn(bad, src)
        for path in PY:
            if os.sep + "tests" + os.sep in path:
                continue
            text = open(path, encoding="utf-8").read()
            self.assertNotRegex(text, r"Sec-Fetch|X-Requested-With|sec-ch-ua", path)
            for line in text.splitlines():
                if re.search(r"nseindia|bseindia", line) and "BROWSER_UA" in line:
                    self.fail("browser user agent sent to an exchange: %s: %s" % (path, line))
        # the only browser user agent left is tayyib-halal's niftyindices download (reported, decision pending)
        users = sorted(os.path.relpath(p, ROOT) for p in PY if os.sep + "tests" + os.sep not in p
                       and not p.endswith("tayyib_core.py") and "BROWSER_UA" in open(p, encoding="utf-8").read())
        self.assertEqual(users, [os.path.join("tayyib-halal", "halal.py")])

    def test_fetch_reason(self):
        R = tc.fetch_reason
        self.assertEqual(R("https://x -> HTTP 403", "NSE"), "NSE refused automated access")
        self.assertEqual(R("https://x -> HTTP 401", "BSE"), "BSE refused automated access")
        self.assertEqual(R("https://x -> <urlopen error The read operation timed out>", "NSE"), "NSE did not answer")
        self.assertEqual(R("https://x -> HTTP 503", "NSE"), "NSE failed: HTTP 503")
        self.assertEqual(R("https://x -> [Errno 11001] getaddrinfo failed", "NSE"), "NSE could not be reached")


class Banner(unittest.TestCase):
    def test_banner_text(self):
        b = DAILY.source_banner(["nse %s: https://www.nseindia.com/api/x -> HTTP 403" % s for s in "ABCDEFGHIJ"],
                                list("ABCDEFGHIJ"))
        self.assertEqual(b, "Exchange filings unavailable today (NSE refused automated access). HALAL-WATCH and "
                            "results checks are incomplete for 10 of 10 stocks: check the announcements yourself for "
                            "any stock you plan to buy.")
        b = DAILY.source_banner(["nse A: https://x -> HTTP 403", "nse B: not tried: NSE refused automated access "
                                 "earlier in this run", "google C: https://y -> <urlopen error timed out>"], ["A", "B", "C"])
        self.assertEqual(b, "Exchange filings and Google News unavailable today (NSE refused automated access; Google "
                            "News did not answer). HALAL-WATCH and results checks are incomplete for 3 of 3 stocks: "
                            "check the announcements yourself for any stock you plan to buy.")
        self.assertIsNone(DAILY.source_banner(["et_markets: https://z -> HTTP 500"], ["A"]))   # market feeds only


class WhySources(unittest.TestCase):
    NEWS = {"asof": "2026-10-30T18:00+05:30", "hours": 72, "errors": [],
            "symbols": {"ALFA": [], "CHRL": []},
            "feeds": {"answered": ["moneycontrol_markets", "livemint_markets", "et_markets"],
                      "failed": {"moneycontrol_business": "moneycontrol_business did not answer"}},
            "sources": {"ALFA": {"answered": ["Google News", "NSE announcements"], "failed": {}},
                        "CHRL": {"answered": ["Google News"],
                                 "failed": {"NSE announcements": "NSE refused automated access"}}}}

    def test_answered_and_failed_are_named(self):
        news = json.loads(json.dumps(self.NEWS))
        news["errors"] = ["nse CHRL: https://www.nseindia.com/api/x -> HTTP 403",
                          "moneycontrol_business: https://m -> timed out"]
        ok = CHECK.news_why("ALFA", news, "2026-10-30")
        self.assertEqual([w["ok"] for w in ok], [True, True])
        self.assertIn("answered: Google News, NSE announcements, 3 RSS feeds", ok[0]["note"])
        self.assertIn("failed: moneycontrol_business: moneycontrol_business did not answer", ok[0]["note"])
        bad = CHECK.news_why("CHRL", news, "2026-10-30")
        self.assertEqual([w["ok"] for w in bad], [None, None])                 # a needed source failed: UNKNOWN
        self.assertTrue(bad[0]["note"].startswith("UNKNOWN: a source for this stock failed (NSE announcements: "
                                                  "NSE refused automated access)"))
        self.assertIn("answered: Google News, 3 RSS feeds", bad[0]["note"])

    def test_older_news_json_still_works(self):
        news = {"asof": "2026-10-30T18:00+05:30", "hours": 72, "errors": ["nse ALFA: HTTP 403"], "symbols": {"ALFA": []}}
        w = CHECK.news_why("ALFA", news, "2026-10-30")
        self.assertEqual([x["ok"] for x in w], [None, None])
        self.assertNotIn("answered", w[0]["note"])

    def test_news_py_records_sources(self):
        """End to end, offline: NSE refuses for ALFA (a b"HTTP 403" fixture), answers for CHRL."""
        tmp = tempfile.mkdtemp(prefix="tayyib-v019-")
        try:
            fix = os.path.join(tmp, "f")
            shutil.copytree(FIX, fix)
            with open(os.path.join(fix, "nse", "announcements_ALFA.json"), "wb") as f:
                f.write(b"HTTP 403")
            data = os.path.join(tmp, "d")
            os.makedirs(data)
            env = dict(os.environ, TAYYIB_DIR=data, TAYYIB_FIXTURES=fix, TAYYIB_NOW=NOW)
            for args in (["tayyib-halal/halal.py", "build"], ["tayyib-news/news.py", "--symbols", "ALFA,CHRL"]):
                p = subprocess.run([sys.executable, os.path.join(ROOT, args[0])] + args[1:] + ["--json"],
                                   capture_output=True, encoding="utf-8", env=env, cwd=data)
                self.assertEqual(p.returncode, 0, p.stderr)
            out = json.load(open(os.path.join(data, "news.json"), encoding="utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["sources"]["ALFA"], {"answered": ["Google News"],
                                                  "failed": {"NSE announcements": "NSE refused automated access"}})
        self.assertEqual(out["sources"]["CHRL"], {"answered": ["Google News", "NSE announcements"], "failed": {}})
        self.assertIn("nse ALFA: https://www.nseindia.com/api/corporate-announcements -> HTTP 403", out["errors"])
        w = [x for x in CHECK.news_why("ALFA", out, "2026-10-30") if x["value"] is None]
        self.assertTrue(w)                                   # a check with no flagged headline: UNKNOWN, not "none"
        for x in w:
            self.assertIsNone(x["ok"])
            self.assertIn("NSE announcements: NSE refused automated access", x["note"])


class ManualLinks(OfflineCase):
    def test_link_format(self):
        L = tc.manual_links("ALFA", {"isin": "INE000A01019"})
        self.assertEqual(L, [{"label": "NSE company page", "url": "https://www.nseindia.com/get-quotes/equity?symbol=ALFA",
                              "hint": None},
                             {"label": "BSE search", "url": "https://www.bseindia.com/getquote.aspx",
                              "hint": "search for ISIN INE000A01019"}])
        self.assertEqual(tc.manual_links("M&M", {})[0]["url"], "https://www.nseindia.com/get-quotes/equity?symbol=M%26M")
        self.assertEqual(tc.manual_links("ALFA", {"bse_code": "500325"})[1],     # a scrip code we already have
                         {"label": "BSE company page", "url": "https://m.bseindia.com/StockReach.aspx?scripcd=500325",
                          "hint": None})
        self.assertEqual(tc.manual_links("alfa.ns")[1]["hint"], "search for ALFA")   # no ISIN: never a guessed one

    def test_links_in_daily_md_dashboard_and_page(self):
        self.build_universe()
        out = self.run_script("tayyib-daily/daily.py", "--no-rebuild")
        md = open(os.path.join(self.dir, "daily", out["date"] + ".md"), encoding="utf-8").read()
        uni = tc.load_universe()
        self.assertTrue(out["top_picks"])
        for sym in out["top_picks"]:
            isin = uni["stocks"][sym]["isin"]
            self.assertIn("  Check announcements yourself: [NSE company page](https://www.nseindia.com/get-quotes/"
                          "equity?symbol=%s) · [BSE search](https://www.bseindia.com/getquote.aspx) (search for ISIN %s)"
                          % (sym, isin), md)
        for r in out["rows"]:
            self.assertNotIn("links", r)                    # the daily rows (and the baseline) are unchanged
        today = DASH.api_today({})
        self.assertTrue(today["top_picks"])
        for r in today["top_picks"] + today["rows"]:
            if not r.get("halal_changed"):
                self.assertEqual(r["links"][0]["url"], tc.NSE_QUOTE_URL % r["symbol"])
        tickets = DASH.api_tickets({})
        for t in tickets["tickets"]:
            if not t.get("halal_changed"):
                self.assertEqual(t["links"], tc.manual_links(t["symbol"], uni["stocks"][t["symbol"]]))
        page = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertIn('el("a", { href:x.url, target:"_blank", rel:"noopener noreferrer"', page)
        self.assertIn("Check announcements yourself:", page)
        self.assertIn("linksEl(r.links)", page)                      # top-pick cards
        self.assertIn("linksEl(t.links)", page)                      # ticket cards
        self.assertIn("whyGroups(b, r.why_view, r.links)", page)     # the Why drawer, in its NEWS section
        self.assertIn(r"var MANUAL_HOSTS = /^https:\/\/(www|m)\.(nseindia|bseindia)\.com\//;", page)
        # the dashboard itself never fetches them: no exchange host in dashboard.py or actions.py
        for f in ("dashboard.py", "actions.py"):
            self.assertNotRegex(open(os.path.join(ROOT, "tayyib-dashboard", f), encoding="utf-8").read(),
                                r"nseindia|bseindia")


class NoDecisionChange(unittest.TestCase):
    def test_defaults_version_unchanged(self):
        self.assertEqual(tc.DEFAULTS_VERSION, 2)
        self.assertEqual(tc.VERSION, "0.1.9")


if __name__ == "__main__":
    unittest.main()
