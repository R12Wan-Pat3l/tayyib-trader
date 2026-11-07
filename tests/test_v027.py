"""v0.2.7: launchers (start.sh, start.bat), current-default labels in the user docs, --help of the MCP server."""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from _util import ROOT

sys.path.insert(0, os.path.join(ROOT, "core"))
import tayyib_core as tc  # noqa: E402

# commands a launcher may use; anything else (rm, curl, pip, git, sudo, eval...) fails the test
SH_ALLOWED = {"HERE", "PY", "for", "if", "then", "fi", "done", "do", "echo", "exit", "export", "mkdir", "cd",
              "exec", "TAYYIB_DIR", "break", "else"}
BAT_ALLOWED = {"@echo", "rem", "setlocal", "endlocal", "where", "if", "echo", "pause", "exit", "for", "cd", "py",
               ")"}


def code_lines(text, comment):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(comment)]


class StartSh(unittest.TestCase):
    path = os.path.join(ROOT, "start.sh")

    def setUp(self):
        with open(self.path, "rb") as f:
            self.raw = f.read()
        self.text = self.raw.decode("utf-8")

    def test_lf_and_shebang(self):
        self.assertNotIn(b"\r\n", self.raw, "start.sh must keep LF endings (see .gitattributes)")
        self.assertTrue(self.text.startswith("#!/bin/sh\n"))

    def test_default_path(self):
        self.assertIn('TAYYIB_DIR="$HOME/tayyib-live/trader"', self.text)
        self.assertIn('if [ -z "$TAYYIB_DIR" ]', self.text)            # an existing TAYYIB_DIR wins
        self.assertIn('mkdir -p "$TAYYIB_DIR"', self.text)

    def test_runs_only_the_dashboard(self):
        for line in code_lines(self.text, "#"):
            word = re.split(r"[\s=;(]", line, maxsplit=1)[0]
            self.assertIn(word, SH_ALLOWED, "unexpected command in start.sh: %s" % line)
        runs = re.findall(r'(?:&& |exec )"\$(?:PY|c)"[^\n]*', self.text)       # every python run
        self.assertEqual(len(runs), 2, runs)                            # the version probe and the dashboard
        self.assertIn("-c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'", runs[0])
        self.assertEqual(runs[1], 'exec "$PY" "$HERE/tayyib-dashboard/dashboard.py" "$@"')
        for bad in ("rm ", "curl", "wget", "pip", "git ", "sudo", "eval", "daily.py", "chmod"):
            self.assertNotIn(bad, "\n".join(code_lines(self.text, "#")))

    def test_executable_in_git(self):
        if not os.path.isdir(os.path.join(ROOT, ".git")) or shutil.which("git") is None:
            self.skipTest("not a git checkout")
        out = subprocess.run(["git", "ls-files", "-s", "start.sh"], cwd=ROOT, capture_output=True,
                             text=True).stdout
        if not out:
            self.skipTest("start.sh not committed yet")
        self.assertTrue(out.startswith("100755"), out)

    @unittest.skipIf(os.name == "nt" or shutil.which("sh") is None, "needs a POSIX sh")
    def test_run_with_a_fake_python(self):
        """Runs start.sh with HOME in a temp folder and a fake python3 that records every call."""
        tmp = tempfile.mkdtemp(prefix="tayyib-startsh-")
        try:
            home, fake = os.path.join(tmp, "home"), os.path.join(tmp, "bin")
            os.makedirs(home)
            os.makedirs(fake)
            log = os.path.join(tmp, "calls.log")
            py = os.path.join(fake, "python3")
            with open(py, "w") as f:
                f.write('#!/bin/sh\necho "$(pwd)|$TAYYIB_DIR|$*" >> "%s"\nexit 0\n' % log)
            os.chmod(py, os.stat(py).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            env = {"HOME": home, "PATH": fake + os.pathsep + "/usr/bin:/bin"}
            p = subprocess.run(["sh", self.path, "--port", "8800"], env=env, capture_output=True, text=True,
                               timeout=30)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            data = os.path.join(home, "tayyib-live", "trader")
            self.assertTrue(os.path.isdir(data))
            calls = open(log).read().splitlines()
            self.assertEqual(len(calls), 2, calls)                     # the version probe, then the dashboard
            self.assertIn("-c import sys", calls[0])
            cwd, tdir, args = calls[1].split("|")
            self.assertEqual(os.path.realpath(cwd), os.path.realpath(os.path.join(home, "tayyib-live")))
            self.assertEqual(tdir, data)
            self.assertEqual(args, "%s --port 8800" % os.path.join(ROOT, "tayyib-dashboard", "dashboard.py"))
            # an existing TAYYIB_DIR is kept
            open(log, "w").close()
            other = os.path.join(tmp, "elsewhere", "trader")
            env["TAYYIB_DIR"] = other
            subprocess.run(["sh", self.path], env=env, capture_output=True, timeout=30)
            self.assertTrue(os.path.isdir(other))
            self.assertEqual(open(log).read().splitlines()[1].split("|")[1], other)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class StartBat(unittest.TestCase):
    def test_default_path_and_only_the_dashboard(self):
        with open(os.path.join(ROOT, "start.bat"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('if not defined TAYYIB_DIR set "TAYYIB_DIR=%USERPROFILE%\\tayyib-live\\trader"', text)
        lines = code_lines(text, "rem ")
        for line in lines:
            self.assertIn(line.split()[0].lower(), BAT_ALLOWED, "unexpected command in start.bat: %s" % line)
        runs = [l for l in lines if l.lower().startswith("py ")]
        self.assertEqual(runs, ['py "%~dp0tayyib-dashboard\\dashboard.py" %*'])


class DocsCurrentDefault(unittest.TestCase):
    """The user docs never call an older default@N 'the defaults' (v0.2.7: several still said default@2)."""
    DOCS = ["README.md", os.path.join("docs", "USER_GUIDE.md"), os.path.join("docs", "HOW_IT_WORKS.md")]
    # words that mark an older label as history, within the same sentence
    HISTORIC = re.compile(r"older|earlier|before|historic|was |were |used to|equals|= ?`?default@|same as|"
                          r"same decisions|v0\.\d|default@\d`? (?:lists|rows)|known label|still labelled|"
                          r"labelled `default@\d` in the\s+tracker", re.I)
    # phrases that state the current default
    CURRENT = re.compile(r"(?:now|currently|current settings:?|is|code is|labelled)\s+`?default@(\d+)"
                         r"|default@(\d+)`?\s+(?:when you changed nothing|when nothing differs|\(the defaults\))",
                         re.I)

    def sentences(self, text):
        return re.split(r"(?<=[.!?])\s+|\n\s*\n|\n\s*[-|*]\s", text)

    def test_no_stale_current_default(self):
        cur = str(tc.DEFAULTS_VERSION)
        for name in self.DOCS:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for m in self.CURRENT.finditer(text):
                n = m.group(1) or m.group(2)
                ctx = text[max(0, m.start() - 80):m.end() + 40].replace("\n", " ")
                self.assertEqual(n, cur, "%s calls default@%s the current default (DEFAULTS_VERSION %s): ...%s..."
                                 % (name, n, cur, ctx))
            for s in self.sentences(text):
                for n in re.findall(r"default@(\d+)", s):
                    if n != cur:
                        self.assertRegex(s, self.HISTORIC, "%s mentions default@%s (current is default@%s) "
                                         "without saying it is older: %r" % (name, n, cur, s.strip()[:200]))

    def test_the_check_catches_a_stale_label(self):
        bad = "Every list records `default@2` when you changed nothing."
        self.assertTrue(any((m.group(1) or m.group(2)) != str(tc.DEFAULTS_VERSION)
                            for m in self.CURRENT.finditer(bad)))
        self.assertIsNone(self.HISTORIC.search("Your settings are the defaults, default@2."))


class Release(unittest.TestCase):
    def test_version(self):
        self.assertEqual(tc.VERSION, "0.2.7")
        self.assertEqual(tc.DEFAULTS_VERSION, 5)                       # simple settings, halal locked, no overrides
        for f in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
            with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
                self.assertIn('"0.2.7"', fh.read())


class McpHelp(unittest.TestCase):
    def test_help_and_version(self):
        server = os.path.join(ROOT, "mcp", "server.py")
        p = subprocess.run([sys.executable, server, "--help"], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("none of which place orders", p.stdout)
        p = subprocess.run([sys.executable, server, "--version"], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(p.stdout.strip(), tc.VERSION)


class WelcomeSaveDefaults(unittest.TestCase):
    """Fresh-install walkthrough: the Welcome screen's Save with the default values wrote no config.json, so the
    Welcome screen came back after "Saved ✓". On the first run it now writes the file."""

    def setUp(self):
        import importlib.util
        self.dir = tempfile.mkdtemp(prefix="tayyib-test-")
        self.old = os.environ.get("TAYYIB_DIR")
        os.environ["TAYYIB_DIR"] = self.dir
        spec = importlib.util.spec_from_file_location("tayyib_actions_v027",
                                                      os.path.join(ROOT, "tayyib-dashboard", "actions.py"))
        self.A = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.A)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TAYYIB_DIR", None)
        else:
            os.environ["TAYYIB_DIR"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_first_save_with_defaults_writes_config(self):
        A = self.A
        self.assertFalse(os.path.exists(A.config_path()))
        r = A.save_config({"version": A.config_version(), "set": {"capital": 100000}, "reset": []})
        self.assertTrue(r["saved"], r)
        self.assertTrue(os.path.exists(A.config_path()))
        self.assertEqual(tc.settings_snapshot(tc.load_config())["label"], "default@%d" % tc.DEFAULTS_VERSION)
        # once the file exists, the same save again changes nothing and writes nothing
        before = A.config_bytes()
        r = A.save_config({"version": A.config_version(), "set": {"capital": 100000}, "reset": []})
        self.assertFalse(r["saved"])
        self.assertEqual(A.config_bytes(), before)


class WeekendNotStale(unittest.TestCase):
    """Fresh-install walkthrough: a list made on a Saturday at 13:29 said "before the 3:30 PM close: levels can
    move". On a weekend (or a holiday in the settings) the last close is final."""

    def test_weekend_morning_is_not_before_the_close(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("tayyib_dashboard_v027",
                                                      os.path.join(ROOT, "tayyib-dashboard", "dashboard.py"))
        D = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(D)
        import datetime as dt
        with mock.patch.object(D.tc, "today_ist", lambda: dt.date(2026, 11, 7)), \
                mock.patch.object(D.tc, "load_config", lambda *a, **k: {"holidays": ["2026-11-09"]}):
            sat = D.staleness({"date": "2026-11-07", "asof": "2026-11-07T13:29+05:30"})
            self.assertFalse(sat["stale"], sat)
            fri = D.staleness({"date": "2026-11-07", "asof": "2026-11-06T13:29+05:30"})
            self.assertTrue(any("before the 3:30 PM close" in r for r in fri["reasons"]), fri)
            hol = D.staleness({"date": "2026-11-07", "asof": "2026-11-09T10:00+05:30"})
            self.assertFalse(any("before the 3:30 PM close" in r for r in hol["reasons"]), hol)


class NiftyIndicesUserAgent(unittest.TestCase):
    """Fresh-install walkthrough: niftyindices.com reset every request whose user agent had a URL in it, so a new
    user's first halal build always failed. The Nifty 500 download now sends the honest name without the link."""

    def test_index_download_sends_name_without_link(self):
        import importlib.util
        import io
        import urllib.error
        import urllib.request
        from unittest import mock
        self.assertEqual(tc.INDEX_HEADERS["User-Agent"], "tayyib-trader/" + tc.VERSION)
        sent = []

        def urlopen(req, timeout=None):
            sent.append(req)
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
        spec = importlib.util.spec_from_file_location("tayyib_halal_v027", os.path.join(ROOT, "tayyib-halal", "halal.py"))
        H = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(H)
        tmp = tempfile.mkdtemp(prefix="tayyib-test-")
        old = os.environ.get("TAYYIB_DIR")
        os.environ["TAYYIB_DIR"] = tmp
        try:
            with mock.patch.object(H.tc, "fixtures_dir", lambda: None), \
                    mock.patch.object(urllib.request, "urlopen", urlopen):
                with self.assertRaises(H.NoParentList):
                    H.load_parent("https://niftyindices.com/IndexConstituent/ind_nifty500list.csv", "index/nifty500.csv")
        finally:
            if old is None:
                os.environ.pop("TAYYIB_DIR", None)
            else:
                os.environ["TAYYIB_DIR"] = old
            shutil.rmtree(tmp, ignore_errors=True)
        ua = dict((k.lower(), v) for k, v in sent[0].header_items())["user-agent"]
        self.assertEqual(ua, "tayyib-trader/" + tc.VERSION)
        self.assertNotIn("http", ua)
        self.assertNotIn("Mozilla", ua)


# --- simple settings, halal locked, no overrides (owner decision, v0.2.7) -------------------------------------------

def _load(name, rel):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIX = os.path.join(ROOT, "tests", "fixtures")
NOW = "2026-10-30 18:00"
STRATS = ("trend", "breakout", "pullback", "oversold", "squeeze")


class TempDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tayyib-test-")
        self.old = os.environ.get("TAYYIB_DIR")
        os.environ["TAYYIB_DIR"] = self.dir

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TAYYIB_DIR", None)
        else:
            os.environ["TAYYIB_DIR"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, obj):
        import json
        p = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def run_script(self, script, *args, ok=True):
        import json
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=FIX, TAYYIB_NOW=NOW, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, os.path.join(ROOT, script)] + [str(a) for a in args] + ["--json"],
                           capture_output=True, encoding="utf-8", env=env, cwd=self.dir, timeout=900)
        if ok and p.returncode != 0:
            self.fail("%s %s failed:\n%s\n%s" % (script, args, p.stdout, p.stderr))
        return (json.loads(p.stdout), p.stderr) if ok else p


LOCKED = {"halal": {"max_debt_to_assets_pct": 33, "max_noncompliant_income_pct": 5,
                    "max_cash_receivables_to_assets_pct": 95, "noncompliant_investment_return_pct": 4,
                    "method": "custom", "allow_review": True, "loosen_note": "my scholar",
                    "parent_list_url": "https://example.com/list.csv"},
          "charges": {"stt_pct": 0.0}, "brokers": {"zerodha": {"dp_charge_per_sell": 0}},
          "user_agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120"}


class SettingsPage(TempDir):
    def test_only_the_allowed_groups_and_fields(self):
        D = _load("tayyib_dashboard_v027s", os.path.join("tayyib-dashboard", "dashboard.py"))
        d = D.api_settings({})
        self.assertEqual([g["id"] for g in d["groups"]], ["money", "broker", "strategies", "holidays"])
        keys = {g["id"]: [f["key"] for s in g["sections"] for f in s["fields"]] for g in d["groups"]}
        self.assertEqual(keys, {
            "money": ["capital", "max_risk_per_trade_pct", "max_position_pct", "max_open_positions"],
            "broker": ["broker"],
            "strategies": ["scanner.setups.%s.enabled" % s for s in STRATS],
            "holidays": ["holidays"]})
        f = {f["key"]: f for g in d["groups"] for s in g["sections"] for f in s["fields"]}
        self.assertEqual(f["broker"]["choices"], ["zerodha", "groww"])
        self.assertEqual((f["max_risk_per_trade_pct"]["min"], f["max_risk_per_trade_pct"]["max"]), (0.25, 3))
        self.assertEqual((f["max_position_pct"]["min"], f["max_position_pct"]["max"]), (5, 40))
        self.assertEqual((f["max_open_positions"]["min"], f["max_open_positions"]["max"]), (1, 20))
        self.assertEqual([f["scanner.setups.%s.enabled" % s]["label"] for s in STRATS],
                         ["Trend (delivery)", "Breakout (swing)", "Pullback (swing)", "Oversold (swing)", "Squeeze (swing)"])
        self.assertTrue(all(f["scanner.setups.%s.enabled" % s]["hint"] and f["scanner.setups.%s.enabled" % s]["value"]
                            for s in STRATS))
        self.assertIn("Debt under 25% of total assets", d["halal"]["rules"])
        self.assertTrue(any("8%" in r for r in d["halal"]["rules"]))
        self.assertTrue(any("eview stocks are blocked" in r for r in d["halal"]["rules"]))
        self.assertEqual(d["halal"]["fixed"], "These rules can't be changed in the app.")
        self.assertTrue(any("CNC" in r for r in d["always_on"]))
        self.assertTrue(any("fixed in the code" in r for r in d["always_on"]))
        self.assertIsNotNone(d["preview"])
        self.assertNotIn("email", d)
        self.assertEqual(set(d["reset_all"]) | set(d["account_keys"]), set(tc.PAGE_KEYS))
        for gone in ("modes.swing.target_r", "min_turnover_rs", "daily.top", "email.enabled", "regime.enabled",
                     "news.feeds", "user_agent", "halal.max_debt_to_assets_pct", "charges.stt_pct",
                     "scanner.setups.breakout.min_score"):
            self.assertNotIn(gone, f)

    def test_page_refuses_everything_else(self):
        A = _load("tayyib_actions_v027s", os.path.join("tayyib-dashboard", "actions.py"))
        for key, v in (("halal.max_debt_to_assets_pct", 30), ("charges.stt_pct", 0), ("user_agent", "x"),
                       ("min_reward_risk", 2), ("email.enabled", True), ("halal.require_compliant", False)):
            with self.assertRaises(A.Refused) as cm:
                A.plan_change({"set": {key: v}, "reset": []})
            self.assertIn("not a setting you can change here", str(cm.exception.errors))
        bad = A.plan_change({"set": {"broker": "custom"}, "reset": []})
        self.assertFalse(bad["ok"])
        off = A.plan_change({"set": {"scanner.setups.%s.enabled" % s: False for s in STRATS}, "reset": []})
        self.assertFalse(off["ok"])
        self.assertEqual(off["errors"][0]["key"], "scanner.setups.trend.enabled")
        one = A.plan_change({"set": {"scanner.setups.%s.enabled" % s: s == "trend" for s in STRATS}, "reset": []})
        self.assertTrue(one["ok"], one["errors"])
        ok = A.plan_change({"set": {"capital": 250000, "broker": "groww", "holidays": ["2026-11-10"]}, "reset": []})
        self.assertTrue(ok["ok"])
        r = A.save_config({"version": A.config_version(), "set": {"max_position_pct": 25}, "reset": []})
        self.assertTrue(r["saved"])
        r = A.save_config({"version": A.config_version(), "set": {}, "reset": ["max_position_pct"]})   # reset works
        self.assertTrue(r["saved"])

    def test_advanced_note_only_for_hidden_keys(self):
        D = _load("tayyib_dashboard_v027a", os.path.join("tayyib-dashboard", "dashboard.py"))
        self.write("config.json", {"capital": 300000, "broker": "groww", "max_open_positions": 4,
                                   "scanner": {"setups": {"squeeze": {"enabled": False}}}, "holidays": ["2026-11-10"]})
        self.assertIsNone(D.api_settings({})["advanced"]["note"])
        self.write("config.json", dict(LOCKED, capital=300000))                    # fixed keys are not "advanced"
        self.assertIsNone(D.api_settings({})["advanced"]["note"])
        self.write("config.json", {"min_reward_risk": 2, "modes": {"swing": {"target_r": 3}}, "email": {"enabled": True}})
        adv = D.api_settings({})["advanced"]
        self.assertEqual(adv["count"], 2)                                            # email is outside the label
        self.assertTrue(adv["note"].startswith("Advanced settings changed in config.json: 2 (see TECHNICAL.md)"))
        self.assertEqual(sorted(k["key"] for k in adv["keys"]), ["min_reward_risk", "modes.swing.target_r"])


class LockedKeys(TempDir):
    def test_validate_config_refuses_every_locked_key(self):
        cfg, notes = tc.validate_config(LOCKED)
        self.assertEqual({k: cfg["halal"][k] for k in tc.TASIS_HALAL}, tc.TASIS_HALAL)
        self.assertEqual((cfg["halal"]["method"], cfg["halal"]["allow_review"]), ("tasis", False))
        self.assertEqual(cfg["halal"]["parent_list_url"], tc.DEFAULT_CONFIG["halal"]["parent_list_url"])
        self.assertEqual(cfg["charges"], tc.DEFAULT_CONFIG["charges"])
        self.assertEqual(cfg["brokers"], tc.DEFAULT_CONFIG["brokers"])
        self.assertEqual(cfg["user_agent"], tc.HONEST_UA)
        self.assertNotIn("loosen_note", cfg["halal"])
        fixed = [n for n in notes if tc.FIXED_NOTE in n]
        self.assertEqual(len(fixed), 10, notes)                 # 4 limits, method, review, list URL, stt, dp, UA
        self.assertTrue(any("halal.loosen_note removed" in n for n in notes))
        self.assertIsNone(cfg["_halal_loosened"])
        self.assertIsNone(tc.halal_banner(cfg))
        self.assertEqual(tc.settings_snapshot(cfg)["label"], "default@%d" % tc.DEFAULTS_VERSION)
        # the same value as the code is simply dropped, without a note (a config.json written by an older version)
        cfg2, notes2 = tc.validate_config({"halal": {"max_debt_to_assets_pct": 25.0, "allow_review": False}})
        self.assertEqual(notes2, [])

    def test_custom_broker_refused(self):
        self.assertNotIn("custom", tc.DEFAULT_CONFIG["brokers"])
        self.assertEqual(tc.DEFAULT_CONFIG_DOCS["broker"]["choices"], ["zerodha", "groww"])
        cfg, notes = tc.validate_config({"broker": "custom"})
        self.assertEqual(cfg["broker"], "zerodha")
        self.assertTrue(any(n.startswith("CONFIG: broker = \"custom\" invalid") for n in notes))
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tayyib-budget", "size.py"), "--broker", "custom"],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)

    def test_at_least_one_strategy(self):
        cfg, notes = tc.validate_config({"scanner": {"setups": {s: {"enabled": False} for s in STRATS}}})
        self.assertIn(tc.STRATEGY_ERROR, notes)
        self.assertTrue(all(cfg["scanner"]["setups"][s]["enabled"] for s in STRATS))
        cfg, notes = tc.validate_config({"scanner": {"setups": {s: {"enabled": s == "oversold"} for s in STRATS}}})
        self.assertEqual(notes, [])

    def test_cli_ignores_locked_keys(self):
        self.write("config.json", LOCKED)
        out, err = self.run_script("tayyib-daily/daily.py", "--risk-preview")
        self.assertTrue(any(tc.FIXED_NOTE in n for n in out["config_notes"]))
        b, err = self.run_script("tayyib-halal/halal.py", "build")
        self.assertIn(tc.FIXED_NOTE, err)                                            # every script reports it
        with open(os.path.join(self.dir, "halal_universe.json"), encoding="utf-8") as f:
            import json
            uni = json.load(f)
        self.assertEqual(uni["thresholds"], tc.TASIS_HALAL)
        self.assertEqual(uni["method"], "TASIS-style")
        self.assertNotIn("loosened", uni)

    def test_mcp_ignores_locked_keys(self):
        import json
        self.write("config.json", LOCKED)
        M = _load("tayyib_mcp_v027", os.path.join("mcp", "server.py"))
        old = {k: os.environ.get(k) for k in ("TAYYIB_FIXTURES", "TAYYIB_NOW")}
        os.environ.update(TAYYIB_FIXTURES=FIX, TAYYIB_NOW=NOW)
        try:
            names = [t["name"] for t in M.handle({"id": 1, "method": "tools/list"})["tools"]]
            self.assertFalse([n for n in names if "override" in n or "config" in n])
            r = M.handle({"id": 2, "method": "tools/call", "params": {"name": "halal_build", "arguments": {}}})
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertFalse(r["isError"], r)
        out = json.loads(r["content"][0]["text"])
        self.assertTrue(any(tc.FIXED_NOTE in n for n in out["config_notes"]))
        with open(os.path.join(self.dir, "halal_universe.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["thresholds"], tc.TASIS_HALAL)

    def test_user_agent_cannot_change(self):
        import urllib.request
        from unittest import mock
        self.write("config.json", {"user_agent": "Mozilla/5.0"})
        cfg = tc.load_config()
        self.assertEqual(cfg["user_agent"], tc.HONEST_UA)
        self.assertEqual(tc.DEFAULT_CONFIG["user_agent"], tc.HONEST_UA)
        sent = []

        class R:
            status = 200
            headers = {}

            def read(self):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=None):
            sent.append(dict((k.lower(), v) for k, v in req.header_items()))
            return R()
        with mock.patch.object(tc, "fixtures_dir", lambda: None), mock.patch.object(urllib.request, "urlopen", urlopen):
            tc.fetch("https://query1.finance.yahoo.com/x")
        self.assertEqual(sent[0]["user-agent"], tc.HONEST_UA)
        self.assertNotIn("Mozilla", sent[0]["user-agent"])


class NoOverrides(TempDir):
    OV = {"ALFA": {"status": "excluded", "note": "my scholar", "date": "2026-11-01"},
          "ITC": {"status": "compliant", "note": "test", "date": "2026-11-01"}}

    def test_overrides_ignored_never_written_and_one_note(self):
        import json
        p = self.write("halal_overrides.json", self.OV)
        with open(p, "rb") as f:
            before = f.read()
        b, _ = self.run_script("tayyib-halal/halal.py", "build")
        self.assertNotIn("counts_with_overrides", b)
        self.assertIn(tc.OVERRIDES_NOTE, b["notes"])
        uni = tc.load_universe()
        self.assertEqual(tc.halal_status("ALFA", uni)["status"], uni["stocks"]["ALFA"]["status"])
        self.assertEqual(tc.halal_status("ITC", uni)["status"], "excluded")
        self.assertNotIn("override", tc.halal_status("ALFA", uni))
        self.assertFalse([x for x in tc.halal_why(tc.halal_status("ALFA", uni), uni) if "override" in x["check"]])
        daily, _ = self.run_script("tayyib-daily/daily.py", "--no-news")
        self.assertEqual(daily["notes"].count(tc.OVERRIDES_NOTE), 1)
        D = _load("tayyib_dashboard_v027o", os.path.join("tayyib-dashboard", "dashboard.py"))
        h = D.api_halal({})
        self.assertFalse([s for s in h["stocks"] if "override" in s])
        with open(p, "rb") as f:
            self.assertEqual(f.read(), before)                                       # never written
        # no override command, no --accept-income-reviews
        for argv in (["override", "ALFA", "--status", "excluded"], ["compare", "x.csv", "--accept-income-reviews"]):
            q = subprocess.run([sys.executable, os.path.join(ROOT, "tayyib-halal", "halal.py")] + argv,
                               capture_output=True, text=True, cwd=self.dir, env=dict(os.environ, TAYYIB_DIR=self.dir))
            self.assertEqual(q.returncode, 2, q.stderr)
        os.remove(p)
        self.assertIsNone(tc.old_overrides_note())

    def test_no_code_reads_the_file(self):
        hits = []
        for d in sorted(os.listdir(ROOT)):
            if not (d.startswith("tayyib-") or d in ("mcp", "core")):
                continue
            for fn in os.listdir(os.path.join(ROOT, d)):
                if fn.endswith(".py") and fn != "tayyib_core.py" or (d == "core" and fn == "tayyib_core.py"):
                    with open(os.path.join(ROOT, d, fn), encoding="utf-8") as f:
                        src = f.read()
                    if re.search(r"read_json\([\"']halal_overrides|write_json\([\"']halal_overrides", src):
                        hits.append(os.path.join(d, fn))
        self.assertEqual(hits, [])


class BacktestMaxPositions(TempDir):
    def test_follows_config(self):
        self.run_script("tayyib-halal/halal.py", "build")
        self.write("config.json", {"max_open_positions": 3})
        res, _ = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1")
        self.assertEqual(res["params"]["max_positions"], 3)
        self.assertEqual(res["params"]["max_positions_from"], "config max_open_positions")
        res, _ = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", "--max-positions", "2")
        self.assertEqual((res["params"]["max_positions"], res["params"]["max_positions_from"]), (2, "--max-positions"))
        os.remove(os.path.join(self.dir, "config.json"))
        res, _ = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1")
        self.assertEqual(res["params"]["max_positions"], tc.DEFAULT_CONFIG["max_open_positions"])   # 6, not 5


class DefaultsV5(unittest.TestCase):
    def test_label_history_and_values(self):
        import baseline
        self.assertEqual(tc.DEFAULTS_VERSION, 5)
        self.assertIn(5, tc.DEFAULTS_HISTORY)
        snap = tc.settings_snapshot(tc.validate_config({})[0])
        self.assertEqual((snap["label"], snap["same_as"]), ("default@5", "default@2"))
        hist = baseline.load_defaults()
        self.assertEqual(hist["5"], tc.default_values())
        gone = sorted(set(hist["4"]) - set(hist["5"]))
        self.assertTrue(gone and all(k.startswith("brokers.custom.") or k == "halal.loosen_note" for k in gone), gone)
        self.assertEqual({k: hist["4"][k] for k in hist["5"] if k in hist["4"]},
                         {k: hist["5"][k] for k in hist["5"] if k in hist["4"]})        # every other value unchanged

    def test_default5_decisions_equal_default4_with_the_same_halal_list(self):
        """The fixtures build the same halal list in both versions (no overrides file): every decision of the
        full daily pipeline is the default@4 (= default@2) one. The new snapshot is that pipeline, byte for byte."""
        import baseline
        d2, d5 = baseline.load_default_snapshot(2), baseline.load_default_snapshot(5)
        self.assertEqual(d5["defaults_version"], 5)
        self.assertEqual(baseline.diff(d2["pipeline"], d5["pipeline"], new_keys=frozenset()), [])
        self.assertEqual(baseline.digest(d5["pipeline"]), baseline.digest(d2["pipeline"]))
        cur = baseline.pipeline(config=None)
        self.assertEqual(baseline.digest(cur), baseline.digest(d5["pipeline"]))


class SmokeTool(unittest.TestCase):
    def test_smoke_help(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "smoke_fresh.py"), "--help"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertIn("Fresh-install smoke test", p.stdout)


if __name__ == "__main__":
    unittest.main()
