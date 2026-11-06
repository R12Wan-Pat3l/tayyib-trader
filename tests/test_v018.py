"""v0.1.8: the Settings page (POST /api/config), the Run button (POST /api/run), the security of the only two
write endpoints, and the tracker's same-day re-run under other settings (SUPERSEDED). Offline, on fixtures."""
import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.parse

from _util import FIX, NOW, OfflineCase, ROOT, tc

DASH_DIR = os.path.join(ROOT, "tayyib-dashboard")
DAILY, H = "tayyib-daily/daily.py", "tayyib-halal/halal.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D = _load("tayyib_dashboard_v018", os.path.join(DASH_DIR, "dashboard.py"))
A = D.A
TR = _load("tayyib_tracker_v018", os.path.join(ROOT, "tayyib-tracker", "tracker.py"))


def script(dirname, name, body):
    p = os.path.join(dirname, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(body))
    return p


class ServerCase(OfflineCase):
    runner_script = None

    def setUp(self):
        super().setUp()
        self.scripts = tempfile.mkdtemp(prefix="tayyib-scripts-")
        self.srv = D.make_server(0, runner=A.Runner(script=self.runner_script or os.path.join(ROOT, DAILY)))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.scripts, ignore_errors=True)
        super().tearDown()

    def req(self, path, method="GET", body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", host if host is not None else "127.0.0.1:%d" % self.port)
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        for k, v in (headers or {}).items():
            if v is not None:
                c.putheader(k, v)
        if data is not None and "Content-Length" not in (headers or {}):
            c.putheader("Content-Length", str(len(data)))
        c.endheaders()
        if data is not None:
            c.send(data)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            out = json.loads(raw) if raw else None
        except ValueError:
            out = raw
        return r, out

    def good(self, **over):
        h = {"Origin": "http://127.0.0.1:%d" % self.port, "X-Tayyib-Token": self.srv.token,
             "Content-Type": "application/json"}
        h.update(over)
        return h

    def post(self, path, body, **over):
        return self.req(path, "POST", body, self.good(**over))

    def get(self, path):
        r, out = self.req(path)
        self.assertEqual(r.status, 200, out)
        return out

    def preview(self, change):
        return self.get("/api/risk-preview?change=" + urllib.parse.quote(json.dumps(change)))

    def save(self, body):
        body = dict(body, version=A.config_version())
        return self.post("/api/config", body)


# --- A. security --------------------------------------------------------------------------------------

class WriteEndpointSecurity(ServerCase):
    def test_token_in_page_and_new_each_start(self):
        r, page = self.req("/")
        self.assertEqual(r.status, 200)
        self.assertIn(('<meta name="tayyib-token" content="%s">' % self.srv.token).encode(), page)
        self.assertNotIn(b"{{TAYYIB_TOKEN}}", page)
        other = D.make_server(0)
        try:
            self.assertNotEqual(other.token, self.srv.token)
            self.assertGreaterEqual(len(self.srv.token), 40)
        finally:
            other.server_close()

    def test_each_rejection_reason(self):
        body = {"set": {"max_open_positions": 5}, "reset": [], "version": A.config_version()}
        cases = [
            ("bad host", dict(host="evil.example:%d" % self.port), self.good(), 403),
            ("no origin", {}, self.good(Origin=None), 403),
            ("other origin", {}, self.good(Origin="http://evil.example"), 403),
            ("other port", {}, self.good(Origin="http://127.0.0.1:%d" % (self.port + 1)), 403),
            ("null origin", {}, self.good(Origin="null"), 403),
            ("no token", {}, self.good(**{"X-Tayyib-Token": None}), 403),
            ("wrong token", {}, self.good(**{"X-Tayyib-Token": "x" * 43}), 403),
            ("form post", {}, self.good(**{"Content-Type": "application/x-www-form-urlencoded"}), 415),
            ("text/plain", {}, self.good(**{"Content-Type": "text/plain"}), 415),
            ("no type", {}, self.good(**{"Content-Type": None}), 415),
            ("too big", {}, self.good(**{"Content-Length": str(64 * 1024 + 1)}), 413),
            ("no length", {}, self.good(**{"Content-Length": "abc"}), 411),
        ]
        for name, kw, headers, code in cases:
            for path in ("/api/config", "/api/run"):
                r, out = self.req(path, "POST", body, headers, **kw)
                self.assertEqual(r.status, code, (name, path, out))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))
        self.assertEqual(self.srv.runner.status()["state"], "idle")
        r, out = self.post("/api/config", b"{not json")
        self.assertEqual(r.status, 400)
        r, out = self.req("/api/config", "POST", b"x" * (64 * 1024 + 10), self.good())
        self.assertEqual(r.status, 413)

    def test_localhost_origin_allowed(self):
        r, out = self.req("/api/config", "POST", {"set": {"max_open_positions": 5}, "version": A.config_version()},
                          self.good(Origin="http://localhost:%d" % self.port), host="localhost:%d" % self.port)
        self.assertEqual(r.status, 200, out)
        self.assertTrue(out["saved"])

    def test_no_other_path_or_method_accepts_writes(self):
        paths = list(D.ROUTES) + list(D.PAGES) + ["/api/run/status", "/nope", "/api/config/", "/api/run/x",
                                                  "/api/config?x=1/../run", "/API/CONFIG"]
        for p in paths:
            if p.split("?")[0] in D.POST_ROUTES:
                continue
            r, _ = self.post(p, {"set": {}})
            self.assertEqual(r.status, 405, p)
            self.assertEqual(r.getheader("Allow"), "GET, HEAD", p)
        for m in ("PUT", "PATCH", "DELETE", "OPTIONS"):
            for p in ("/api/config", "/api/run", "/", "/api/settings"):
                r, _ = self.req(p, m, {"set": {}}, self.good())
                self.assertEqual(r.status, 405, (m, p))
        for p in D.POST_ROUTES:                                   # and a GET of a write route does nothing
            r, _ = self.req(p)
            self.assertEqual(r.status, 405)
            self.assertEqual(r.getheader("Allow"), "POST")
        self.assertEqual(D.POST_ROUTES, ("/api/config", "/api/run"))

    def test_gets_write_nothing(self):
        self.build_universe()
        before = sorted(os.listdir(self.dir))
        for p in ("/api/settings", "/api/risk-preview?change=" + urllib.parse.quote(json.dumps({"set": {"capital": 500000}})),
                  "/api/config/backups", "/api/config/backup-diff?name=config-20260101-000000.json", "/api/run/status",
                  "/api/meta"):
            self.get(p)
        self.assertEqual(sorted(os.listdir(self.dir)), before)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))


