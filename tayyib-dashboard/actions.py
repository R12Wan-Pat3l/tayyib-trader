"""tayyib-dashboard: the only two things the dashboard can change.

1. trader/config.json, from the Settings tab: validated by tc.validate_config (the single source of truth,
   never re-implemented here), written atomically (temp file + replace), with a timestamped copy of the old
   file in trader/config_backups/ (the last 20 are kept). A refused change writes nothing.
2. A run of tayyib-daily (analysis only: it makes the daily list) or (v0.2.2) of tayyib-backtest with --write
   (it writes only trader/backtest/ and the price cache), one at a time, as a subprocess with the same Python
   and the same TAYYIB_DIR. The page can set only "skip news" for the daily list, and only years (3 or 5),
   mode (all, swing, delivery) and compare (on / off) for a backtest.
3. (v0.2.3) "Send test email": tayyib-email/email_report.py test and nothing else, refused before it starts when
   TAYYIB_SMTP_PASSWORD is not set. The password stays in the environment: never read, stored or shown here.
4. (v0.2.5) "Preview" / "Import" of a holdings export: tayyib-broker/ticket.py import FILE [--yes], only for a
   file the user saved in trader/import/ (a plain file name: no folder, no "..", no link; .csv or .xlsx). Import
   needs a Preview of the same file first (same name, same contents). No file is uploaded over HTTP. It writes
   only trader/positions.json (backed up first) and never talks to a broker.

Nothing here places, changes or cancels an order, and nothing here talks to a broker.
"""
import collections
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tayyib_core as tc  # noqa: E402

ROOT = os.path.dirname(HERE)
DAILY = os.path.join(ROOT, "tayyib-daily", "daily.py")
BACKTEST = os.path.join(ROOT, "tayyib-backtest", "backtest.py")
EMAIL = os.path.join(ROOT, "tayyib-email", "email_report.py")
TICKET = os.path.join(ROOT, "tayyib-broker", "ticket.py")
IMPORT_DIR = "import"
IMPORT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}\.(csv|xlsx)$", re.I)
NEED_PREVIEW = "Preview this file first: Import needs a Preview of the same file (same name, same contents)"
PW_ENV = "TAYYIB_SMTP_PASSWORD"
PASSWORD_MISSING = "TAYYIB_SMTP_PASSWORD is not set: see User guide, Get the list by email"
BT_YEARS = (3, 5)
BT_MODES = ("all", "swing", "delivery")
BACKUP_DIR = "config_backups"
KEEP_BACKUPS = 20
BACKUP_RE = re.compile(r"^config-\d{8}-\d{6}(-\d+)?\.json$")
APPLY_NOTE = "Changes apply from the next run."
LOG_LINES = 200


class Refused(Exception):
    """A change the server will not make: (HTTP code, message or a list of messages)."""

    def __init__(self, code, errors):
        Exception.__init__(self, errors if isinstance(errors, str) else "; ".join(errors))
        self.code = code
        self.errors = [errors] if isinstance(errors, str) else list(errors)


# --- config.json ------------------------------------------------------------------------------------

def config_path():
    return os.path.join(tc.data_dir(), "config.json")


def config_bytes():
    p = config_path()
    if not os.path.exists(p):
        return b""
    with open(p, "rb") as f:
        return f.read()


def config_version():
    """A short fingerprint of config.json as it is on disk: a save made from an older page is refused."""
    return hashlib.sha1(config_bytes()).hexdigest()[:12]


def raw_config():
    """config.json as written -> (dict, problem or None)."""
    try:
        user = tc.read_json("config.json", {})
    except ValueError as e:
        return {}, "config.json could not be read (%s)" % e
    return ({} if user is None else user), None


def editable(key):
    """v0.2.7: only the page's keys (money and risk, broker, the five strategies, holidays). The halal rules, charges
    and user agent are fixed in code; the advanced keys are for config.json only."""
    return tc.is_page_key(key)


def why_not_editable(key):
    doc = tc.DEFAULT_CONFIG_DOCS.get(key) or {}
    if doc.get("type") == "locked":
        return " (a hard rule)"
    if doc.get("fixed"):
        return " (" + tc.FIXED_NOTE + ")"
    if doc:
        return " (an advanced setting: config.json only, see TECHNICAL.md)"
    return ""


