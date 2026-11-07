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


class SmokeTool(unittest.TestCase):
    def test_smoke_help(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "smoke_fresh.py"), "--help"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertIn("Fresh-install smoke test", p.stdout)


if __name__ == "__main__":
    unittest.main()
