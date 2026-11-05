"""v0.1.7: ranking on thin evidence (default@2), the news source-failure banner, the why[] additions,
halal.list_url removed, and the read-only dashboard server. All offline, on the fixtures."""
import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from _util import FIX, NOW, OfflineCase, ROOT, tc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baseline  # noqa: E402

DAILY, H, TR, RI, BR = ("tayyib-daily/daily.py", "tayyib-halal/halal.py", "tayyib-tracker/tracker.py",
                        "tayyib-risk/check.py", "tayyib-broker/ticket.py")
DASH_DIR = os.path.join(ROOT, "tayyib-dashboard")


def load_dashboard():
    spec = importlib.util.spec_from_file_location("tayyib_dashboard_under_test", os.path.join(DASH_DIR, "dashboard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D = load_dashboard()


# --- Part 0 ---------------------------------------------------------------------------------------

class ListUrlRemoved(unittest.TestCase):
    def test_gone_from_defaults_docs_and_snapshot_exceptions(self):
        self.assertNotIn("list_url", tc.DEFAULT_CONFIG["halal"])
        self.assertNotIn("halal.list_url", tc.DEFAULT_CONFIG_DOCS)
        self.assertNotIn("halal.list_url", tc.SETTINGS_EXCLUDE)
        self.assertIn("parent_list_url", tc.DEFAULT_CONFIG["halal"])           # the one that is used stays

    def test_old_config_gets_the_note(self):
        cfg, notes = tc.validate_config({"halal": {"list_url": "https://example.org/shariah.csv"}})
        self.assertEqual(notes, ["CONFIG: halal.list_url removed: it was never used"])
        self.assertNotIn("list_url", cfg["halal"])
        self.assertEqual(tc.settings_snapshot(cfg)["label"], "default@2")      # changes nothing


# --- A1: ranking ------------------------------------------------------------------------------------

class Ranking(OfflineCase):
    def test_rank_key(self):
        rows = [{"s": "A", "e": 0.10, "n": 20, "sc": 60}, {"s": "B", "e": 2.50, "n": 2, "sc": 70},
                {"s": "C", "e": 0.40, "n": 9, "sc": 50}, {"s": "D", "e": 1.00, "n": 1, "sc": 95},
                {"s": "E", "e": None, "n": None, "sc": 99}, {"s": "F", "e": 0.30, "n": 8, "sc": 40}]
        order = lambda k: [r["s"] for r in sorted(rows, key=lambda r: tc.rank_key(r["e"], r["n"], r["sc"], k))]
        # >= 8 past trades: by expectancy (C 0.40, F 0.30, A 0.10); then the rest by score (E 99, D 95, B 70)
        self.assertEqual(order(8), ["C", "F", "A", "E", "D", "B"])
        self.assertEqual(order(0), ["B", "D", "C", "F", "A", "E"])        # the v0.1.4 order: expectancy only
        self.assertEqual(order(50), ["E", "D", "B", "A", "C", "F"])       # nobody has 50: score only
        self.assertTrue(tc.thin_evidence(7, 8))
        self.assertFalse(tc.thin_evidence(8, 8))
        self.assertTrue(tc.thin_evidence(None, 8))
        self.assertFalse(tc.thin_evidence(None, 0))
        self.assertEqual(tc.expectancy_label(0.8, 2, 8), "information only (2 trades)")
        self.assertEqual(tc.expectancy_label(0.8, 1, 8), "information only (1 trade)")
        self.assertEqual(tc.expectancy_label(0.8, 9, 8), "ranked (9 trades)")
        self.assertEqual(tc.expectancy_label(None, 9, 8), "UNKNOWN")

    def test_setting_documented_and_validated(self):
        self.assertEqual(tc.DEFAULT_CONFIG["daily"]["min_past_trades_for_rank"], 8)
        doc = tc.DEFAULT_CONFIG_DOCS["daily.min_past_trades_for_rank"]
        self.assertEqual((doc["min"], doc["max"], doc["type"]), (0, 50, "int"))
        cfg, notes = tc.validate_config({"daily": {"min_past_trades_for_rank": 51}})
        self.assertEqual(cfg["daily"]["min_past_trades_for_rank"], 8)
        self.assertIn("daily.min_past_trades_for_rank = 51 invalid (range 0–50), using default 8", notes[0])

    def run_k(self, k):
        self.write("config.json", {"daily": {"min_past_trades_for_rank": k}})
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        sized = [o["symbol"] for o in self.read("orders.json")["orders"]]
        return out, sized

    def test_threshold_drives_sizing_list_and_picks(self):
        self.build_universe()
        # fixtures: CHRL +2.43R from 2 past trades (score 89.3), ALFA +0.34R from 5 (score 87.1)
        out0, sized0 = self.run_k(0)
        self.assertEqual(sized0, ["CHRL", "ALFA"])                          # best expectancy first (v0.1.4)
        self.assertEqual({r["symbol"]: r["ranked_by"] for r in out0["rows"]}, {"CHRL": "expectancy", "ALFA": "expectancy"})
        out3, sized3 = self.run_k(3)
        self.assertEqual(sized3, ["ALFA", "CHRL"])                          # ALFA has 5 >= 3, CHRL has 2: by score
        by = {r["symbol"]: r for r in out3["rows"]}
        self.assertEqual((by["ALFA"]["ranked_by"], by["CHRL"]["ranked_by"]), ("expectancy", "score"))
        self.assertEqual(by["CHRL"]["expectancy_use"], "information only (2 trades)")
        self.assertIsNotNone(by["CHRL"]["expectancy_r"])                    # still shown
        self.assertEqual(by["ALFA"]["expectancy_use"], "ranked (5 trades)")
        # the same key orders the list within each check group, and the picks are its first PASS rows
        k = out3["settings"]["values"]["daily"]["min_past_trades_for_rank"]
        rank = {"PASS": 0, "WARN": 1, "BLOCK": 2}
        exp = sorted(out3["rows"], key=lambda r: (rank.get(r["risk"], 4),) + tc.rank_key(
            r["expectancy_r"], r["past_trades"], r["score"], k))
        self.assertEqual([r["symbol"] for r in out3["rows"]], [r["symbol"] for r in exp])
        self.assertEqual(out3["top_picks"], [r["symbol"] for r in out3["rows"] if r["risk"] == "PASS"][:3])
        # the risk check saw the sizing order (it fills limits in file order)
        self.assertEqual([r["symbol"] for r in self.read("risk.json")["results"]], sized3)
        md = open(os.path.join(self.dir, "daily", out3["date"] + ".md"), encoding="utf-8").read()
        self.assertIn("information only: ranked by score", md)
        self.assertIn("at least 3 past trades", md)
        # HISTORY why[] uses the setting, not a hard 8
        hist = [w for w in by["CHRL"]["why"] if w["check"] == "past trades of this setup on this stock"][0]
        self.assertEqual((hist["limit"], hist["ok"]), (3, False))

    def test_baseline_runs_with_zero(self):
        """test_v015.BaselineIdentical.test_pipeline_identical runs the whole v0.1.4 baseline with this
        config: with the threshold at 0 every decision is the v0.1.4 one."""
        self.assertEqual(baseline.V014_ORDER, {"daily": {"min_past_trades_for_rank": 0}})
        import inspect
        self.assertIs(inspect.signature(baseline.pipeline).parameters["config"].default, baseline.V014_ORDER)

    def test_defaults_version_bump_enforced(self):
        hist = baseline.load_defaults()
        self.assertEqual(tc.DEFAULTS_VERSION, 2)
        self.assertNotIn("daily.min_past_trades_for_rank", hist["1"])
        self.assertEqual(hist["2"]["daily.min_past_trades_for_rank"], 8)
        # v2 = v1 + the new key, nothing else changed in value
        changed = sorted(k for k in hist["1"] if hist["2"].get(k) != hist["1"][k])
        self.assertEqual(changed, [])
        self.assertEqual(sorted(set(hist["2"]) - set(hist["1"])), ["daily.min_past_trades_for_rank"])
        self.assertEqual(tc.settings_snapshot(tc.validate_config({})[0])["label"], "default@2")
        # recording a changed default under the same version is refused
        saved = tc.DEFAULT_CONFIG["daily"]["min_past_trades_for_rank"]
        tc.DEFAULT_CONFIG["daily"]["min_past_trades_for_rank"] = 5
        tmp = tempfile.mkdtemp()
        try:
            dst = os.path.join(tmp, "defaults_versions.json")
            shutil.copyfile(baseline.DEFAULTS, dst)
            orig, baseline.DEFAULTS = baseline.DEFAULTS, dst
            try:
                with self.assertRaises(SystemExit) as e:
                    baseline.record_defaults()
                self.assertIn("daily.min_past_trades_for_rank", str(e.exception))
            finally:
                baseline.DEFAULTS = orig
        finally:
            tc.DEFAULT_CONFIG["daily"]["min_past_trades_for_rank"] = saved
            shutil.rmtree(tmp, ignore_errors=True)


# --- A2: source-failure banner --------------------------------------------------------------------

class SourceBanner(OfflineCase):
    def daily_with(self, fixtures, config=None):
        if config:
            self.write("config.json", config)
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=fixtures, TAYYIB_NOW=NOW)
        p = subprocess.run([sys.executable, os.path.join(ROOT, DAILY), "--no-rebuild", "--json"], capture_output=True,
                           encoding="utf-8", env=env, cwd=self.dir)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_unit(self):
        sb = sys.modules.get("daily") or _import("tayyib-daily", "daily")
        self.assertIsNone(sb.source_banner(["moneycontrol_business: offline"], ["A", "B"]))
        self.assertEqual(sb.source_banner(["nse A: HTTP 403", "nse B: HTTP 403", "nse Z: x"], ["A", "B", "C"]),
                         "NSE announcements unavailable today: HALAL-WATCH and results checks are incomplete for "
                         "2 of 3 stocks.")
        self.assertEqual(sb.source_banner(["nse A: 403", "google C: timeout"], ["A", "B", "C"]),
                         "NSE announcements and Google News unavailable today: HALAL-WATCH and results checks are "
                         "incomplete for 2 of 3 stocks.")

    def test_banner_on_nse_failure_and_verdicts_unchanged(self):
        self.build_universe()
        broken = tempfile.mkdtemp(prefix="tayyib-fix-")
        try:
            shutil.copytree(FIX, os.path.join(broken, "f"))
            shutil.rmtree(os.path.join(broken, "f", "nse"))                   # NSE announcements fail
            failed = self.daily_with(os.path.join(broken, "f"))
        finally:
            shutil.rmtree(broken, ignore_errors=True)
        n = len(failed["rows"])
        self.assertEqual(failed["banners"], ["NSE announcements unavailable today: HALAL-WATCH and results checks "
                                             "are incomplete for %d of %d stocks." % (n, n)])
        md = open(os.path.join(self.dir, "daily", failed["date"] + ".md"), encoding="utf-8").read()
        self.assertIn("NSE announcements unavailable today", md.split("# Halal trade list")[0])   # above the list
        for r in failed["rows"]:                                               # per row: UNKNOWN, not "none"
            news = [w for w in r["why"] if w["group"] == "NEWS"]
            self.assertTrue(news and all(w["ok"] is None for w in news if w["value"] is None), r["symbol"])
            self.assertTrue(any(w["ok"] is None for w in news), r["symbol"])
        # the same headlines with the source switched off: no failure, no banner, and the same verdicts
        os.remove(os.path.join(self.dir, "orders.json"))
        off = self.daily_with(FIX, {"news": {"nse_announcements": False}})
        self.assertEqual(off["banners"], [])
        verdicts = lambda o: [(r["symbol"], r["risk"], r["reasons"], r["qty"]) for r in o["rows"]]
        self.assertEqual(verdicts(failed), verdicts(off))

    def test_no_banner_without_failure_or_without_news(self):
        self.build_universe()
        self.assertEqual(self.run_script(DAILY, "--no-news", "--no-rebuild")["banners"], [])


def _import(skill, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, skill, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- A3: why[] additions (display only) ------------------------------------------------------------

class WhyAdditions(OfflineCase):
    def test_setup_context_on_every_signal(self):
        bars, _ = tc.get_daily_bars("ALFA")
        ind = tc.indicators(bars)
        n = 0
        for i in range(200, len(bars)):
            for s in ("breakout", "pullback", "oversold", "squeeze", "trend"):
                sig = tc.detect(s, bars, ind, i)
                if not sig:
                    continue
                n += 1
                ctx = {w["check"]: w for w in sig["why"] if w["op"] == "info"}
                a, r = ctx["context: close above the 200-day average"], ctx["context: 126-day return"]
                self.assertAlmostEqual(a["value"], (ind["close"][i] / tc.sma(ind["close"], 200)[i] - 1) * 100, 6)
                self.assertAlmostEqual(r["value"], (ind["close"][i] / ind["close"][i - 126] - 1) * 100, 6)
                self.assertEqual((a["ok"], a["limit"], r["ok"]), (True, None, True))
        self.assertGreater(n, 50)

    def test_capped_stop(self):
        cfg = tc.validate_config({})[0]
        sig = {"setup": "breakout", "mode": "swing", "date": "2026-10-30", "trigger": 100.0,
               "invalidation": 70.0, "atr": 12.0, "valid_days": 3}
        pl = tc.plan_trade(sig, cfg)
        cap = [w for w in pl["why"] if w.get("stop_capped")]
        self.assertEqual(len(cap), 1)
        self.assertEqual(cap[0]["note"], "chart invalidation Rs 70.00 (30.0% away); stop capped at 10%")
        self.assertEqual(pl["stop"], 90.0)
        sig2 = dict(sig, invalidation=97.0, atr=2.0)                         # chart stop inside the cap
        self.assertFalse(any(w.get("stop_capped") for w in tc.plan_trade(sig2, cfg)["why"]))
        d = dict(sig, setup="trend", mode="delivery", invalidation=60.0, atr=3.0)
        dc = [w for w in tc.plan_trade(d, cfg)["why"] if w.get("stop_capped")]
        self.assertIn("stop capped at 15%", dc[0]["note"])

    def test_near_limit(self):
        h = tc.validate_config({})[0]["halal"]
        self.assertEqual(h["near_limit_pct"], 90.0)
        ratios = {"debt_to_assets_pct": 23.0, "interest_income_pct": 1.0, "noncompliant_income_pct": 2.75,
                  "assumed_return_pct": 1.75, "cash_receivables_to_assets_pct": 40.0}
        self.assertEqual(tc.near_limits(ratios, h), ["debt_to_assets_pct", "noncompliant_income_pct"])
        w = {x["check"]: x for x in tc._ratio_why(ratios, h, "test")}
        self.assertTrue(w["debt / total assets"]["near_limit"])                 # 23 >= 0.9 x 25
        self.assertFalse(w["cash + receivables / total assets"]["near_limit"])
        self.assertEqual(w["debt / total assets"]["ok"], True)                  # the decision is unchanged
        self.assertEqual(tc.near_limits(ratios, h, near_pct=95), [])
        # an older list's recorded items get the flag from their own value and limit
        rec = {"status": "compliant", "why": [{k: v for k, v in x.items() if k != "near_limit"}
                                              for x in tc._ratio_why(ratios, h, "t")]}
        hw = {x["check"]: x for x in tc.halal_why(rec, {})}
        self.assertTrue(hw["debt / total assets"]["near_limit"])
        self.assertNotIn("halal.near_limit_pct", tc.default_values())         # display only: not in the hash

    def test_halal_list_has_near_limit_and_rows_carry_flags(self):
        self.build_universe()
        uni = self.read("halal_universe.json")
        screened = [s for s in uni["stocks"].values() if s.get("ratios")]
        self.assertTrue(screened)
        for s in screened:
            self.assertIsInstance(s["near_limit"], list)
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        for r in out["rows"]:
            self.assertIn("stop_capped", r)
            self.assertEqual(r["stop_capped"], any(w.get("stop_capped") for w in r["why"]))
            self.assertTrue(any(w["op"] == "info" for w in r["why"] if w["group"] == "SETUP"))
            for w in r["why"]:
                if w["group"] == "HALAL" and w["op"] == "<" and w["unit"] == "%":
                    self.assertIn(w["near_limit"], (True, False))


# --- Part C / D: the dashboard server ----------------------------------------------------------------

class Server(OfflineCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix="tayyib-dash-")
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
        self.srv = D.make_server(0)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, path, method="GET", host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.putrequest(method, path, skip_host=True)
        c.putheader("Host", host if host is not None else "127.0.0.1:%d" % self.port)
        c.endheaders()
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def get(self, path):
        r, body = self.req(path)
        self.assertEqual(r.status, 200, body[:300])
        return json.loads(body)

    def test_binds_localhost_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")
        self.assertEqual(D.HOST, "127.0.0.1")
        src = open(os.path.join(DASH_DIR, "dashboard.py"), encoding="utf-8").read()
        self.assertNotIn("0.0.0.0", src)
        self.assertNotIn("--host", src)
        self.assertIn("ThreadingHTTPServer((HOST, port)", src)

    def test_every_endpoint(self):
        r, body = self.req("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"tayyib dashboard", body)
        self.assertIn("text/html", r.getheader("Content-Type"))
        meta = self.get("/api/meta")
        self.assertEqual(meta["version"], tc.VERSION)
        self.assertEqual(meta["settings_header"], "Current settings: default@2")
        self.assertEqual(meta["data_dir"], os.path.abspath(self.dir))
        for k in ("banners", "halal_banner", "settings_label", "disclaimer"):
            self.assertIn(k, meta)
        self.assertEqual(meta["disclaimer"], "Not financial advice, not a fatwa.")
        self.assertEqual(self.get("/api/dates")["dates"], ["2026-10-30"])
        today = self.get("/api/today")
        self.assertEqual(today["date"], "2026-10-30")
        self.assertEqual(today["staleness"], {"stale": False, "reasons": [], "asof": "2026-10-30T18:00+05:30"})
        self.assertEqual([p["symbol"] for p in today["top_picks"]], self.read("daily/2026-10-30.json")["top_picks"])
        row = today["rows"][0]
        self.assertTrue(row["display"]["entry"].startswith("\u20b9"))
        self.assertEqual([g["group"] for g in row["why_view"]], list(tc.WHY_GROUPS))
        self.assertEqual(self.get("/api/today?date=2026-10-30")["date"], "2026-10-30")
        tr = self.get("/api/tracker")
        self.assertEqual(tr["noise_banner"], "still noise: don't judge yet (0 of 30 closed trades)")
        self.assertIn("all", tr["summary"])
        ha = self.get("/api/halal")
        self.assertEqual(ha["limits"]["max_debt_to_assets_pct"], 25.0)
        self.assertTrue(ha["stocks"])
        for s in ha["stocks"]:
            self.assertIsInstance(s["near_limit"], list)
        ti = self.get("/api/tickets")
        self.assertTrue(ti["tickets"])
        ch = self.get("/api/chart?symbol=CHRL&from=2026-10-30")
        self.assertEqual(ch["status"], "ok")
        self.assertTrue(ch["svg"]["line"])
        self.assertEqual({l["kind"] for l in ch["svg"]["levels"]}, {"entry", "stop", "target"})
        r, _ = self.req("/api/meta", method="HEAD")
        self.assertEqual(r.status, 200)

    def test_staleness(self):
        today = self.get("/api/today")
        self.assertFalse(today["staleness"]["stale"])
        d = self.read("daily/2026-10-30.json")
        d["asof"] = "2026-10-30T14:05+05:30"
        self.write("daily/2026-10-30.json", d)
        st = self.get("/api/today")["staleness"]
        self.assertTrue(st["stale"])
        self.assertIn("before the 3:30 PM close", st["reasons"][0])
        d.update(date="2026-10-29", asof="2026-10-29T18:00+05:30")
        self.write("daily/2026-10-30.json", d)
        st = self.get("/api/today")["staleness"]
        self.assertEqual(st["reasons"], ["this is the list of 2026-10-29, not today's (2026-10-30)"])

    def test_write_methods_refused(self):
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            for p in ("/", "/api/today", "/api/tickets"):
                r, _ = self.req(p, method=m)
                self.assertEqual(r.status, 405, (m, p))
                self.assertEqual(r.getheader("Allow"), "GET, HEAD")
        self.assertEqual(self.read("orders.json"), self.read("orders.json"))

    def test_bad_host_forbidden(self):
        for h in ("evil.example:%d" % self.port, "127.0.0.1:%d" % (self.port + 1), "localhost", "",
                  "127.0.0.1.evil.example:%d" % self.port, "192.168.1.5:%d" % self.port):
            for p in ("/", "/api/meta", "/api/tickets"):
                r, body = self.req(p, host=h)
                self.assertEqual(r.status, 403, (h, p))
                self.assertNotIn(b"tickets", body)
        r, _ = self.req("/api/meta", host="localhost:%d" % self.port)
        self.assertEqual(r.status, 200)

    def test_no_cors_and_safe_headers(self):
        r, _ = self.req("/api/meta")
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("connect-src 'self'", r.getheader("Content-Security-Policy"))

    def test_traversal_blocked(self):
        for p in ("/../config.json", "/%2e%2e/config.json", "/tracker.json", "/orders.json", "/daily/2026-10-30.json",
                  "/api/../tracker.json", "/index.html/../../trader/orders.json", "//etc/passwd", "/dashboard.py",
                  "/tayyib_core.py", "/C:/Windows/win.ini"):
            r, body = self.req(p)
            self.assertEqual(r.status, 404, p)
            self.assertNotIn(b'"orders"', body)
        bad = self.get("/api/today?date=../../orders")
        self.assertEqual(bad, {"error": "date must be YYYY-MM-DD"})
        self.assertIn("error", self.get("/api/chart?symbol=../../x&from=2026-10-30"))

    def test_missing_files(self):
        for f in os.listdir(self.dir):
            p = os.path.join(self.dir, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        self.assertEqual(self.get("/api/today"), {"missing": "daily/", "hint": "run tayyib-daily"})
        self.assertEqual(self.get("/api/today?date=2026-10-30"), {"missing": "daily/2026-10-30.json",
                                                                   "hint": "run tayyib-daily"})
        self.assertEqual(self.get("/api/tracker"), {"missing": "tracker.json", "hint": "run tayyib-daily"})
        self.assertEqual(self.get("/api/halal")["missing"], "halal_universe.json")
        self.assertEqual(self.get("/api/tickets"), {"missing": "orders.json", "hint": "run tayyib-daily"})
        self.assertEqual(self.get("/api/dates"), {"dates": []})
        self.assertEqual(self.get("/api/meta")["banners"], [])
        self.assertEqual(os.listdir(self.dir), [])                             # and nothing was written

    def test_null_is_unknown(self):
        d = self.read("daily/2026-10-30.json")
        r = d["rows"][0]
        for k in ("entry", "stop", "target", "stop_pct", "qty", "loss_at_stop_rs", "rr_net", "expectancy_r",
                  "past_trades", "valid_until", "verdict"):
            r[k] = None
        r["why"] = [tc.why_item("NEWS", "HALAL-WATCH news", None, None, None, None, None, "UNKNOWN: failed")]
        self.write("daily/2026-10-30.json", d)
        row = [x for x in self.get("/api/today")["rows"] if x["symbol"] == r["symbol"]][0]
        for k in ("entry", "stop", "target", "stop_pct", "qty", "loss_at_stop_rs", "rr_net", "expectancy_r",
                  "past_trades", "valid_until", "verdict"):
            self.assertEqual(row["display"][k], "UNKNOWN", k)
        it = row["why_view"][0]["items"][0]
        self.assertEqual((it["value"], it["symbol"], it["mark"]), ("UNKNOWN", "UNKNOWN", "unknown"))
        self.assertEqual(D.inr(None), "UNKNOWN")
        self.assertEqual(D.inr(0), "\u20b90.00")                               # a real zero stays a zero
        self.assertEqual(D.inr(100000), "\u20b91,00,000.00")
        self.assertEqual(D.signed_r(-1.0), "\u22121.00R")

    def test_compliance_cross_check_hides_changed_stocks(self):
        today = self.get("/api/today")
        sym = today["top_picks"][0]["symbol"]
        tickets = {t["symbol"] for t in self.get("/api/tickets")["tickets"]}
        self.assertIn(sym, tickets)
        self.write("halal_overrides.json", {sym: {"status": "excluded", "note": "new debt", "date": "2026-10-31"}})
        today = self.get("/api/today")
        row = [r for r in today["rows"] if r["symbol"] == sym][0]
        self.assertEqual(row["message"], "halal status changed since this list: re-check")
        self.assertEqual(row["halal_now"], "excluded")
        for k in ("entry", "stop", "target", "qty", "display", "why", "why_view"):
            self.assertNotIn(k, row)
        self.assertEqual(today["halal_changed"], [sym])
        self.assertTrue(all(p.get("halal_changed") for p in today["top_picks"] if p["symbol"] == sym))
        t = [x for x in self.get("/api/tickets")["tickets"] if x["symbol"] == sym][0]
        self.assertTrue(t["halal_changed"])
        for k in ("display", "steps"):
            self.assertNotIn(k, t)

    def test_tracker_summary_equals_tracker_py(self):
        old = {"date": "2026-10-01", "symbol": "OLDX", "name": "", "mode": "swing", "setup": "breakout",
               "check": "PASS", "entry": 100, "stop": 95, "target": 110, "qty": 1, "valid_until": "2026-10-06",
               "max_hold_days": 20, "status": "TARGET", "filled": "2026-10-02", "exited": "2026-10-09", "r": 1.8,
               "pnl_rs": 9.0, "settings_hash": "pre-0.1.5"}
        st = self.read("tracker.json")
        st["rows"].append(old)
        st["rows"].append(dict(old, symbol="OLDY", status="STOP", r=-1.05, pnl_rs=-5.2, exited="2026-10-05",
                               check="BLOCK"))
        self.write("tracker.json", st)
        rep = self.run_script(TR, "report")
        api = self.get("/api/tracker")
        self.assertEqual(api["summary"], rep["summary"])
        self.assertEqual(api["settings_split"], rep["settings_split"])
        self.assertEqual([p["cum_r"] for p in api["equity"]["points"]], [-1.05, 0.75])   # by exit date
        v = {r["symbol"]: r["verdict"]["verdict"] for r in api["rows"]}
        self.assertEqual((v["OLDX"], v["OLDY"]), ("right", "wrong"))
        self.assertEqual(D.verdict({"status": "TIME EXIT", "r": 0.4})["verdict"], "right")
        self.assertEqual(D.verdict({"status": "TIME EXIT", "r": -0.4})["verdict"], "wrong")
        self.assertEqual(D.verdict({"status": "NOT TRIGGERED"})["verdict"], "no trade")
        self.assertEqual(D.verdict({"status": "WAITING"})["verdict"], "pending")
        self.assertEqual(D.verdict({"status": "OPEN"})["verdict"], "pending")

    def test_chart_unavailable_is_not_drawn(self):
        st = self.read("tracker.json")
        st["rows"].append(dict(st["rows"][0], symbol="NOPE"))                 # no price fixture for it
        self.write("tracker.json", st)
        c = self.get("/api/chart?symbol=NOPE&from=%s" % st["rows"][0]["date"])
        self.assertEqual(c, {"status": "unknown", "symbol": "NOPE", "message": "price data unavailable"})
        self.assertIn("error", self.get("/api/chart?symbol=CHRL&from=2020-01-01"))   # not a tracker row

    def test_ticket_steps_are_ticket_py_text(self):
        ti = self.get("/api/tickets")
        t = [x for x in ti["tickets"] if x.get("steps")][0]
        txt = self.run_script(BR, "show", t["id"], as_json=False)
        for k, step in enumerate(t["steps"]["zerodha"], 1):
            self.assertIn("    %d. %s" % (k, step), txt)
        o = [x for x in self.read("orders.json")["orders"] if x["id"] == t["id"]][0]
        self.assertEqual(t["steps"]["groww"], tc.broker_steps(o, "groww"))

    def test_module_writes_nothing(self):
        src = open(os.path.join(DASH_DIR, "dashboard.py"), encoding="utf-8").read()
        for pat in (r"write_json", r"open\([^)]*['\"][wax]b?['\"]", r"os\.(remove|unlink|rename|replace|makedirs|mkdir)",
                    r"shutil\.", r"tc\.path\(", r"subprocess", r"\.write_text|\.write_bytes"):
            self.assertIsNone(re.search(pat, src), pat)
        self.assertIn("save=False", src)                                      # bar fetch never writes the cache
        before = sorted(os.listdir(self.dir))
        for p in ("/api/meta", "/api/today", "/api/tracker", "/api/halal", "/api/tickets",
                  "/api/chart?symbol=CHRL&from=2026-10-30"):
            self.get(p)
        self.assertEqual(sorted(os.listdir(self.dir)), before)


class NoOrderCodeInDashboard(unittest.TestCase):
    def test_page_and_server(self):
        html = open(os.path.join(DASH_DIR, "index.html"), encoding="utf-8").read()
        py = open(os.path.join(DASH_DIR, "dashboard.py"), encoding="utf-8").read()
        for src in (html.lower(), py.lower()):
            for b in ("api.kite.trade", "kite.zerodha.com/connect", "kite.trade", "api.groww.in", "groww.in/v1",
                      "groww.in/api", "kiteconnect", "growwapi", "smartapi", "place_order", "/orders/regular"):
                self.assertNotIn(b, src)
        self.assertNotIn("XMLHttpRequest", html)
        self.assertNotIn("<form", html.lower())
        self.assertNotIn("sendBeacon", html)
        self.assertNotIn("WebSocket", html)
        # v0.1.8: one fetch (request); GET everywhere except postJSON, which only goes to the two write routes
        self.assertEqual(re.findall(r"method\s*:\s*\"?(\w+)", html), ["POST"])
        self.assertEqual(re.findall(r"fetch\(([^,)]*)", html), ["url"])
        self.assertIn('return request(url, { cache:"no-store", credentials:"same-origin" });', html)
        for u in re.findall(r"getJSON\(\"([^\"]+)", html):
            self.assertTrue(u.startswith("/api/"), u)
        posts = re.findall(r"postJSON\(\"([^\"]+)", html)
        self.assertEqual(set(posts), {"/api/config", "/api/run"})
        self.assertEqual(len(re.findall(r"postJSON\(", html)), len(posts) + 1)   # + its definition: no computed URL
        self.assertIsNone(re.search(r"https?://(?!www\.w3\.org/2000/svg)", html), "external URL in the page")
        self.assertNotIn("fonts.googleapis", html)
        self.assertIn("Not financial advice, not a fatwa.", html)
        # the only action buttons copy text
        acts = re.findall(r'cls:"(copy|link)"', html)
        self.assertTrue(acts)
        labels = re.findall(r'el\("button", \{[^}]*text:"([^"]*)', html)
        self.assertTrue(labels)
        for t in labels:                                                      # Why?, Chart, Ratios, Copy ...
            if t in ("Run today's list", "Run anyway"):                       # v0.1.8: runs tayyib-daily, no order
                continue
            self.assertNotRegex(t.lower(), r"\b(buy|sell|place|cancel|modify|order|submit|run)\b", t)


if __name__ == "__main__":
    unittest.main()