def _set(d, dotted, value):
    ks = dotted.split(".")
    for k in ks[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[ks[-1]] = value


def _prune(d, prefix=""):
    """Drop sections left empty (a fixed key that was dropped can leave "halal": {}). A documented key whose value
    is a map (news.feeds) is a setting, not a section: an empty one is kept."""
    for k in [k for k, v in d.items() if isinstance(v, dict)]:
        key = prefix + k
        if key in tc.DEFAULT_CONFIG_DOCS:
            continue
        _prune(d[k], key + ".")
        if d[k] == {}:
            d.pop(k)
    return d


def _unset(d, dotted):
    ks = dotted.split(".")
    stack = []
    for k in ks[:-1]:
        if not isinstance(d.get(k), dict):
            return
        stack.append((d, k))
        d = d[k]
    d.pop(ks[-1], None)
    for parent, k in reversed(stack):           # drop sections left empty
        if parent[k] == {}:
            parent.pop(k)


def _flat(cfg):
    """{dotted key: value} for every key a settings editor shows (the documented ones)."""
    out = {}
    for key in tc.DEFAULT_CONFIG_DOCS:
        d, ok = cfg, True
        for k in key.split("."):
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                ok = False
                break
        if ok:
            out[key] = d
    return out


def _errors_by_key(notes):
    out = []
    for n in notes:
        m = re.match(r"CONFIG(?: ERROR)?: (?:unknown key )?([A-Za-z0-9_.]+)", n)
        out.append({"key": m.group(1) if m and m.group(1) in tc.DEFAULT_CONFIG_DOCS else None, "message": n})
    return out


def plan_change(change):
    """What saving `change` = {"set": {dotted: value}, "reset": [dotted]} would do. Writes nothing.

    The new config.json is the valid part of the current one (an invalid, unknown or removed key is left out:
    every script already ignores it), plus the set values, minus the reset keys (back to the default).
    -> {ok, errors[{key, message}], user (the new config.json), cfg, diff[], dropped[], label, banner}"""
    if not isinstance(change, dict) or set(change) - {"set", "reset"}:
        raise Refused(400, "expected {\"set\": {...}, \"reset\": [...]}")
    sets, resets = change.get("set", {}), change.get("reset", [])
    if not isinstance(sets, dict) or not isinstance(resets, list):
        raise Refused(400, "set must be an object and reset a list")
    bad = [k for k in list(sets) + list(resets) if not isinstance(k, str) or not editable(k)]
    if bad:
        raise Refused(400, ["%s is not a setting you can change here%s" % (k, why_not_editable(k)) for k in bad])
    raw, problem = raw_config()
    base, dropped = tc.clean_user_config(raw)
    if problem:
        dropped = ["CONFIG: %s: it is replaced" % problem] + dropped
    old_cfg, _ = tc.validate_config(base)
    user = copy.deepcopy(base)
    for k in resets:
        _unset(user, k)
    for k, v in sets.items():
        _set(user, k, v)
    _prune(user)
    cfg, notes = tc.validate_config(user)
    errors = tc.config_errors(notes)
    before, after = _flat(old_cfg), _flat(cfg)
    diff = [{"key": k, "description": tc.DEFAULT_CONFIG_DOCS[k]["description"], "unit": tc.DEFAULT_CONFIG_DOCS[k]["unit"],
             "from": before.get(k), "to": after.get(k), "default": _flat(tc.DEFAULT_CONFIG).get(k),
             "from_text": tc._fmt_val(before.get(k)), "to_text": tc._fmt_val(after.get(k))}
            for k in tc.DEFAULT_CONFIG_DOCS if before.get(k) != after.get(k)]
    snap = tc.settings_snapshot(cfg)
    return {"ok": not errors, "errors": _errors_by_key(errors), "user": user, "cfg": cfg, "diff": diff,
            "dropped": dropped, "label": snap["label"], "label_now": tc.settings_snapshot(old_cfg)["label"],
            "banner": tc.halal_banner(cfg), "info": [n for n in notes if n not in errors], "snap": snap}


def list_backups():
    d = os.path.join(tc.data_dir(), BACKUP_DIR)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted((x for x in os.listdir(d) if BACKUP_RE.match(x)), reverse=True):
        p = os.path.join(d, f)
        st = os.stat(p)
        out.append({"name": f, "saved": dt.datetime.strptime(f[7:22], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
                    "bytes": st.st_size})
    return out


def read_backup(name):
    if not isinstance(name, str) or not BACKUP_RE.match(name) or name not in {b["name"] for b in list_backups()}:
        raise Refused(404, "no such backup")
    return tc.read_json(os.path.join(tc.data_dir(), BACKUP_DIR, name))


def restore_change(name):
    """A backup as a change: every setting it has is set, every other one goes back to its default."""
    try:
        old = read_backup(name)
    except ValueError as e:
        raise Refused(400, "the backup could not be read: %s" % e)
    kept, notes = tc.clean_user_config(old)
    if tc.config_errors(notes):
        raise Refused(400, ["the backup has settings that are no longer valid:"] + tc.config_errors(notes))
    flat = _flat(kept)
    return {"set": {k: v for k, v in flat.items() if editable(k)},
            "reset": [k for k in tc.DEFAULT_CONFIG_DOCS if editable(k) and k not in flat]}


def _backup_now():
    """Copy config.json as it is to config_backups/config-YYYYmmdd-HHMMSS.json; keep the newest 20."""
    data = config_bytes()
    if not data:
        return None
    d = os.path.join(tc.data_dir(), BACKUP_DIR)
    os.makedirs(d, exist_ok=True)
    stamp = tc.now_ist().strftime("%Y%m%d-%H%M%S")
    name, k = "config-%s.json" % stamp, 1
    while os.path.exists(os.path.join(d, name)):
        k += 1
        name = "config-%s-%d.json" % (stamp, k)
    tmp = os.path.join(d, name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(d, name))
    for old in list_backups()[KEEP_BACKUPS:]:
        os.remove(os.path.join(d, old["name"]))
    return name


_SAVE_LOCK = threading.Lock()


def save_config(body):
    """POST /api/config. body: {"set", "reset", "version"} or {"restore": NAME, "version"}.

    `version` is config_version() from when the page read the settings: a config.json changed since then
    (by hand, or in another tab) is not overwritten. -> {saved, label, backup, message, diff}"""
    if not isinstance(body, dict):
        raise Refused(400, "expected a JSON object")
    allowed = {"restore", "version"} if "restore" in body else {"set", "reset", "version"}
    if set(body) - allowed:
        raise Refused(400, "unexpected fields: %s" % ", ".join(sorted(set(body) - allowed)))
    with _SAVE_LOCK:
        if body.get("version") != config_version():
            raise Refused(409, "config.json changed since this page read it: reload the Settings tab and try again")
        change = restore_change(body["restore"]) if "restore" in body else {"set": body.get("set", {}),
                                                                           "reset": body.get("reset", [])}
        plan = plan_change(change)
        if not plan["ok"]:
            raise Refused(400, [e["message"] for e in plan["errors"]])
        # v0.2.7: on the first run (no config.json) the Welcome screen's save writes the file even with the
        # default values, or the Welcome screen would come back every time after "Saved"
        if not plan["diff"] and not plan["dropped"] and os.path.exists(config_path()):
            return {"saved": False, "label": plan["label"], "message": "Nothing changed.", "diff": []}
        backup = _backup_now()
        tc.write_json(config_path(), plan["user"])          # temp file + os.replace: never half written
        return {"saved": True, "label": plan["label"], "backup": backup, "diff": plan["diff"],
                "account": plan["snap"]["account_differs"],
                "message": APPLY_NOTE, "version": config_version()}


# --- running tayyib-daily ---------------------------------------------------------------------------

def run_advice(now=None, cfg=None):
    """Before 15:30 IST on a weekday, or on a holiday in your settings, the page asks before running."""
    now = now or tc.now_ist()
    cfg = cfg or tc.load_config()
    d = now.date()
    holiday = d.isoformat() in set(cfg.get("holidays") or [])
    if holiday:
        why = "Today, %s, is a market holiday in your settings." % d.isoformat()
    elif d.weekday() < 5 and now.hour * 60 + now.minute < 15 * 60 + 30:
        why = "The market closes at 3:30 PM IST; it is %s." % now.strftime("%I:%M %p").lstrip("0")
    else:
        return {"confirm": False, "message": None}
    return {"confirm": True, "message": "Prices aren't final yet, levels may change. " + why}


def import_dir():
    return os.path.join(tc.data_dir(), IMPORT_DIR)


def import_file(name):
    """A file name from the page -> its full path inside trader/import/, or Refused. Only a plain name of a .csv or
    .xlsx file that is there now: no folder, no '..', no drive, no link (so nothing outside the folder is read)."""
    if not isinstance(name, str) or not IMPORT_NAME_RE.match(name) or ".." in name or name != os.path.basename(name):
        raise Refused(400, "a file name from trader/import/ (.csv or .xlsx, no folders) is needed")
    d = os.path.realpath(import_dir())
    p = os.path.join(d, name)
    if os.path.islink(p) or os.path.dirname(os.path.realpath(p)) != d or not os.path.isfile(p):
        raise Refused(404, "no file %s in trader/import/" % name)
    return p


def file_sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def import_files():
    """The .csv / .xlsx files in trader/import/ (name, size, modified), newest first."""
    d = import_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if IMPORT_NAME_RE.match(f) and os.path.isfile(p) and not os.path.islink(p):
            st = os.stat(p)
            out.append({"name": f, "size_kb": max(1, int(round(st.st_size / 1024.0))), "mtime": st.st_mtime,
                        "modified": dt.datetime.fromtimestamp(st.st_mtime, tc.IST).strftime("%Y-%m-%d %H:%M")})
    return sorted(out, key=lambda x: -x["mtime"])


def import_argv(path, apply):
    """The whole command line the page can start for an import: import FILE --json [--yes]."""
    return ["import", path, "--json"] + (["--yes"] if apply else [])


def run_request(body):
    """What the page may start, strictly: {"skip_news": bool} (tayyib-daily) or
    {"backtest": {"years": 3 | 5, "mode": "all" | "swing" | "delivery", "compare": bool}} (tayyib-backtest).
    or (v0.2.3) {"email_test": true} (tayyib-email test), or (v0.2.5) {"import": {"file": NAME, "apply": bool}}
    (tayyib-broker import of a file in trader/import/). -> (kind, options). Anything else is refused."""
    if isinstance(body, dict) and "import" in body:
        b = body["import"]
        if set(body) != {"import"} or not isinstance(b, dict) or set(b) - {"file", "apply"} or \
                not isinstance(b.get("apply", False), bool):
            raise Refused(400, "an import takes only file (a name in trader/import/) and apply (true or false)")
        path = import_file(b.get("file"))
        return "import", {"file": b["file"], "path": path, "apply": bool(b.get("apply"))}
    if isinstance(body, dict) and "email_test" in body:
        if body != {"email_test": True}:
            raise Refused(400, "a test email takes no options: {\"email_test\": true}")
        return "email_test", {}
    if isinstance(body, dict) and "backtest" in body:
        b = body["backtest"]
        if set(body) != {"backtest"} or not isinstance(b, dict) or set(b) - {"years", "mode", "compare"}:
            raise Refused(400, "a backtest takes only years (3 or 5), mode (all, swing, delivery) and compare")
        years, mode, compare = b.get("years", 3), b.get("mode", "all"), b.get("compare", False)
        if isinstance(years, bool) or years not in BT_YEARS:
            raise Refused(400, "years must be 3 or 5")
        if mode not in BT_MODES:
            raise Refused(400, "mode must be all, swing or delivery")
        if not isinstance(compare, bool):
            raise Refused(400, "compare must be true or false")
        return "backtest", {"years": years, "mode": mode, "compare": compare}
    if not isinstance(body, dict) or set(body) - {"skip_news"} or not isinstance(body.get("skip_news", False), bool):
        raise Refused(400, "the only option is skip_news (true or false)")
    return "daily", {"skip_news": bool(body.get("skip_news"))}


def password_set():
    """Whether the SMTP password is in this server's environment. Only yes or no: the value is never read out."""
    return bool((os.environ.get(PW_ENV) or "").strip())


def email_argv():
    """The whole command line the page can start for email: test. Never send, never an address or a password."""
    return ["test"]


def backtest_argv(opts):
    """The whole command line a backtest from the page can have: run, --years, --mode, --compare, --write."""
    return (["run", "--years", str(opts["years"]), "--mode", opts["mode"]] + (["--compare"] if opts["compare"] else [])
            + ["--write"])


def newest_backtest(since):
    """The id of the newest trader/backtest/*.json written at or after `since` (epoch seconds), or None."""
    d = os.path.join(tc.data_dir(), "backtest")
    if not os.path.isdir(d):
        return None
    best = None
    for f in os.listdir(d):
        if f.endswith(".json"):
            m = os.path.getmtime(os.path.join(d, f))
            if m >= since - 1 and (best is None or m > best[0]):
                best = (m, f[:-5])
    return best[1] if best else None


class Runner(object):
    """One run at a time, tayyib-daily or a backtest. start() -> state; status() -> state with the last lines of
    output."""

    def __init__(self, script=DAILY, python=None, backtest_script=BACKTEST, email_script=EMAIL, ticket_script=TICKET):
        self.script = script
        self.ticket_script = ticket_script
        self.previewed = {}                         # file name -> sha1 of the contents last previewed successfully
        self.full = []
        self.backtest_script = backtest_script
        self.email_script = email_script
        self.python = python or sys.executable
        self.lock = threading.Lock()
        self.proc = None
        self.state = {"state": "idle", "started": None, "ended": None, "returncode": None, "error": None,
                      "kind": "daily", "skip_news": False, "list_date": None, "new_list": False,
                      "backtest": None, "backtest_id": None}
        self.lines = collections.deque(maxlen=LOG_LINES)
        self.t0 = self.t1 = None

    def start(self, body):
        kind, opts = run_request(body)
        if kind == "email_test" and not password_set():
            raise Refused(400, PASSWORD_MISSING)
        sha = file_sha1(opts["path"]) if kind == "import" else None
        if kind == "import" and opts["apply"] and self.previewed.get(opts["file"]) != sha:
            raise Refused(409, NEED_PREVIEW)
        with self.lock:
            if self.state["state"] == "running":
                what = {"backtest": "a backtest", "email_test": "a test email",
                        "import": "a holdings import"}.get(self.state.get("kind"), "today's list")
                raise Refused(409, "a run is already going (%s, started %s): wait for it to finish"
                              % (what, self.state["started"]))
            skip = bool(opts.get("skip_news"))
            if kind == "backtest":
                cmd = [self.python, self.backtest_script] + backtest_argv(opts)
            elif kind == "email_test":
                cmd = [self.python, self.email_script] + email_argv()
            elif kind == "import":
                cmd = [self.python, self.ticket_script] + import_argv(opts["path"], opts["apply"])
            else:
                cmd = [self.python, self.script] + (["--no-news"] if skip else [])
            env = dict(os.environ, TAYYIB_DIR=tc.data_dir(), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            self.lines.clear()
            self.full = []
            self.t0, self.t1 = time.time(), None
            self.state = {"state": "running", "started": tc.now_ist().isoformat(timespec="seconds"), "ended": None,
                          "returncode": None, "error": None, "kind": kind, "skip_news": skip, "list_date": None,
                          "new_list": False, "backtest": opts if kind == "backtest" else None, "backtest_id": None,
                          "import": {"file": opts["file"], "apply": opts["apply"], "sha1": sha} if kind == "import"
                          else None, "import_result": None}
            try:
                self.proc = subprocess.Popen(cmd, cwd=os.path.dirname(tc.data_dir()), env=env,
                                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as e:
                self.t1 = self.t0
                self.state.update(state="failed", ended=self.state["started"], error="could not start: %s" % e)
                return self.status()
            threading.Thread(target=self._follow, args=(self.proc, self.t0), daemon=True).start()
        return self.status()

    def _follow(self, proc, t0):
        for line in proc.stdout:
            self.lines.append(line.rstrip("\r\n"))
            if len(self.full) < 20000:
                self.full.append(line.rstrip("\r\n"))
        rc = proc.wait()
        if self.state.get("kind") == "import":
            return self._done_import(rc)
        if self.state.get("kind") == "backtest":
            return self._done_backtest(rc, t0)
        if self.state.get("kind") == "email_test":
            return self._done_email(rc)
        today = tc.today_ist().isoformat()
        p = os.path.join(tc.data_dir(), "daily", today + ".json")
        fresh = os.path.exists(p) and os.path.getmtime(p) >= t0 - 1
        with self.lock:
            self.t1 = time.time()
            self.state.update(ended=tc.now_ist().isoformat(timespec="seconds"), returncode=rc)
            if rc == 0 and fresh:
                self.state.update(state="ok", list_date=today, new_list=True)
            else:
                tail = [x for x in self.lines if x.strip()][-3:]
                self.state.update(state="failed", error=(
                    "tayyib-daily stopped with exit code %d: %s" % (rc, " / ".join(tail) or "no output") if rc != 0 else
                    "tayyib-daily finished but wrote no list for %s" % today))

    def _done_email(self, rc):
        with self.lock:
            self.t1 = time.time()
            self.state.update(ended=tc.now_ist().isoformat(timespec="seconds"), returncode=rc)
            tail = [x for x in self.lines if x.strip()]
            if rc == 0:
                self.state.update(state="ok", message=tail[-1] if tail else "test email sent")
            else:
                err = tail[-1] if tail else "no output"
                self.state.update(state="failed", error="the test email was not sent: " +
                                  (err[len("error: "):] if err.startswith("error: ") else err))

    def _done_import(self, rc):
        text = "\n".join(self.full)
        k = 0 if text.startswith("{") else text.find("\n{") + 1
        res = None
        if rc == 0 and k >= 0:
            try:
                res = json.loads(text[k:])
            except ValueError:
                res = None
        with self.lock:
            self.t1 = time.time()
            imp = self.state.get("import") or {}
            self.state.update(ended=tc.now_ist().isoformat(timespec="seconds"), returncode=rc)
            if rc == 0 and res is not None:
                self.state.update(state="ok", import_result=res)
                if imp.get("apply"):
                    self.previewed.pop(imp.get("file"), None)     # the next Import needs a new Preview
                else:
                    self.previewed[imp.get("file")] = imp.get("sha1")
            else:
                tail = [x for x in self.lines if x.strip()][-3:]
                err = tail[-1] if tail else "no output"
                self.state.update(state="failed", error="the import %s: %s" % (
                    "was not written" if imp.get("apply") else "preview failed",
                    err[len("error: "):] if err.startswith("error: ") else err))

    def _done_backtest(self, rc, t0):
        rid = newest_backtest(t0)
        with self.lock:
            self.t1 = time.time()
            self.state.update(ended=tc.now_ist().isoformat(timespec="seconds"), returncode=rc)
            if rc == 0 and rid:
                self.state.update(state="ok", backtest_id=rid)
            else:
                tail = [x for x in self.lines if x.strip()][-3:]
                self.state.update(state="failed", error=(
                    "tayyib-backtest stopped with exit code %d: %s" % (rc, " / ".join(tail) or "no output") if rc != 0
                    else "tayyib-backtest finished but saved no backtest"))

    def status(self):
        with self.lock:
            out = dict(self.state)
            out["elapsed_s"] = None if self.t0 is None else int((self.t1 or time.time()) - self.t0)
            out["lines"] = list(self.lines)
            if out.get("kind") == "email_test":
                out["command"] = "tayyib-email " + " ".join(email_argv())
            elif out.get("kind") == "import":
                imp = out.get("import") or {}
                out["command"] = "tayyib-broker import trader/import/%s%s" % (imp.get("file"),
                                                                            " --yes" if imp.get("apply") else "")
                out.pop("lines", None)
                out["lines"] = [x for x in self.lines if not x.startswith(("{", " ", "}", "]"))][-20:]
            elif out.get("kind") == "backtest":
                out["command"] = "tayyib-backtest " + " ".join(backtest_argv(out["backtest"]))
                prog = [x.strip() for x in out["lines"] if x.startswith("  ")]   # its progress lines (stderr)
                out["progress"] = prog[-1] if prog else None
            else:
                out["command"] = "tayyib-daily%s" % (" --no-news" if out["skip_news"] else "")
            return out