class NoOrderCodeAnywhereInTheDashboard(unittest.TestCase):
    def test_only_two_post_routes_and_no_broker_hosts(self):
        py = open(os.path.join(DASH_DIR, "dashboard.py"), encoding="utf-8").read()
        acts = open(os.path.join(DASH_DIR, "actions.py"), encoding="utf-8").read()
        html = open(os.path.join(DASH_DIR, "index.html"), encoding="utf-8").read()
        self.assertEqual(D.POST_ROUTES, ("/api/config", "/api/run"))
        self.assertEqual(len(re.findall(r"def do_POST", py)), 1)
        for src in (py.lower(), acts.lower(), html.lower()):
            for b in ("api.kite.trade", "kite.zerodha.com/connect", "kite.trade", "api.groww.in", "groww.in/v1",
                      "groww.in/api", "kiteconnect", "growwapi", "smartapi", "place_order", "/orders/regular",
                      "urlopen", "http.client", "socket."):
                self.assertNotIn(b, src, b)
        self.assertIsNone(re.search(r"https?://", acts))

    def test_actions_write_only_config_and_backups(self):
        src = open(os.path.join(DASH_DIR, "actions.py"), encoding="utf-8").read()
        self.assertEqual(re.findall(r"tc\.write_json\(([^,]+),", src), ["config_path()"])
        self.assertEqual(len(re.findall(r"open\([^)]*['\"]wb?['\"]", src)), 1)          # the backup copy
        self.assertEqual(len(re.findall(r"os\.remove\(", src)), 1)                      # pruning old backups
        self.assertEqual(re.findall(r"subprocess\.Popen\(\[?(\w+)", src), ["cmd"])
        self.assertIn("cmd = [self.python, self.script] + ([\"--no-news\"] if skip else [])", src)
        self.assertEqual(A.DAILY, os.path.join(ROOT, "tayyib-daily", "daily.py"))
        # validation is tc.validate_config, never re-implemented
        self.assertIn("tc.validate_config(user)", src)
        for bad in ("TASIS_HALAL", "_check_value", "DEFAULT_CONFIG_DOCS[k][\"min\"]", "\"max\"]"):
            self.assertNotIn(bad, src)

    def test_dashboard_module_itself_writes_nothing(self):
        src = open(os.path.join(DASH_DIR, "dashboard.py"), encoding="utf-8").read()
        for pat in (r"write_json", r"open\([^)]*['\"][wax]b?['\"]", r"os\.(remove|unlink|rename|replace|makedirs|mkdir)",
                    r"shutil\.", r"subprocess", r"\.write_text|\.write_bytes"):
            self.assertIsNone(re.search(pat, src), pat)


# --- B. settings --------------------------------------------------------------------------------------

