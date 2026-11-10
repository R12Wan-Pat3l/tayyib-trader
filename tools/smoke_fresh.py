#!/usr/bin/env python3
"""Fresh-install smoke test (v0.2.7): does a new copy of the repo start, with no data at all?

Standard library only, offline (nothing is fetched), places no order. It:
  1. copies this repo to a temp folder (no .git, no trader/, no caches) and uses an empty temp TAYYIB_DIR;
  2. runs `--help` on every skill script and on mcp/server.py (each must exit 0);
  3. runs the copy's `tools/sync_core.py --check` (every core copy must match);
  4. starts the copy's dashboard on a free 127.0.0.1 port (--no-browser) and checks that / serves the page,
     /api/meta has this version and first_run true (no config.json: the Welcome screen shows), every data
     endpoint answers 200 with its "missing" hint, and no GET route answers 500;
  5. stops the dashboard, checks it wrote no config.json, and deletes the temp folders.

    python3 tools/smoke_fresh.py          (Windows: py tools\\smoke_fresh.py)
    python3 tools/smoke_fresh.py --keep   keep the temp folders (their paths are printed)

Exit 0 when every check passed, 1 otherwise. Run in CI by the Tests workflow."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".git", "trader", "__pycache__", ".claude", ".pytest_cache", ".venv", "venv", "node_modules"}
# endpoints that read a data file: with an empty folder each must say what is missing (never a 500)
DATA_ENDPOINTS = ["/api/today", "/api/tracker", "/api/halal", "/api/tickets", "/api/backtests", "/api/backtest"]
# the other GET routes: must answer 200 (an error object for missing query parameters is fine)
OTHER_ENDPOINTS = ["/api/dates", "/api/settings", "/api/risk-preview", "/api/config/backups",
                   "/api/config/backup-diff", "/api/chart", "/api/run/status", "/api/import"]


def version(root):
    return re.search(r'^VERSION = "([^"]+)"', open(os.path.join(root, "core", "tayyib_core.py"),
                                                 encoding="utf-8").read(), re.M).group(1)


def copy_repo(dst):
    def ignore(d, names):
        return [n for n in names if n in SKIP or n.endswith((".pyc", ".tmp"))]
    shutil.copytree(ROOT, dst, ignore=ignore)


def scripts(root):
    out = []
    for d in sorted(os.listdir(root)):
        if not d.startswith("tayyib-") or not os.path.isdir(os.path.join(root, d)):
            continue
        helpers = {"tayyib_core.py", "actions.py", "paper.py"}      # helper modules, not scripts
        out += [os.path.join(d, f) for f in sorted(os.listdir(os.path.join(root, d)))
                if f.endswith(".py") and f not in helpers]
    return out + [os.path.join("mcp", "server.py")]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(port, path, timeout=10):
    """-> (status, body bytes). Sends Host 127.0.0.1:port, as a browser would."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Smoke:
    def __init__(self):
        self.failed = []
        self.passed = 0

    def check(self, ok, what):
        print(("  ok    " if ok else "  FAIL  ") + what)
        if ok:
            self.passed += 1
        else:
            self.failed.append(what)
        return ok


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    keep = "--keep" in argv
    base = tempfile.mkdtemp(prefix="tayyib-smoke-")
    repo = os.path.join(base, "tayyib-trader")
    data = os.path.join(base, "data", "trader")             # empty, and not created: like a new user
    env = dict(os.environ, TAYYIB_DIR=data, PYTHONIOENCODING="utf-8")
    for k in ("TAYYIB_FIXTURES", "TAYYIB_NOW", "TAYYIB_SMTP_PASSWORD"):
        env.pop(k, None)
    t = Smoke()
    proc = None
    try:
        print("tayyib-trader fresh-install smoke test")
        print("  repo copy: %s" % repo)
        print("  TAYYIB_DIR: %s (empty)" % data)
        copy_repo(repo)
        want = version(repo)
        print("  version: %s\n" % want)

        print("1. --help on every script")
        for s in scripts(repo):
            p = subprocess.run([sys.executable, os.path.join(repo, s), "--help"], cwd=base, env=env,
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
            t.check(p.returncode == 0 and p.stdout.strip(), "%s --help (exit %d)" % (s.replace(os.sep, "/"),
                                                                                     p.returncode))

        print("2. core copies")
        p = subprocess.run([sys.executable, os.path.join(repo, "tools", "sync_core.py"), "--check"], cwd=repo,
                           env=env, capture_output=True, text=True, timeout=60)
        t.check(p.returncode == 0, "sync_core.py --check: %s" % (p.stdout.strip() or p.stderr.strip()))

        print("3. dashboard on an empty data folder")
        port = free_port()
        proc = subprocess.Popen([sys.executable, os.path.join(repo, "tayyib-dashboard", "dashboard.py"),
                                 "--port", str(port), "--no-browser"], cwd=base, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        up, deadline = False, time.time() + 30
        while time.time() < deadline and proc.poll() is None:
            try:
                up = get(port, "/api/meta", timeout=2)[0] == 200
            except OSError:
                up = False
            if up:
                break
            time.sleep(0.3)
        if not t.check(up, "dashboard started on 127.0.0.1:%d" % port):
            if proc.poll() is not None:
                print(proc.stdout.read().decode("utf-8", "replace"))
            return 1
        code, body = get(port, "/")
        t.check(code == 200 and b"<html" in body.lower()[:400], "/ serves the page (HTTP %d)" % code)
        code, body = get(port, "/api/meta")
        meta = json.loads(body.decode("utf-8")) if code == 200 else {}
        t.check(meta.get("version") == want, "/api/meta version %s (want %s)" % (meta.get("version"), want))
        t.check(meta.get("first_run") is True and meta.get("setup"),
                "/api/meta first_run true with the Welcome setup (no config.json)")
        for ep in DATA_ENDPOINTS:
            code, body = get(port, ep)
            try:
                d = json.loads(body.decode("utf-8"))
            except ValueError:
                d = {}
            t.check(code == 200 and d.get("missing") and d.get("hint"),
                    "%s -> HTTP %d, missing %r, hint %r" % (ep, code, d.get("missing"), d.get("hint")))
        for ep in OTHER_ENDPOINTS:
            code, _ = get(port, ep)
            t.check(code == 200, "%s -> HTTP %d" % (ep, code))
        t.check(not os.path.exists(os.path.join(data, "config.json")), "no config.json written by starting it")
    except Exception as e:                                   # report, never a silent pass
        t.check(False, "smoke test crashed: %s: %s" % (type(e).__name__, e))
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        if proc is not None and proc.stdout:
            proc.stdout.close()
        if keep:
            print("\nkept: %s" % base)
        else:
            shutil.rmtree(base, ignore_errors=True)
    print("\n%d passed, %d failed" % (t.passed, len(t.failed)))
    for f in t.failed:
        print("  FAILED: " + f)
    return 1 if t.failed else 0


if __name__ == "__main__":
    sys.exit(main())
