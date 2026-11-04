"""Shared helpers: run skill scripts offline against tests/fixtures."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
NOW = "2026-10-30 18:00"          # after the close on the last fixture day (a Friday)
sys.path.insert(0, os.path.join(ROOT, "core"))
os.environ["TAYYIB_FIXTURES"] = FIX
os.environ["TAYYIB_NOW"] = NOW
import tayyib_core as tc  # noqa: E402,F401


class OfflineCase(unittest.TestCase):
    """Each test gets a fresh trader/ folder."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tayyib-test-")
        os.environ["TAYYIB_DIR"] = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_script(self, script, *args, ok=True, as_json=True):
        argv = [sys.executable, os.path.join(ROOT, script)] + [str(a) for a in args]
        if as_json:
            argv.append("--json")
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=FIX, TAYYIB_NOW=NOW)
        p = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=self.dir)
        if ok and p.returncode != 0:
            self.fail("%s %s failed:\n%s\n%s" % (script, args, p.stdout, p.stderr))
        if not ok:
            return p
        return json.loads(p.stdout) if as_json else p.stdout

    def read(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return json.load(f)

    def write(self, name, obj):
        with open(os.path.join(self.dir, name), "w") as f:
            json.dump(obj, f)

    def build_universe(self):
        return self.run_script("tayyib-halal/halal.py", "build")