class SettingsPage(ServerCase):
    def test_every_editable_key_rendered_once_and_grouped(self):
        s = self.get("/api/settings")
        self.assertEqual([g["title"] for g in s["groups"]],
                         ["Risk", "Plan", "Selection", "Broker & charges", "Halal", "Email", "Regime",
                          "Data & calendar"])  # Email: v0.2.3; Regime: v0.2.4
        keys = []
        for g in s["groups"]:
            for sec in g["sections"]:
                keys += [f["key"] for f in sec["fields"]] + ([sec["toggle"]["key"]] if sec.get("toggle") else [])
                for f in sec["fields"]:
                    for k in ("default", "default_text", "range_text", "changed", "value", "unit", "label"):
                        self.assertIn(k, f, f["key"])
        want = [k for k, d in tc.DEFAULT_CONFIG_DOCS.items() if d["type"] != "locked"]
        self.assertEqual(sorted(keys), sorted(want))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertNotIn("halal.require_compliant", keys)               # a hard rule, not an option
        for rule in tc.HARD_RULES:
            self.assertIn(rule, s["always_on"])
        self.assertTrue(any("compliant" in x for x in s["always_on"]))
        groups = {g["id"]: [f["key"] for sec in g["sections"] for f in sec["fields"]] for g in s["groups"]}
        self.assertIn("max_risk_per_trade_pct", groups["risk"])
        self.assertIn("modes.swing.max_stop_pct", groups["plan"])
        self.assertIn("daily.min_past_trades_for_rank", groups["selection"])
        self.assertIn("scanner.setups.breakout.max_distance_to_high_pct", groups["selection"])
        self.assertIn("charges.stt_pct", groups["broker"])
        self.assertIn("halal.loosen_note", groups["halal"])
        toggles = [sec["toggle"]["key"] for g in s["groups"] for sec in g["sections"] if sec.get("toggle")]
        self.assertEqual(sorted(toggles), sorted("scanner.setups.%s.enabled" % x for x in tc.SETUP_INFO))

    def test_changed_marker(self):
        self.write("config.json", {"max_open_positions": 4})
        s = self.get("/api/settings")
        f = [f for g in s["groups"] for sec in g["sections"] for f in sec["fields"] if f["key"] == "max_open_positions"][0]
        self.assertTrue(f["changed"] and f["saved"])
        self.assertEqual((f["value"], f["default"], f["default_text"]), (4, 6, "6 positions"))
        self.assertEqual(s["label"], tc.settings_snapshot(tc.load_config())["label"])
        self.assertNotEqual(s["label"], "default@2")

    def test_risk_preview(self):
        p = self.preview({"set": {"max_risk_per_trade_pct": 2.5}})
        pv = p["preview"]
        self.assertEqual([x["losses"] for x in pv["streaks"]], [3, 5, 10])
        self.assertEqual(pv["risk_rs"], "₹2,500")
        self.assertIn("above 2%", pv["warning"])
        self.assertEqual({x["binding"] for x in pv["samples"]} <= {"risk per trade", "max position", "both"}, True)
        self.assertTrue(p["ok"])
        self.assertEqual([d["key"] for d in p["diff"]], ["max_risk_per_trade_pct"])
        self.assertIsNone(self.preview({"set": {"max_risk_per_trade_pct": 2}})
                          ["preview"]["warning"])
        self.assertIsNone(tc.risk_preview(tc.load_config())["warning"])

    def test_save_flow(self):
        r, out = self.save({"set": {"max_open_positions": 4, "capital": 250000}})
        self.assertEqual(r.status, 200, out)
        self.assertTrue(out["saved"])
        self.assertEqual(out["message"], "Changes apply from the next run.")
        self.assertIsNone(out["backup"])                                # there was no config.json to keep
        cfg = tc.load_config()
        self.assertEqual((cfg["max_open_positions"], cfg["capital"]), (4, 250000))
        self.assertEqual(out["label"], tc.settings_snapshot(cfg)["label"])
        self.assertFalse([f for f in os.listdir(self.dir) if f.endswith(".tmp")])
        r, out = self.save({"set": {"max_open_positions": 5}, "reset": ["capital"]})
        self.assertTrue(out["saved"])
        self.assertTrue(re.match(r"config-\d{8}-\d{6}\.json$", out["backup"]))
        self.assertEqual(self.read("config.json"), {"max_open_positions": 5})
        self.assertEqual(tc.read_json(os.path.join(self.dir, "config_backups", out["backup"])),
                         {"max_open_positions": 4, "capital": 250000})

    def test_invalid_rejected_and_nothing_saved(self):
        self.write("config.json", {"max_open_positions": 4})
        before = open(os.path.join(self.dir, "config.json"), "rb").read()
        r, out = self.save({"set": {"max_risk_per_trade_pct": 9, "max_open_positions": 3}})
        self.assertEqual(r.status, 400)
        self.assertEqual(out["errors"], ["CONFIG: max_risk_per_trade_pct = 9 invalid (range 0.25–3), using default 1"])
        self.assertEqual(open(os.path.join(self.dir, "config.json"), "rb").read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config_backups")))
        for bad in ({"set": {"halal.require_compliant": False}}, {"set": {"intraday": True}},
                    {"set": {"modes.swing.product": "MIS"}}, {"reset": ["halal.require_compliant"]}, {"set": []},
                    {"set": {}, "extra": 1}):
            r, out = self.save(bad)
            self.assertEqual(r.status, 400, bad)
        self.assertEqual(open(os.path.join(self.dir, "config.json"), "rb").read(), before)
        r, out = self.save({"set": {"capital": "lots"}})
        self.assertEqual(r.status, 400)
        self.assertIn("CONFIG: capital = \"lots\" invalid", out["errors"][0])

    def test_halal_looser_needs_a_note(self):
        r, out = self.save({"set": {"halal.max_debt_to_assets_pct": 30}})
        self.assertEqual(r.status, 400)
        self.assertEqual(out["errors"], [tc.validate_config({"halal": {"max_debt_to_assets_pct": 30}})[1][0]])
        self.assertIn("needs halal.loosen_note", out["errors"][0])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))
        p = self.preview({"set": {"halal.max_debt_to_assets_pct": 30}})
        self.assertFalse(p["ok"])
        self.assertEqual(p["errors"][0]["key"], "halal.max_debt_to_assets_pct")
        ch = {"set": {"halal.max_debt_to_assets_pct": 30, "halal.loosen_note": "Mufti X, letter of 2026-10-01"}}
        p = self.preview(ch)
        self.assertTrue(p["ok"])
        self.assertEqual(p["banner"], "Halal thresholds are looser than TASIS (your setting): Mufti X, letter of 2026-10-01")
        r, out = self.save(ch)
        self.assertEqual(r.status, 200, out)
        cfg = tc.load_config()
        self.assertEqual(cfg["_halal_loosened"], "Mufti X, letter of 2026-10-01")
        self.assertEqual(self.read("config.json")["halal"]["method"], "custom")   # what the validator decided
        self.assertEqual(tc.config_notes(cfg), [])
        r, out = self.save({"set": {"halal.loosen_note": "  "}})                 # removing the note: refused
        self.assertEqual(r.status, 400)
        self.assertIn("needs halal.loosen_note", out["errors"][0])

    def test_stricter_saves_freely(self):
        r, out = self.save({"set": {"halal.max_debt_to_assets_pct": 20, "halal.max_noncompliant_income_pct": 2}})
        self.assertEqual(r.status, 200, out)
        cfg = tc.load_config()
        self.assertEqual(cfg["halal"]["max_debt_to_assets_pct"], 20)
        self.assertIsNone(cfg["_halal_loosened"])
        self.assertEqual(tc.config_notes(cfg), [])                               # method saved as custom: no note

    def test_stale_page_refused(self):
        r, out = self.post("/api/config", {"set": {"max_open_positions": 4}, "version": "0" * 12})
        self.assertEqual(r.status, 409)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))

    def test_old_and_invalid_keys_are_left_out_on_save(self):
        self.write("config.json", {"halal": {"list_url": "x", "require_compliant": True}, "capital": -5, "max_open_positions": 4})
        p = self.preview({"set": {"max_open_positions": 3}})
        self.assertTrue(p["ok"])
        self.assertEqual(len(p["dropped"]), 2)
        r, out = self.save({"set": {"max_open_positions": 3}})
        self.assertEqual(r.status, 200, out)
        self.assertEqual(self.read("config.json"), {"halal": {"require_compliant": True}, "max_open_positions": 3})

    def test_keeps_last_20_backups_and_restores(self):
        self.write("config.json", {"max_open_positions": 2})
        for k in range(23):
            r, out = self.save({"set": {"max_open_positions": 3 + k % 10}})
            self.assertEqual(r.status, 200, out)
        b = self.get("/api/config/backups")["backups"]
        self.assertEqual(len(b), 20)
        self.assertEqual(len(os.listdir(os.path.join(self.dir, "config_backups"))), 20)
        oldest = b[-1]["name"]
        want = tc.read_json(os.path.join(self.dir, "config_backups", oldest))
        diff = self.get("/api/config/backup-diff?name=" + oldest)
        self.assertTrue(diff["ok"])
        r, out = self.save({"restore": oldest})
        self.assertEqual(r.status, 200, out)
        self.assertEqual(self.read("config.json"), want)
        for bad in ("../config.json", "config-1.json", "nope"):
            r, out = self.save({"restore": bad})
            self.assertEqual(r.status, 404, bad)
        self.assertEqual(self.get("/api/config/backup-diff?name=../tracker.json"), {"error": "no such backup"})


