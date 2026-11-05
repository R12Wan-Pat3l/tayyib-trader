"""tayyib-dashboard: the only two things the dashboard can change.

1. trader/config.json, from the Settings tab: validated by tc.validate_config (the single source of truth,
   never re-implemented here), written atomically (temp file + replace), with a timestamped copy of the old
   file in trader/config_backups/ (the last 20 are kept). A refused change writes nothing.
2. A run of tayyib-daily (analysis only: it makes the daily list), one at a time, as a subprocess with the
   same Python and the same TAYYIB_DIR. The only option the page can set is "skip news".

Nothing here places, changes or cancels an order, and nothing here talks to a broker.
"""
import collections
import copy
import datetime as dt
import hashlib
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
    doc = tc.DEFAULT_CONFIG_DOCS.get(key)
    return doc is not None and doc["type"] != "locked"


def _set(d, dotted, value):
    ks = dotted.split(".")
    for k in ks[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[ks[-1]] = value


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
        raise Refused(400, ["%s is not a setting you can change here%s" % (k, " (a hard rule)" if (
            tc.DEFAULT_CONFIG_DOCS.get(k) or {}).get("type") == "locked" else "") for k in bad])
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
    cfg, notes = tc.validate_config(user)
    errors = tc.config_errors(notes)
    # the validator switches halal.method to "custom" when a threshold differs from TASIS: save what it decided
    if not errors and cfg["halal"]["method"] != (user.get("halal") or {}).get("method", tc.DEFAULT_CONFIG["halal"]["method"]):
        _set(user, "halal.method", cfg["halal"]["method"])
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
        if not plan["diff"] and not plan["dropped"]:
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


class Runner(object):
    """One tayyib-daily run at a time. start() -> state; status() -> state with the last lines of output."""

    def __init__(self, script=DAILY, python=None):
        self.script = script
        self.python = python or sys.executable
        self.lock = threading.Lock()
        self.proc = None
        self.state = {"state": "idle", "started": None, "ended": None, "returncode": None, "error": None,
                      "skip_news": False, "list_date": None, "new_list": False}
        self.lines = collections.deque(maxlen=LOG_LINES)
        self.t0 = self.t1 = None

    def start(self, body):
        if not isinstance(body, dict) or set(body) - {"skip_news"} or not isinstance(body.get("skip_news", False), bool):
            raise Refused(400, "the only option is skip_news (true or false)")
        with self.lock:
            if self.state["state"] == "running":
                raise Refused(409, "a run is already going (started %s)" % self.state["started"])
            skip = bool(body.get("skip_news"))
            cmd = [self.python, self.script] + (["--no-news"] if skip else [])
            env = dict(os.environ, TAYYIB_DIR=tc.data_dir(), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            self.lines.clear()
            self.t0, self.t1 = time.time(), None
            self.state = {"state": "running", "started": tc.now_ist().isoformat(timespec="seconds"), "ended": None,
                          "returncode": None, "error": None, "skip_news": skip, "list_date": None, "new_list": False}
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
        rc = proc.wait()
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

    def status(self):
        with self.lock:
            out = dict(self.state)
            out["elapsed_s"] = None if self.t0 is None else int((self.t1 or time.time()) - self.t0)
            out["lines"] = list(self.lines)
            out["command"] = "tayyib-daily%s" % (" --no-news" if out["skip_news"] else "")
            return out