class SettingsWording(ServerCase):
    """v0.1.8 review: the page never shows internal key names for the source note, nor the server's "using 25"."""

    def test_labels_and_messages_have_no_key_names(self):
        s = self.get("/api/settings")
        for g in s["groups"]:
            for sec in g["sections"]:
                for f in sec["fields"] + ([sec["toggle"]] if sec.get("toggle") else []):
                    self.assertNotIn("loosen_note", f["label"], f["key"])
                    self.assertNotIn("loosen_note", f.get("tasis_text") or "", f["key"])
        p = self.preview({"set": {"halal.max_debt_to_assets_pct": 30}})
        e = p["errors"][0]
        self.assertIn("needs halal.loosen_note", e["message"])                  # the validator's own words, kept
        self.assertEqual(e["text"], "30% is looser than TASIS (25%). Add your source / scholar note below to save "
                                    "this, or reset to 25%.")
        self.assertTrue(e["needs_note"])
        for t in (e["text"], e["full"]):
            self.assertNotIn("loosen_note", t)
            self.assertNotIn("using 25", t)
        e = self.preview({"set": {"halal.allow_review": True}})["errors"][0]
        self.assertIn("Add your source / scholar note below", e["text"])
        e = self.preview({"set": {"max_risk_per_trade_pct": 9}})["errors"][0]
        self.assertEqual(e["text"], "9 is not allowed (allowed: 0.25–3).")
        r, out = self.save({"set": {"halal.max_debt_to_assets_pct": 30}})
        self.assertEqual(r.status, 400)
        self.assertIn("needs halal.loosen_note", out["errors"][0])               # API keeps the validator text
        self.assertNotIn("loosen_note", " ".join(out["problems"]))              # the page shows these
        self.assertIn("your source / scholar note", out["problems"][0])
        # the CLI / daily note is unchanged
        self.assertIn("using 25", tc.validate_config({"halal": {"max_debt_to_assets_pct": 30}})[1][0])

    def test_page_shows_friendly_errors(self):
        page = open(os.path.join(DASH_DIR, "index.html"), encoding="utf-8").read()
        self.assertFalse(re.search(r"\be\.message\b", page))       # errors are shown by e.text / e.full
        self.assertNotIn("needs halal", page)


class ResetToDefaults(ServerCase):
    MINE = {"capital": 250000, "broker": "groww", "max_risk_per_trade_pct": 0.5, "max_open_positions": 4,
            "modes": {"swing": {"target_r": 2.5}}, "scanner": {"setups": {"squeeze": {"enabled": False}}},
            "halal": {"max_debt_to_assets_pct": 30, "allow_review": True, "loosen_note": "Mufti X"},
            "holidays": ["2026-11-10"]}

    def setUp(self):
        super().setUp()
        self.write("config.json", self.MINE)
        self.s = self.get("/api/settings")
        self.group = {g["id"]: g["keys"] for g in self.s["groups"]}

    def test_reset_lists(self):
        allk, acc = set(self.s["reset_all"]), set(self.s["account_keys"])
        editable = {k for k, d in tc.DEFAULT_CONFIG_DOCS.items() if d["type"] != "locked"}
        self.assertEqual(allk | acc, editable)
        self.assertFalse(allk & acc)
        self.assertTrue({"capital", "broker", "cash_available"} <= acc)
        self.assertNotIn("halal.require_compliant", allk | acc)               # hard rules are never options
        self.assertEqual({k for ks in self.group.values() for k in ks}, editable)
        self.assertIn("halal.loosen_note", self.group["halal"])
        self.assertIn("halal.allow_review", self.group["halal"])

    def test_nothing_written_without_confirmation(self):
        before = open(os.path.join(self.dir, "config.json"), "rb").read()
        p = self.preview({"reset": self.s["reset_all"] + self.s["account_keys"]})
        self.assertTrue(p["ok"])
        self.assertEqual(p["label"], "default@%d" % tc.DEFAULTS_VERSION)
        self.assertTrue(p["diff"])
        self.assertEqual(open(os.path.join(self.dir, "config.json"), "rb").read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config_backups")))
        # the page's reset only changes the form: no request is sent from it
        page = open(os.path.join(DASH_DIR, "index.html"), encoding="utf-8").read()
        body = page[page.index("function resetKeys"):page.index("function refreshField")]
        self.assertNotIn("postJSON", body)
        self.assertNotIn("request(", body)

    def test_reset_all_keeps_capital_and_broker(self):
        r, out = self.save({"reset": self.s["reset_all"]})
        self.assertEqual(r.status, 200, out)
        self.assertEqual(self.read("config.json"), {"capital": 250000, "broker": "groww"})
        self.assertEqual(out["label"], "default@%d" % tc.DEFAULTS_VERSION)
        self.assertEqual(out["account_note"], "Your own capital ₹2,50,000 and broker groww are kept: they are not "
                                              "part of the settings label.")
        self.assertTrue(re.match(r"config-\d{8}-\d{6}\.json$", out["backup"]))
        self.assertEqual(tc.read_json(os.path.join(self.dir, "config_backups", out["backup"])), self.MINE)
        cfg = tc.load_config()
        snap = tc.settings_snapshot(cfg)
        self.assertEqual(snap["label"], "default@2")
        self.assertNotEqual(snap["hash"], tc.settings_snapshot(tc.validate_config({})[0])["hash"])  # still recorded
        self.assertEqual(self.get("/api/meta")["settings_header"], "Current settings: default@2")
        # undo from Backups, through the same save
        r, out = self.save({"restore": out["backup"]})
        self.assertEqual(r.status, 200, out)
        want = json.loads(json.dumps(self.MINE))
        want["halal"]["method"] = "custom"                    # what the validator decides for looser thresholds
        self.assertEqual(self.read("config.json"), want)

    def test_reset_all_with_capital_and_broker(self):
        r, out = self.save({"reset": self.s["reset_all"] + self.s["account_keys"]})
        self.assertEqual(r.status, 200, out)
        self.assertEqual(self.read("config.json"), {})
        self.assertEqual(out["label"], "default@%d" % tc.DEFAULTS_VERSION)
        self.assertIsNone(out["account_note"])
        self.assertEqual(tc.settings_snapshot(tc.load_config())["hash"],
                         tc.settings_snapshot(tc.validate_config({})[0])["hash"])
        self.assertEqual(len(os.listdir(os.path.join(self.dir, "config_backups"))), 1)

    def test_section_reset(self):
        r, out = self.save({"reset": self.group["risk"]})
        self.assertEqual(r.status, 200, out)
        mine = self.read("config.json")
        self.assertNotIn("max_risk_per_trade_pct", mine)
        self.assertNotIn("max_open_positions", mine)
        self.assertNotIn("capital", mine)                      # the section's own reset includes capital
        self.assertEqual(mine["modes"], {"swing": {"target_r": 2.5}})            # other sections untouched
        self.assertEqual(mine["halal"]["loosen_note"], "Mufti X")
        r, out = self.save({"reset": self.group["plan"]})
        self.assertNotIn("modes", self.read("config.json"))

    def test_halal_reset_clears_the_note(self):
        r, out = self.save({"reset": self.group["halal"]})
        self.assertEqual(r.status, 200, out)
        mine = self.read("config.json")
        self.assertNotIn("halal", mine)
        cfg = tc.load_config()
        self.assertEqual({k: cfg["halal"][k] for k in tc.TASIS_HALAL}, tc.TASIS_HALAL)
        self.assertEqual((cfg["halal"]["allow_review"], cfg["halal"]["loosen_note"], cfg["halal"]["method"]),
                         (False, "", "tasis"))
        self.assertIsNone(cfg["_halal_loosened"])
        self.assertIsNone(tc.halal_banner(cfg))

    def test_reset_is_validated_like_any_save(self):
        # a reset of the note alone leaves looser thresholds without a source: refused, nothing written
        before = open(os.path.join(self.dir, "config.json"), "rb").read()
        r, out = self.save({"reset": ["halal.loosen_note"]})
        self.assertEqual(r.status, 400)
        self.assertIn("needs halal.loosen_note", " ".join(out["errors"]))
        self.assertEqual(open(os.path.join(self.dir, "config.json"), "rb").read(), before)
        r, out = self.save({"reset": ["halal.require_compliant"]})                 # a hard rule: not resettable
        self.assertEqual(r.status, 400)
        r, out = self.post("/api/config", {"reset": self.s["reset_all"], "version": "0" * 12})
        self.assertEqual(r.status, 409)                                             # stale page
        self.assertEqual(open(os.path.join(self.dir, "config.json"), "rb").read(), before)


# --- C. the Run button --------------------------------------------------------------------------------

class RunButton(ServerCase):
    def wait(self, timeout=60):
        t = time.time()
        while time.time() - t < timeout:
            s = self.get("/api/run/status")
            if s["state"] != "running":
                return s
            time.sleep(0.1)
        self.fail("run did not finish")

    def use(self, body):
        self.srv.runner.script = script(self.scripts, "fake.py", body)

    def test_ok_run_status_and_skip_news(self):
        self.use('''
            import os, sys, json
            print("args", sys.argv[1:])
            print("dir", os.environ["TAYYIB_DIR"])
            d = os.path.join(os.environ["TAYYIB_DIR"], "daily"); os.makedirs(d, exist_ok=True)
            json.dump({"date": "2026-10-30"}, open(os.path.join(d, "2026-10-30.json"), "w"))
            for k in range(300): print("line", k)
        ''')
        r, s = self.post("/api/run", {"skip_news": True})
        self.assertEqual(r.status, 200, s)
        self.assertIn(s["state"], ("running", "ok"))
        s = self.wait()
        self.assertEqual(s["state"], "ok", s)
        self.assertEqual((s["list_date"], s["returncode"], s["command"]), ("2026-10-30", 0, "tayyib-daily --no-news"))
        self.assertEqual(len(s["lines"]), 200)
        self.assertEqual(s["lines"][-1], "line 299")
        self.assertIsInstance(s["elapsed_s"], int)
        self.assertRegex(s["elapsed_text"], r"^\d+:\d\d$")
        self.use('''
            import os, sys
            print("args", sys.argv[1:])
            print("dir", os.environ["TAYYIB_DIR"])
            open(os.path.join(os.environ["TAYYIB_DIR"], "daily", "2026-10-30.json"), "w").write("{}")
        ''')
        r, s = self.post("/api/run", {})
        s = self.wait()
        self.assertEqual(s["lines"][0], "args []")
        self.assertIn("dir " + tc.data_dir(), s["lines"])
        self.assertEqual(s["command"], "tayyib-daily")

    def test_one_run_at_a_time(self):
        self.use("import time; time.sleep(3)\n")
        r, _ = self.post("/api/run", {})
        self.assertEqual(r.status, 200)
        r, out = self.post("/api/run", {})
        self.assertEqual(r.status, 409)
        self.assertIn("already", out["error"])
        self.wait()

    def test_only_skip_news_from_the_browser(self):
        for bad in ({"skip_news": "yes"}, {"args": ["--top", "50"]}, {"skip_news": True, "mode": "swing"}, [], "x"):
            r, _ = self.post("/api/run", bad)
            self.assertEqual(r.status, 400, bad)
        self.assertEqual(self.srv.runner.status()["state"], "idle")

    def test_failure_shows_the_error_and_no_list(self):
        self.use('import sys\nprint("halal list missing: run halal.py build")\nsys.exit(2)\n')
        self.post("/api/run", {})
        s = self.wait()
        self.assertEqual(s["state"], "failed")
        self.assertIn("exit code 2", s["error"])
        self.assertIn("halal list missing", s["error"])
        self.assertFalse(s["new_list"])
        self.use('print("did nothing")\n')                               # exit 0 but no list written
        self.post("/api/run", {})
        s = self.wait()
        self.assertEqual(s["state"], "failed")
        self.assertIn("wrote no list", s["error"])

    def test_confirm_before_the_close_or_on_a_holiday(self):
        cfg = tc.load_config()
        when = lambda x: tc.dt.datetime.strptime(x, "%Y-%m-%d %H:%M").replace(tzinfo=tc.IST)
        adv = A.run_advice(when("2026-10-30 11:05"), cfg)                    # a Friday morning
        self.assertTrue(adv["confirm"])
        self.assertTrue(adv["message"].startswith("Prices aren't final yet, levels may change."))
        self.assertFalse(A.run_advice(when("2026-10-30 15:30"), cfg)["confirm"])
        self.assertFalse(A.run_advice(when("2026-10-31 10:00"), cfg)["confirm"])   # Saturday: Friday's bar is final
        cfg["holidays"] = ["2026-10-30"]
        adv = A.run_advice(when("2026-10-30 18:00"), cfg)
        self.assertTrue(adv["confirm"])
        self.assertIn("holiday", adv["message"])
        self.assertFalse(self.get("/api/run/status")["advice"]["confirm"])      # NOW is 18:00: no question

    def test_real_daily_run(self):
        self.build_universe()
        r, s = self.post("/api/run", {"skip_news": True})
        self.assertEqual(r.status, 200, s)
        s = self.wait(timeout=300)
        self.assertEqual(s["state"], "ok", s["lines"][-20:])
        self.assertEqual(tc.read_json(os.path.join("daily", "2026-10-30.json"))["date"], "2026-10-30")
        self.assertTrue(self.get("/api/today")["rows"])


# --- D. tracker: same-day re-run under other settings ---------------------------------------------

def _daily(date, h, label, rows):
    return {"date": date, "settings": {"hash": h, "label": label, "differs_from_default": []},
            "rows": [dict({"name": s, "mode": "swing", "setup": "breakout", "risk": "PASS", "entry": 100.0, "stop": 95.0,
                           "target": 110.0, "qty": 10, "loss_at_stop_rs": 50, "valid_until": date, "max_hold_days": 20},
                          symbol=s) for s in rows]}


class TrackerReRun(OfflineCase):
    def add(self, store, h, label, syms):
        self.write(os.path.join("daily", "2026-10-30.json") if False else "x.json", {})
        os.makedirs(os.path.join(self.dir, "daily"), exist_ok=True)
        self.write(os.path.join("daily", "2026-10-30.json"), _daily("2026-10-30", h, label, syms))
        return TR.add_from_daily(store, "2026-10-30")

    def test_same_settings_rerun(self):
        store = TR.load()
        self.assertEqual(self.add(store, "aaaa1111", "default@2", ["A", "B"])[0], 2)
        self.assertEqual(self.add(store, "aaaa1111", "default@2", ["A", "B", "C"])[0], 1)
        self.assertEqual([r["symbol"] for r in store["rows"]], ["A", "B", "C"])
        self.assertFalse([r for r in store["rows"] if r["status"] == "SUPERSEDED"])
        self.assertEqual(store.pop("_superseded"), 0)

    def test_changed_settings_rerun(self):
        store = TR.load()
        self.add(store, "aaaa1111", "default@2", ["A", "B"])
        self.assertEqual(self.add(store, "bbbb2222", "bbbb2222", ["A", "C"])[0], 2)
        st = {(r["symbol"], r["settings_hash"]): r for r in store["rows"]}
        self.assertEqual(st[("A", "aaaa1111")]["status"], "SUPERSEDED")
        self.assertEqual(st[("B", "aaaa1111")]["superseded_by"], "bbbb2222")
        self.assertEqual(st[("A", "bbbb2222")]["status"], "WAITING")
        self.assertEqual(st[("C", "bbbb2222")]["status"], "WAITING")
        self.assertEqual(store["_superseded"], 2)
        # back to the first settings: its rows count again, the second ones are superseded
        self.add(store, "aaaa1111", "default@2", ["A", "B"])
        st = {(r["symbol"], r["settings_hash"]): r["status"] for r in store["rows"]}
        self.assertEqual(st, {("A", "aaaa1111"): "WAITING", ("B", "aaaa1111"): "WAITING",
                              ("A", "bbbb2222"): "SUPERSEDED", ("C", "bbbb2222"): "SUPERSEDED"})
        # an other day's rows are never touched
        other = dict(store["rows"][0], date="2026-10-29", settings_hash="cccc3333")
        store["rows"].append(other)
        self.add(store, "dddd4444", "dddd4444", ["A"])
        self.assertEqual(other["status"], "WAITING")

    def test_filled_rows_untouched(self):
        store = TR.load()
        self.add(store, "aaaa1111", "default@2", ["A", "B", "C"])
        a, b, c = store["rows"]
        a.update(status="OPEN", filled="2026-10-30", fill=100.0)
        b.update(status="TARGET", filled="2026-10-30", fill=100.0, exited="2026-10-30", r=2.0, pnl_rs=95.0)
        self.add(store, "bbbb2222", "bbbb2222", ["A", "B", "C", "D"])
        self.assertEqual((a["status"], b["status"], c["status"]), ("OPEN", "TARGET", "SUPERSEDED"))
        self.assertNotIn("superseded_by", a)
        syms = sorted((r["symbol"], r["settings_hash"]) for r in store["rows"])
        self.assertEqual(syms, [("A", "aaaa1111"), ("B", "aaaa1111"), ("C", "aaaa1111"), ("C", "bbbb2222"),
                                ("D", "bbbb2222")])                    # a filled pick is not added twice

    def test_summaries_exclude_superseded(self):
        store = TR.load()
        self.add(store, "aaaa1111", "default@2", ["A", "B"])
        self.add(store, "bbbb2222", "bbbb2222", ["C"])
        summ = TR.summary(store["rows"], store)
        self.assertEqual(summ["all"]["listed"], 1)
        self.assertNotIn("settings: default@2", summ)
        self.assertEqual(list(TR.settings_split(store)), ["bbbb2222"])
        TR.save(store)
        self.assertEqual(self.read("tracker.json")["summary"]["all"]["listed"], 1)
        TR.update(store, tc.load_config())                              # SUPERSEDED rows are not followed
        self.assertEqual([r["status"] for r in store["rows"] if r["symbol"] in ("A", "B")], ["SUPERSEDED"] * 2)
        TR.export(store)                                                # the Excel Summary uses summary() too
        self.assertTrue(os.path.exists(os.path.join(self.dir, "tracker.xlsx")))
        csv = open(os.path.join(self.dir, "tracker.csv"), encoding="utf-8-sig").read()
        self.assertEqual(csv.count("SUPERSEDED"), 2)                    # kept for audit in the row table
        t = D.api_tracker({})                                           # and the dashboard
        self.assertEqual((t["summary"]["all"]["listed"], t["kpis"]["tracked"], t["superseded"]), (1, "1", 2))
        self.assertEqual(sum(t["result_counts"].values()), 1)
        sup = [r for r in t["rows"] if r["superseded"]]
        self.assertEqual(len(sup), 2)
        self.assertEqual(sup[0]["verdict"]["label"], "SUPERSEDED by bbbb2222: not counted")
        self.assertEqual(sup[0]["display"]["r"], "not counted")

    def test_end_to_end_rerun_with_changed_settings(self):
        self.build_universe()
        self.run_script(DAILY, "--no-news", "--no-rebuild")
        first = tc.read_json("tracker.json")["rows"]
        self.assertTrue(first)
        self.run_script(DAILY, "--no-news", "--no-rebuild")                          # same settings: no duplicates
        self.assertEqual(len(tc.read_json("tracker.json")["rows"]), len(first))
        self.write("config.json", {"max_risk_per_trade_pct": 0.5})
        self.run_script(DAILY, "--no-news", "--no-rebuild")
        rows = tc.read_json("tracker.json")["rows"]
        old = [r for r in rows if r["settings_hash"] == first[0]["settings_hash"]]
        new = [r for r in rows if r["settings_hash"] != first[0]["settings_hash"]]
        self.assertTrue(new)
        self.assertEqual({r["status"] for r in old if not r.get("filled")}, {"SUPERSEDED"})
        self.assertEqual(tc.read_json("tracker.json")["summary"]["all"]["listed"],
                         len([r for r in rows if r["status"] != "SUPERSEDED"]))


if __name__ == "__main__":
    unittest.main()
