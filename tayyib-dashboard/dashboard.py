#!/usr/bin/env python3
"""tayyib-dashboard: a local dashboard over your trader/ files.

  py tayyib-dashboard/dashboard.py              opens http://127.0.0.1:8765/ in your browser
  py tayyib-dashboard/dashboard.py --port 8800 --no-browser

Five tabs: Today (the daily list, top picks, each row's Why, a "Run today's list" button), Results (the
paper tracker, price charts, equity curve), Halal (the screened universe, ratios against the limits, your
overrides), Tickets (unplaced tickets with the Kite / Groww steps to copy, your positions journal) and
Settings (config.json, validated, with a risk preview and backups).

It listens on 127.0.0.1 only, refuses requests whose Host header is not 127.0.0.1 or localhost on its own
port and sends no CORS headers. Everything is GET / HEAD and reads only, except exactly two POST endpoints,
both in actions.py: /api/config (save or restore config.json) and /api/run (start tayyib-daily). A POST
also needs an Origin of this server, the per-start token embedded in the page (X-Tayyib-Token),
Content-Type application/json and a body of at most 64 KB. Any other method or path gets 405. This module
itself writes nothing. Nothing here can place, change or cancel an order, and neither can anything else in
tayyib-trader. Python does every calculation (formatting, statuses, chart coordinates, validation); the
page only draws what the server sends.

Not financial advice, not a fatwa.
"""
import argparse
import datetime as dt
import hmac
import importlib.util
import json
import os
import re
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tayyib_core as tc  # noqa: E402
import actions as A  # noqa: E402   the only write paths: config.json and starting tayyib-daily

ROOT = os.path.dirname(HERE)
HOST = "127.0.0.1"                    # loopback only, never all interfaces: for this computer alone
DEFAULT_PORT = 8765
INDEX = os.path.join(HERE, "index.html")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SYM_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
CLOSED = ("TARGET", "STOP", "BREAKEVEN", "TIME EXIT")
NOISE_UNTIL = 30                      # closed trades before the results mean anything
HINT = "run tayyib-daily"
RUN_DAILY = "Run: give me today's halal list"
SETTINGS_NOTE = "change them in the Settings tab"
MAX_BODY = 64 * 1024                  # bytes a POST may carry
TOKEN_SLOT = b"{{TAYYIB_TOKEN}}"      # index.html carries the per-start token here
UNKNOWN = "UNKNOWN"


# --- the sibling skills whose code the dashboard reuses (never a copy of it) ----------------------

def _sibling(skill, name):
    p = os.path.join(ROOT, skill, name)
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("tayyib_dash_" + name[:-3], p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TRACKER = []


def tracker_mod():
    """tayyib-tracker/tracker.py: its summary() is the one the Excel Summary sheet uses."""
    if not _TRACKER:
        _TRACKER.append(_sibling("tayyib-tracker", "tracker.py"))
    return _TRACKER[0]


# --- formatting: done here, so the page never turns a missing value into 0 -------------------------

def inr(x, dec=2):
    """Indian format with the rupee sign: 100000 -> '₹1,00,000.00'. None -> UNKNOWN."""
    if x is None:
        return UNKNOWN
    return tc.fmt_rs(x, dec).replace("Rs ", "₹")


def inr_short(x):
    """Large money in crore / lakh: 5237000000 -> '₹523.7 cr', 1250000 -> '₹12.5 lakh'. None -> UNKNOWN."""
    if x is None:
        return UNKNOWN
    a = abs(x)
    if a >= 1e7:
        v, unit = x / 1e7, "cr"
    elif a >= 1e6:
        v, unit = x / 1e5, "lakh"
    else:
        return inr(x, 0 if a >= 1000 else 2)
    t = "{:,.1f}".format(v)
    t = t[:-2] if t.endswith(".0") else t                     # ₹2 cr, ₹523.7 cr, ₹1,000 cr
    return "₹%s %s" % (t, unit)


NO_CLOSED = "no closed trades"


def num(x, dec=2, suffix=""):
    if x is None:
        return UNKNOWN
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, float)):
        return ("%." + str(dec) + "f%s") % (x, suffix)
    return str(x)


def signed_r(x):
    if x is None:
        return UNKNOWN
    return ("+%.2fR" % x) if x > 0 else ("−%.2fR" % -x) if x < 0 else "0.00R"


def text(x):
    return UNKNOWN if x is None or x == "" else str(x)


def why_value(v, unit):
    if v is None:
        return UNKNOWN
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if unit == "Rs":
            return inr_short(v)
        if unit == "%":
            return "%.2f%%" % v
        if unit == "R":
            return "%.2fR" % v
        if isinstance(v, int):
            return str(v)
        return "%.2f" % v
    return str(v)


OPS = {"<": "<", "<=": "≤", ">": ">", ">=": "≥", "==": "="}


def over_of(x):
    """over_limit of a HALAL ratio item, recomputed for lists that flagged over-limit ratios as near."""
    if x.get("group") == "HALAL" and x.get("op") == "<" and x.get("unit") == "%":
        return tc.is_over_limit(x.get("value"), x.get("limit"))
    return bool(x.get("over_limit"))


def near_of(x):
    if x.get("group") == "HALAL" and x.get("op") == "<" and x.get("unit") == "%":
        return tc.is_near_limit(x.get("value"), x.get("limit"))
    return bool(x.get("near_limit"))


def why_view(items, headlines=None):
    """why[] -> groups in order, each item with its mark (✓ / ✗ / UNKNOWN) and display text.
    NEWS values are shown in full: a headline an older list cut short is completed from news.json."""
    out = []
    for g in tc.WHY_GROUPS:
        mine = [x for x in items or [] if x.get("group") == g]
        if not mine:
            continue
        rows = []
        for x in mine:
            ok = x.get("ok")
            mark = "ok" if ok is True else "failed" if ok is False else "unknown"
            if x.get("op") == "info" and ok is not None:
                mark = "info"
            limit = None
            if x.get("op") in OPS and x.get("limit") is not None:
                limit = "%s %s" % (OPS[x["op"]], why_value(x["limit"], x.get("unit")))
            value = why_value(x.get("value"), x.get("unit"))
            if g == "NEWS" and isinstance(x.get("value"), str) and headlines:
                value = next((t for t in headlines if t.startswith(x["value"])), value)
            rows.append({"check": x.get("check"), "value": value,
                         "limit": limit, "mark": mark,
                         "symbol": {"ok": "✓", "failed": "✗", "unknown": UNKNOWN, "info": "i"}[mark],
                         "note": x.get("note"), "near_limit": near_of(x),
                         "over_limit": over_of(x),
                         "stop_capped": bool(x.get("stop_capped"))})
        out.append({"group": g, "items": rows})
    return out


# --- data -----------------------------------------------------------------------------------------

def data_file(name):
    """Only the files this module names itself; `name` never comes from the request."""
    return os.path.join(tc.data_dir(), name)


def read(name):
    """-> (obj, None) or (None, {"missing": name, "hint": ...})."""
    p = data_file(name)
    if not os.path.exists(p):
        return None, {"missing": name.replace(os.sep, "/"), "hint": HINT}
    try:
        return tc.read_json(p), None
    except ValueError as e:
        return None, {"missing": name.replace(os.sep, "/"), "hint": HINT, "error": "could not read: %s" % e}


def daily_dates():
    d = os.path.join(tc.data_dir(), "daily")
    if not os.path.isdir(d):
        return []
    return sorted((f[:-5] for f in os.listdir(d) if f.endswith(".json") and DATE_RE.match(f[:-5])), reverse=True)


def current(cfg=None):
    """The current halal universe with overrides (what every check uses now)."""
    uni = tc.load_universe()
    return uni, (lambda sym: tc.halal_status(sym, uni))


CHANGED = "halal status changed since this list: re-check"


def changed_row(sym, status, reasons):
    return {"symbol": sym, "halal_changed": True, "message": CHANGED, "halal_now": status,
            "halal_now_reasons": (reasons or [])[:2]}


def api_meta(q):
    cfg = tc.load_config()
    uni = tc.load_universe()
    snap = tc.settings_snapshot(cfg)
    dates = daily_dates()
    latest = tc.read_json(os.path.join("daily", dates[0] + ".json")) if dates else None
    return {"version": tc.VERSION, "data_dir": tc.data_dir(), "today": tc.today_ist().isoformat(),
            "settings_label": snap["label"], "defaults_version": snap["defaults_version"],
            "settings_header": "Current settings: %s" % snap["label"],
            "settings_note": SETTINGS_NOTE,
            "differs_from_default": snap["differs_from_default"],
            "latest_date": dates[0] if dates else None,
            "banners": (latest or {}).get("banners") or [],
            "halal_banner": tc.halal_banner(cfg, uni), "config_notes": tc.config_notes(cfg),
            "disclaimer": "Not financial advice, not a fatwa.", "full_disclaimer": tc.DISCLAIMER}


def api_dates(q):
    return {"dates": daily_dates()}


def long_date(iso):
    """'2026-11-05' -> 'Thursday, 5 November 2026' (English names, independent of the computer's locale)."""
    try:
        x = tc.parse_date(iso)
    except (TypeError, ValueError):
        return text(iso)
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")
    return "%s, %d %s %d" % (days[x.weekday()], x.day, months[x.month - 1], x.year)


def staleness(d):
    """Not today's list, or written before 15:30 IST (the day's bar was not final)."""
    reasons = []
    today = tc.today_ist().isoformat()
    if d.get("date") != today:
        reasons.append("this is the list of %s, not today's (%s)" % (text(d.get("date")), today))
    asof = d.get("asof")
    if not asof:
        reasons.append("the list has no time stamp: UNKNOWN whether it was written after the close")
    else:
        try:
            t = dt.datetime.fromisoformat(asof)
            t = t.astimezone(tc.IST) if t.tzinfo else t.replace(tzinfo=tc.IST)
            if (t.hour, t.minute) < (15, 30):
                reasons.append("written at %s IST, before the 3:30 PM close: levels can move" % t.strftime("%H:%M"))
        except ValueError:
            reasons.append("the time stamp %r could not be read" % asof)
    return {"stale": bool(reasons), "reasons": reasons, "asof": asof}


CHECK_ORDER = ("PASS", "WARN", "BLOCK", "FILTERED", "NOT SIZED")
OLDER_NOTE = "Older list: ranked by expectancy only (made before the thin-evidence rule)"
OLDER_USE = "older list: ranked by expectancy only"


def ladder(r):
    """Stop - entry - target as positions on one bar (0-100) with the R multiples. None if a level is missing."""
    e, st, t = r.get("entry"), r.get("stop"), r.get("target")
    if None in (e, st, t) or e <= st or t <= e:
        return None
    risk = e - st
    pos = lambda v: round((v - st) / (t - st) * 100, 1)
    return {"stop": {"pos": 0.0, "price": inr(st), "r": "−1R", "pct": "−%.1f%%" % ((e - st) / e * 100)},
            "entry": {"pos": pos(e), "price": inr(e), "r": "0R"},
            "target": {"pos": 100.0, "price": inr(t), "r": "+%.1fR" % ((t - e) / risk),
                       "pct": "+%.1f%%" % ((t - e) / e * 100)},
            "summary": "stop %s (−1R), buy above %s, target %s (+%.1fR)" % (inr(st), inr(e), inr(t),
                                                                              (t - e) / risk)}


def sparkline(sym, days=60, width=240, height=48, pad=3):
    """The last `days` closes from the price cache (read only, no network) -> an SVG polyline."""
    try:
        bars, _ = tc.cached_bars(sym)
    except (OSError, ValueError):
        bars = None
    bars = (bars or [])[-days:]
    if len(bars) < 2:
        return {"status": "unknown", "message": "price data unavailable"}
    cl = [b["close"] for b in bars]
    lo, hi = min(cl), max(cl)
    span = (hi - lo) or 1.0
    n = len(cl)
    pts = [(pad + (width - 2 * pad) * k / (n - 1), pad + (height - 2 * pad) * (1 - (c - lo) / span))
           for k, c in enumerate(cl)]
    line = " ".join("%.1f,%.1f" % q for q in pts)
    ch = (cl[-1] - cl[0]) / cl[0] * 100
    return {"status": "ok", "width": width, "height": height, "line": line,
            "area": "%.1f,%d %s %.1f,%d" % (pts[0][0], height, line, pts[-1][0], height),
            "change": "%+.1f%%" % ch, "up": ch >= 0, "first": bars[0]["date"], "last": bars[-1]["date"],
            "summary": "%s to %s: %+.1f%%, from %s to %s" % (tc.plural(n, "session"), bars[-1]["date"], ch,
                                                                    inr(cl[0]), inr(cl[-1]))}


def halal_badge(why):
    """within limits / near limit / over limit from the row's HALAL ratio items, always in words."""
    items = [x for x in why if x.get("group") == "HALAL" and x.get("op") == "<" and x.get("unit") == "%"]
    over = [x["check"] for x in items if over_of(x)]
    near = [x["check"] for x in items if near_of(x)]
    if over:
        ov = any(x.get("check") == "your override" for x in why if x.get("group") == "HALAL")
        return {"state": "over", "label": "halal: compliant by your override, ratio over limit" if ov
                else "halal: over limit", "detail": ", ".join(over)}
    if near:
        return {"state": "near", "label": "halal: near limit", "detail": ", ".join(near)}
    if not items or all(x.get("value") is None for x in items):
        return {"state": "unknown", "label": "halal: ratios UNKNOWN", "detail": None}
    return {"state": "ok", "label": "halal: within limits", "detail": None}


def row_view(r, k_min, older=False, headlines=None):
    disp = {"entry": inr(r.get("entry")), "stop": inr(r.get("stop")), "target": inr(r.get("target")),
            "stop_pct": num(r.get("stop_pct"), 1, "%"), "qty": text(r.get("qty")),
            "position_rs": inr(r.get("position_rs"), 0), "loss_at_stop_rs": inr(r.get("loss_at_stop_rs"), 0),
            "gain_at_target_rs": inr(r.get("gain_at_target_rs"), 0), "rr_net": num(r.get("rr_net")),
            "expectancy_r": signed_r(r.get("expectancy_r")), "past_trades": text(r.get("past_trades")),
            "score": num(r.get("score"), 1), "valid_until": text(r.get("valid_until")),
            "verdict": text(r.get("verdict"))}
    if older:                      # made before v0.1.7: ranked by expectancy alone, no thin-evidence label
        use, ranked = OLDER_USE, "expectancy (older list)"
    else:
        use = r.get("expectancy_use") or tc.expectancy_label(r.get("expectancy_r"), r.get("past_trades"), k_min)
        ranked = r.get("ranked_by") or ("score" if tc.thin_evidence(r.get("past_trades"), k_min) else "expectancy")
    why = r.get("why") or []
    badge = halal_badge(why)
    summary = "%s %s, setup score %s; net R:R %s; time machine %s (%s)" % (
        text(r.get("mode")), text(r.get("setup")), disp["score"], disp["rr_net"], disp["expectancy_r"], use)
    return dict(r, display=disp, expectancy_use=use, ranked_by=ranked,
                stop_capped=bool(r.get("stop_capped") or any(x.get("stop_capped") for x in why)),
                near_limit=badge["state"] == "near", over_limit=badge["state"] == "over", halal_badge=badge,
                why_summary=summary, ladder=ladder(r), why_view=why_view(why, headlines))


def api_today(q):
    dates = daily_dates()
    date = (q.get("date") or [dates[0] if dates else None])[0]
    if date is None:
        return {"missing": "daily/", "hint": HINT}
    if not DATE_RE.match(date):
        return {"error": "date must be YYYY-MM-DD"}
    d, miss = read(os.path.join("daily", date + ".json"))
    if miss:
        return miss
    _, status_of = current()
    vals = (d.get("settings") or {}).get("values") or {}
    # lists from before v0.1.7 (default@1) were ranked by expectancy alone: that is a threshold of 0
    older = "min_past_trades_for_rank" not in (vals.get("daily") or {})
    k_min = (vals.get("daily") or {}).get("min_past_trades_for_rank", 0)
    news = tc.read_json("news.json", {}) or {}
    rows, changed = [], []
    for r in d.get("rows") or []:
        h = status_of(r["symbol"])
        if h.get("status") != "compliant":                 # compliance cross-check: the universe NOW
            rows.append(changed_row(r["symbol"], h.get("status"), h.get("reasons")))
            changed.append(r["symbol"])
            continue
        heads = [it.get("title") or "" for it in ((news.get("symbols") or {}).get(r["symbol"]) or [])]
        rows.append(row_view(r, k_min, older, heads))
    by = {r["symbol"]: r for r in rows}
    picks = [dict(by[s], sparkline=sparkline(s)) for s in d.get("top_picks") or [] if s in by]
    st = d.get("settings") or {}
    label = st.get("label") or "pre-0.1.5 (not recorded)"
    counts = {}
    for r in rows:
        k = "CHANGED" if r.get("halal_changed") else r.get("risk") or "UNKNOWN"
        counts[k] = counts.get(k, 0) + 1
    rank_note = OLDER_NOTE if older else (
        "Ranked by time-machine expectancy among stocks with at least %d past trades, then the rest by setup "
        "score" % k_min)
    return {"date": d.get("date"), "date_long": long_date(d.get("date")), "asof": d.get("asof"),
            "asof_time": (d.get("asof") or "")[11:16] or UNKNOWN, "staleness": staleness(d),
            "banner": d.get("banner"), "banners": d.get("banners") or [],
            "capital": inr(d.get("capital"), 0), "capital_short": inr_short(d.get("capital")),
            "broker": text(d.get("broker")), "mode": text(d.get("mode")),
            "scanned": text(d.get("scanned")), "universe_updated": text(d.get("universe_updated")),
            "risk_per_trade_pct": num(d.get("risk_per_trade_pct"), 2, "%"),
            "settings_label": label, "made_with": "This list was made with: %s" % label,
            "older_list": older, "rank_note": rank_note,
            "min_past_trades_for_rank": None if older else k_min, "counts": counts,
            "top_picks": picks, "rows": rows, "notes": d.get("notes") or [], "halal_changed": changed,
            "checks": sorted({r.get("risk") for r in rows if r.get("risk")},
                             key=lambda c: (CHECK_ORDER.index(c) if c in CHECK_ORDER else 9, c)),
            "modes": sorted({r.get("mode") for r in rows if r.get("mode")})}


def verdict(r):
    """A labelled verdict for one tracked pick."""
    s, x = r.get("status"), r.get("r")
    if s == "TARGET":
        return {"verdict": "right", "label": "TARGET: right", "kind": "pass"}
    if s == "STOP":
        return {"verdict": "wrong", "label": "STOP: wrong", "kind": "block"}
    if s == "NOT TRIGGERED":
        return {"verdict": "no trade", "label": "NOT TRIGGERED: no trade", "kind": "unknown"}
    if s == "TIME EXIT":
        if x is None:
            return {"verdict": "unknown", "label": "TIME EXIT: R UNKNOWN", "kind": "unknown"}
        return ({"verdict": "right", "label": "TIME EXIT (%s): right" % signed_r(x), "kind": "pass"} if x > 0 else
                {"verdict": "wrong", "label": "TIME EXIT (%s): wrong" % signed_r(x), "kind": "block"})
    if s == "BREAKEVEN":
        return {"verdict": "breakeven", "label": "BREAKEVEN (%s)" % signed_r(x), "kind": "warn"}
    if s in ("OPEN", "WAITING"):
        return {"verdict": "pending", "label": "%s: pending" % s, "kind": "info"}
    if s == "SUPERSEDED":
        return {"verdict": "superseded", "label": "SUPERSEDED by %s: not counted" % text(r.get("superseded_by")),
                "kind": "unknown"}
    return {"verdict": "unknown", "label": "%s" % text(s), "kind": "unknown"}


def equity_curve(rows, width=640, height=200, pad=28):
    """Cumulative R of closed trades by exit date -> points and the SVG coordinates to draw."""
    closed = sorted([r for r in rows if r.get("status") in CLOSED and r.get("r") is not None and r.get("exited")],
                    key=lambda r: (r["exited"], r["date"], r["symbol"]))
    pts, cum = [], 0.0
    for r in closed:
        cum = round(cum + r["r"], 2)
        pts.append({"date": r["exited"], "symbol": r["symbol"], "r": r["r"], "cum_r": cum,
                    "label": "%s %s %s, total %s" % (r["exited"], r["symbol"], signed_r(r["r"]), signed_r(cum))})
    if not pts:
        return {"points": [], "svg": None, "summary": "No closed trades yet: nothing to draw."}
    base_y = height - pad
    ys = [0.0] + [p["cum_r"] for p in pts]
    lo, hi = min(ys), max(ys)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    n = len(pts)
    X = lambda k: pad + (width - 2 * pad) * (k / n)
    Y = lambda v: pad + (height - 2 * pad) * (1 - (v - lo) / (hi - lo))
    coords = [(X(0), Y(0.0))] + [(X(k + 1), Y(p["cum_r"])) for k, p in enumerate(pts)]
    return {"points": pts, "summary": "%d closed trade%s, total %s, last %s on %s"
                                      % (n, "" if n == 1 else "s", signed_r(pts[-1]["cum_r"]),
                                         signed_r(pts[-1]["r"]), pts[-1]["date"]),
            "svg": {"width": width, "height": height,
                    "line": " ".join("%.1f,%.1f" % c for c in coords),
                    "area": "%.1f,%.1f %s %.1f,%.1f" % (coords[0][0], base_y, " ".join("%.1f,%.1f" % c for c in coords),
                                                       coords[-1][0], base_y),
                    "zero_y": round(Y(0.0), 1), "dots": [{"x": round(c[0], 1), "y": round(c[1], 1),
                                                          "label": p["label"]} for c, p in zip(coords[1:], pts)],
                    "y_ticks": [{"y": round(Y(v), 1), "label": signed_r(v)} for v in (lo, 0.0, hi)]}}


def stats_display(s):
    """Summary numbers for display. With no closed trades they say so: never a ₹0.00 or 0% that looks real."""
    if not s.get("closed"):
        return {"win_rate_pct": NO_CLOSED, "avg_r": NO_CLOSED, "total_r": NO_CLOSED, "pnl_rs": NO_CLOSED}
    return {"win_rate_pct": num(s.get("win_rate_pct"), 1, "%"), "avg_r": signed_r(s.get("avg_r")),
            "total_r": signed_r(s.get("total_r")), "pnl_rs": inr(s.get("pnl_rs"))}


def result_counts(rows):
    out = {"right": 0, "wrong": 0, "no trade": 0, "pending": 0, "other": 0}
    for r in rows:
        if r.get("status") == "SUPERSEDED":                 # kept for the record, never counted
            continue
        v = r["verdict"]["verdict"]
        out[v if v in out else "other"] += 1
    return out


def api_tracker(q):
    store, miss = read("tracker.json")
    if miss:
        return miss
    tr = tracker_mod()
    if tr is None:
        return {"missing": "tayyib-tracker/tracker.py", "hint": "install every tayyib skill side by side"}
    store = store or {}
    store.setdefault("rows", [])
    store.setdefault("settings", {})
    for r in store["rows"]:
        r.setdefault("settings_hash", tr.PRE)
    summ = tr.summary(store["rows"], store)          # the same function as the Excel Summary sheet
    rows = []
    for k, r in enumerate(sorted(store["rows"], key=lambda r: (r["date"], r["symbol"]), reverse=True)):
        v = verdict(r)
        pending = r.get("status") in ("WAITING", "OPEN")
        sup = r.get("status") == "SUPERSEDED"
        rows.append(dict(r, row_id=k, verdict=v, superseded=sup, settings_label=tr.settings_group(store, r.get("settings_hash")),
                         display={"entry": inr(r.get("entry")), "stop": inr(r.get("stop")),
                                  "target": inr(r.get("target")), "fill": inr(r.get("fill")),
                                  "exit": "not yet" if pending and r.get("exit") is None else
                                  "not followed" if sup else inr(r.get("exit")),
                                  "r": "not closed" if pending and r.get("r") is None else
                                  "not counted" if sup else signed_r(r.get("r")),
                                  "pnl_rs": inr(r.get("pnl_rs")) if r.get("status") in CLOSED else (
                                      "not counted" if sup else
                                      "not closed" if r.get("pnl_rs") is None else inr(r.get("pnl_rs"))),
                                  "filled": "not followed" if sup and not r.get("filled")
                                  else "not yet" if r.get("status") == "WAITING" and not r.get("filled")
                                  else "no" if r.get("status") == "NOT TRIGGERED" and not r.get("filled")
                                  else text(r.get("filled")),
                                  "exited": "not yet" if pending and not r.get("exited") else
                                  "not followed" if sup and not r.get("exited") else text(r.get("exited")),
                                  "days": text(r.get("days")),
                                  "check": text(r.get("check")), "last": inr(r.get("last"))}))
    closed = summ["all"]["closed"]
    groups = []
    for g, s in summ.items():
        kind, _, val = g.partition(": ")
        groups.append({"group": g, "by": "all" if g == "all" else kind, "value": val or "all", "stats": s,
                       "display": stats_display(s)})
    a = summ["all"]
    ring = min(closed, NOISE_UNTIL) / float(NOISE_UNTIL)
    kpis = dict(stats_display(a), closed="%d / %d" % (closed, NOISE_UNTIL), tracked=str(a.get("listed", len(rows))),
                open=str(sum(1 for r in rows if r.get("status") in ("OPEN", "WAITING"))))
    return {"rows": rows, "summary": summ, "groups": groups, "settings_split": tr.settings_split(store),
            "kpis": kpis, "ring": {"fraction": round(ring, 3), "closed": closed, "of": NOISE_UNTIL,
                                   "label": "%d of %d closed trades" % (closed, NOISE_UNTIL)},
            "result_counts": result_counts(rows),
            "superseded": sum(1 for r in rows if r["superseded"]),
            "superseded_note": "SUPERSEDED: the list for that date was made again with other settings before the pick "
                               "filled. Kept for the record, not followed, not counted in any result.",
            "equity": equity_curve(store["rows"]), "closed": closed,
            "noise_banner": ("still noise: don't judge yet (%d of %d closed trades)" % (closed, NOISE_UNTIL))
            if closed < NOISE_UNTIL else None}


RATIO_ROWS = (("debt_to_assets_pct", "Debt / total assets", "max_debt_to_assets_pct"),
              ("interest_income_pct", "Reported interest / total income", "max_noncompliant_income_pct"),
              ("noncompliant_income_pct", "Non-compliant income (reported + assumed 8%)",
               "max_noncompliant_income_pct"),
              ("cash_receivables_to_assets_pct", "Cash + receivables / total assets",
               "max_cash_receivables_to_assets_pct"))


NOT_CHECKED = "not checked (business excluded)"
STATUS_ORDER = ("compliant", "review", "excluded", "unknown")


def donut(counts, r=40.0):
    """compliant / review / excluded / unknown as stroke-dasharray segments of one circle."""
    total = sum(counts.values())
    if not total:
        return None
    c = 2 * 3.141592653589793 * r
    segs, off = [], 0.0
    for k in STATUS_ORDER + tuple(sorted(set(counts) - set(STATUS_ORDER))):
        n = counts.get(k, 0)
        if not n:
            continue
        length = c * n / total
        segs.append({"status": k, "count": n, "pct": "%.0f%%" % (100.0 * n / total),
                     "dash": "%.2f %.2f" % (length, c - length), "offset": "%.2f" % -off})
        off += length
    return {"r": r, "circumference": round(c, 2), "total": total, "segments": segs}


def api_halal(q):
    uni, miss = read("halal_universe.json")
    if miss:
        return dict(miss, hint="run tayyib-halal build (or tayyib-daily, which builds it)")
    cfg = tc.load_config()
    h = cfg["halal"]
    limits = {k: h[k] for k in tc.TASIS_HALAL}
    near = h.get("near_limit_pct", 90)
    overrides = tc.read_json("halal_overrides.json", {}) or {}
    stocks, counts = [], {}
    for sym in sorted((uni.get("stocks") or {})):
        rec = tc.halal_status(sym, uni)
        st = rec.get("status") or "unknown"
        counts[st] = counts.get(st, 0) + 1
        ratios = rec.get("ratios") or {}
        not_checked = st == "excluded" and not ratios          # failed the business screen: ratios never fetched
        bars = []
        for key, label, lim in RATIO_ROWS:
            v, L = ratios.get(key), limits.get(lim)
            nl = tc.is_near_limit(v, L, near)
            over = tc.is_over_limit(v, L)
            bars.append({"key": key, "label": label, "value": v, "limit": L,
                         "value_text": NOT_CHECKED if not_checked else num(v, 2, "%"),
                         "limit_text": num(L, 0, "%"),
                         "fill_pct": None if v is None or not L else round(min(v / L, 1.5) * 100 / 1.5, 1),
                         "limit_pct": round(100 / 1.5, 1), "near_pct": round(near / 1.5, 1),
                         "near_limit": nl, "over": over, "over_limit": over,
                         "state": "not_checked" if not_checked else "unknown" if v is None else
                         "over" if over else "near" if nl else "ok",
                         "state_text": NOT_CHECKED if not_checked else UNKNOWN if v is None else
                         "over limit" if over else "near limit" if nl else "within limit"})
        ov = overrides.get(sym)
        stocks.append({"symbol": sym, "name": rec.get("name", ""), "industry": rec.get("industry", ""),
                       "status": st, "reasons": rec.get("reasons") or [], "as_of": text(rec.get("as_of")),
                       "assumed_return_text": num(ratios.get("assumed_return_pct"), 2, "%"),
                       "total_income_basis": ratios.get("total_income_basis"),
                       "ratios": bars, "near_limit": [b["key"] for b in bars if b["near_limit"]],
                       "over_limit": [b["key"] for b in bars if b["over"]], "not_checked": not_checked,
                       "override": {"status": ov.get("status"), "note": text(ov.get("note")),
                                    "date": text(ov.get("date"))} if ov else None})
    return {"updated": text(uni.get("updated")), "source": text(uni.get("source")), "method": text(uni.get("method")),
            "limits": limits, "list_thresholds": uni.get("thresholds"), "near_limit_pct": near,
            "banner": tc.halal_banner(cfg, uni), "counts": counts, "stocks": stocks, "donut": donut(counts),
            "age_days": tc.universe_age_days(uni),
            "age_text": None if tc.universe_age_days(uni) is None else tc.plural(tc.universe_age_days(uni), "day") + " ago"}


def api_tickets(q):
    orders, miss_o = read("orders.json")
    pos, _ = read("positions.json")
    if miss_o and pos is None:
        return miss_o
    _, status_of = current()
    today = tc.today_ist()
    tickets = []
    for o in (orders or {}).get("orders") or []:
        if o.get("status") == "PLACED":
            continue
        h = status_of(o.get("symbol"))
        if h.get("status") != "compliant":                 # compliance cross-check: the universe NOW
            tickets.append(dict(changed_row(o.get("symbol"), h.get("status"), h.get("reasons")), id=o.get("id")))
            continue
        try:
            steps = {b: tc.broker_steps(o, b) for b in ("zerodha", "groww")}
        except (KeyError, TypeError, ValueError):
            steps = None
        vu = o.get("valid_until")
        expired = bool(vu and DATE_RE.match(vu) and today > tc.parse_date(vu))
        tickets.append({"id": o.get("id"), "symbol": o.get("symbol"), "status": text(o.get("status")),
                        "mode": text(o.get("mode")), "setup": text(o.get("setup")), "broker": text(o.get("broker")),
                        "expired": expired, "valid_until": text(vu),
                        "is_ticket": o.get("status") in ("PASS", "WARN") and not expired,
                        "display": {"qty": text(o.get("qty")), "trigger": inr(o.get("trigger_price")),
                                    "limit": inr(o.get("limit_price")), "stop": inr(o.get("stop")),
                                    "target": inr(o.get("target")), "position": inr(o.get("position_value_rs")),
                                    "charges": inr(o.get("buy_charges_rs")), "loss": inr(o.get("loss_at_stop_rs")),
                                    "gain": inr(o.get("gain_at_target_rs"))},
                        "steps": steps})
    rank = {"PASS": 0, "WARN": 1}
    order = sorted(range(len(tickets)), key=lambda k: (0 if tickets[k].get("is_ticket") else 1,
                                                       rank.get(tickets[k].get("status"), 2), k))
    tickets = [tickets[k] for k in order]
    live = [t for t in tickets if t.get("is_ticket")]
    blocked = [t for t in tickets if not t.get("is_ticket")]
    plist = (pos or {}).get("positions") or []
    opened = [p for p in plist if p.get("status") == "open"]
    closed = [p for p in plist if p.get("status") == "closed"]
    tot = sum(p.get("pnl_rs") or 0 for p in closed) if closed else None
    rs = [p["r"] for p in closed if p.get("r") is not None]

    def pview(p):
        return dict(p, display={"entry": inr(p.get("entry")), "stop": inr(p.get("stop")),
                                "target": inr(p.get("target")), "exit": inr(p.get("exit")),
                                "pnl_rs": inr(p.get("pnl_rs")), "r": signed_r(p.get("r")),
                                "qty": text(p.get("qty")), "opened": text(p.get("opened")),
                                "closed": text(p.get("closed")), "time_stop_date": text(p.get("time_stop_date"))})
    return {"tickets": tickets, "ready": live, "blocked": blocked,
            "blocked_title": "Blocked (not tickets)",
            "open": [pview(p) for p in opened], "closed": [pview(p) for p in closed],
            "totals": {"closed": len(closed), "winners": sum(1 for p in closed if (p.get("pnl_rs") or 0) > 0),
                       "pnl_rs": inr(tot) if closed else NO_CLOSED,
                       "avg_r": signed_r(round(sum(rs) / len(rs), 2)) if rs else NO_CLOSED},
            "orders_missing": miss_o, "note": "Nothing here places an order. You place it in your broker app, "
                                              "after you have said yes."}


def chart_view(bars, row, width=640, height=220, pad=30):
    """Bars and the plan's levels -> SVG coordinates. The page only draws them."""
    levels = [("entry", row.get("entry")), ("stop", row.get("stop")), ("target", row.get("target"))]
    vals = [b["low"] for b in bars] + [b["high"] for b in bars] + [v for _, v in levels if v is not None]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.05, hi + span * 0.05
    n = len(bars)
    X = lambda k: pad + (width - 2 * pad - 60) * (k / max(n - 1, 1))
    Y = lambda v: pad + (height - 2 * pad) * (1 - (v - lo) / (hi - lo))
    idx = {b["date"]: k for k, b in enumerate(bars)}
    marks = []
    for kind, d, price in (("fill", row.get("filled"), row.get("fill")), ("exit", row.get("exited"), row.get("exit"))):
        if d in idx and price is not None:
            marks.append({"kind": kind, "x": round(X(idx[d]), 1), "y": round(Y(price), 1),
                          "label": "%s %s at %s" % ("triggered (paper)" if kind == "fill" else "exit", d,
                                                    inr(price))})
    return {"width": width, "height": height,
            "line": " ".join("%.1f,%.1f" % (X(k), Y(b["close"])) for k, b in enumerate(bars)),
            "levels": [{"kind": k, "y": round(Y(v), 1), "label": "%s %s" % (k, inr(v))}
                       for k, v in levels if v is not None],
            "signal_x": round(X(idx[row["date"]]), 1) if row.get("date") in idx else None,
            "markers": marks, "x_labels": [{"x": round(X(k), 1), "label": bars[k]["date"]}
                                           for k in sorted({0, n // 2, n - 1})],
            "y_labels": [{"y": round(Y(v), 1), "label": inr(v, 0)} for v in (lo, (lo + hi) / 2, hi)]}


def api_chart(q):
    sym = tc.normalize_symbol((q.get("symbol") or [""])[0])
    frm = (q.get("from") or [""])[0]
    if not SYM_RE.match(sym or "") or not DATE_RE.match(frm or ""):
        return {"error": "symbol (NSE code) and from (YYYY-MM-DD, the list date) are required"}
    store, miss = read("tracker.json")
    if miss:
        return miss
    row = next((r for r in (store or {}).get("rows") or [] if r.get("symbol") == sym and r.get("date") == frm), None)
    if row is None:
        return {"error": "%s on %s is not a tracker row" % (sym, frm)}
    bars, source = None, None
    try:
        bars, _ = tc.get_daily_bars(sym, save=False)          # read-only: never writes the cache
        source = "Yahoo Finance daily bars"
    except (tc.FetchError, OSError, ValueError) as e:
        cached, fetched = tc.cached_bars(sym)
        if cached:
            bars, source = cached, "cached bars from %s (live fetch failed: %s)" % (fetched, str(e)[:80])
    if not bars:
        return {"status": "unknown", "symbol": sym, "message": "price data unavailable"}
    start = (tc.parse_date(frm) - dt.timedelta(days=45)).isoformat()
    end = row.get("exited")
    end = (tc.parse_date(end) + dt.timedelta(days=10)).isoformat() if end else None
    win = [b for b in bars if b["date"] >= start and (end is None or b["date"] <= end)]
    if len(win) < 2:
        return {"status": "unknown", "symbol": sym, "message": "price data unavailable"}
    return {"status": "ok", "symbol": sym, "from": frm, "source": source, "bars": len(win),
            "first": win[0]["date"], "last": win[-1]["date"], "svg": chart_view(win, row),
            "summary": "%s from %s to %s: buy above %s, stop %s, target %s; %s"
                       % (sym, win[0]["date"], win[-1]["date"], inr(row.get("entry")), inr(row.get("stop")),
                          inr(row.get("target")), verdict(row)["label"])}


# --- Settings (v0.1.8): every documented key, grouped. Validation is tc.validate_config, via actions.py ------

def _group_of(key):
    if key in ("capital", "max_risk_per_trade_pct", "max_risk_per_trade_rs", "max_position_pct", "max_open_positions",
               "max_portfolio_heat_pct", "max_positions_per_industry", "min_reward_risk", "cash_available"):
        return "risk", "Money and limits"
    if key.startswith("modes.swing."):
        return "plan", "Swing trades"
    if key.startswith("modes.delivery."):
        return "plan", "Delivery trades"
    if key == "tick_size":
        return "plan", "Prices"
    if key.startswith("scanner.setups."):
        name = key.split(".")[2]
        return "selection", "Setup: %s (%s)" % (name, "delivery" if name in tc.DELIVERY_SETUPS else "swing")
    if key in ("min_price", "min_turnover_rs") or key in ("scanner.warmup_bars", "scanner.min_history_bars",
                                                           "scanner.liquidity_days"):
        return "selection", "Liquidity and history"
    if key.startswith("daily."):
        return "selection", "The daily list"
    if key in ("broker", "exchange") or key.startswith("charges."):
        return "broker", "Broker and charges"
    if key.startswith("brokers."):
        return "broker", "Brokerage: %s" % key.split(".")[1]
    if key.startswith("halal."):
        return "halal", ("Your source" if key in ("halal.loosen_note", "halal.allow_review") else
                         "Thresholds" if key.startswith("halal.max_") or key.endswith("_return_pct") or key == "halal.method"
                         else "The halal list")
    return "data", "Data and calendar"


SETTING_GROUPS = (
    ("risk", "Risk", "What you can lose: per trade, per stock and in total. The preview on the right shows it in rupees."),
    ("plan", "Plan", "Where the stop and the target go, and how long a trade may stay open, per mode."),
    ("selection", "Selection", "Which setups are looked for, the liquidity filter and how the daily list is ranked."),
    ("broker", "Broker & charges", "The charges every quantity and every result in R is computed after."),
    ("halal", "Halal", "Stricter than TASIS saves freely. Looser needs your source or scholar, and every list then says so."),
    ("data", "Data & calendar", "Holidays, news sources and the request header."),
)
SECTION_ORDER = {"plan": ("Swing trades", "Delivery trades", "Prices"),
                 "selection": ("The daily list", "Liquidity and history"),
                 "halal": ("Thresholds", "Your source", "The halal list")}
TASIS_LOOSER = {"max_debt_to_assets_pct": "above", "max_noncompliant_income_pct": "above",
                "max_cash_receivables_to_assets_pct": "above", "noncompliant_investment_return_pct": "below"}


NOTE_WORDS = "your source / scholar note"


def plain(text):
    """User-facing text: no internal key names for the source note, ₹ for Rs."""
    if not text:
        return text
    return (text.replace("halal.loosen_note", NOTE_WORDS).replace("loosen_note", NOTE_WORDS)
            .replace("Rs ", "₹"))


def field_name(key):
    """A setting's name as the page shows it (the code line under each field keeps the key)."""
    doc = tc.DEFAULT_CONFIG_DOCS.get(key)
    if doc is None:
        return key
    if key == "halal.loosen_note":
        return "Your source / scholar note"
    return plain(re.sub(r"\s*\(null = [^)]*\)", "", doc["description"]))


def _with_unit(v, key):
    doc = tc.DEFAULT_CONFIG_DOCS.get(key) or {}
    return v + ("%" if doc.get("unit") == "%" else "")


def friendly(err):
    """{key, message} from the validator -> + text (under the field) and full (with the setting's name).
    The validator's own message stays in `message` (CLI and daily notes keep it); only the page rewords."""
    m, key = err["message"], err.get("key")
    out = dict(err, needs_note=False)
    x = re.match(r"CONFIG ERROR: halal\.(\w+) = (\S+) is looser than TASIS \(([^)]*)\)", m)
    if x:
        out["needs_note"] = True
        if x.group(1) == "allow_review":
            text = ("Letting 'review' stocks through is looser than TASIS. Add your source / scholar note below "
                    "to save this, or turn it off.")
        else:
            text = ("%s is looser than TASIS (%s). Add your source / scholar note below to save this, or reset "
                    "to %s." % (_with_unit(x.group(2), key), _with_unit(x.group(3), key), _with_unit(x.group(3), key)))
    else:
        x = re.match(r"CONFIG: [\w.]+ = (.*) invalid \((.*)\), using (?:default|the defaults).*$", m)
        y = re.match(r"CONFIG: [\w.]+ = (.*) ignored: it is a hard rule and stays (.*)$", m)
        if x and key:
            text = "%s is not allowed (%s)." % (x.group(1), x.group(2).replace("range ", "allowed: "))
        elif y and key:
            text = "This is a hard rule: it stays %s." % y.group(2)
        else:
            text = plain(re.sub(r"^CONFIG(?: ERROR)?: ", "", m))
            text = text[:1].upper() + text[1:]
    out["text"] = text
    short = re.sub(r"\s*\([^)]*\)$", "", re.split(r"\.\s+(?=[A-Z])", field_name(key))[0]) if key else ""
    out["full"] = "%s: %s" % (short, text) if key else text
    return out


def friendly_info(n):
    if n.startswith(tc.HALAL_METHOD_NOTE):
        return "Your halal thresholds differ from TASIS, so the halal method is saved as 'custom'."
    t = plain(re.sub(r"^CONFIG(?: ERROR)?: ", "", n))
    return t[:1].upper() + t[1:]


def friendly_errors(errors):
    return [friendly(e) for e in errors]


def account_note(snap):
    """'Kept your own capital ₹2,00,000 and broker groww: they are not part of the label.' or None."""
    acc = snap.get("account_differs") or []
    if not acc or not str(snap.get("label") or "").startswith("default@"):
        return None                           # with other changes the label is the hash, which includes them
    order = ("capital", "cash_available", "broker", "exchange")
    acc = sorted(acc, key=lambda d: (order.index(d["key"]) if d["key"] in order else len(order), d["key"]))
    parts = []
    for d in acc:
        doc = tc.DEFAULT_CONFIG_DOCS.get(d["key"]) or {"type": "number", "unit": None}
        name = {"capital": "capital", "cash_available": "cash", "broker": "broker", "exchange": "exchange"}.get(
            d["key"], field_name(d["key"]).lower())
        parts.append("%s %s" % (name, _value_text(d["value"], doc)))
    return ("Your own %s %s kept: %s not part of the settings label." % (
        ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1],
        "are" if len(parts) > 1 else "is", "they are" if len(parts) > 1 else "it is"))


def _step(doc):
    if doc["type"] == "int":
        return 1
    span = (doc.get("max") or 0) - (doc.get("min") or 0)
    return 0.001 if span <= 0.1 else 0.01 if span <= 1 else 0.05 if span <= 10 else 0.5 if span <= 60 else 1


def _range_text(doc):
    if doc["type"] in ("number", "int") and doc.get("min") is not None:
        unit = doc.get("unit") or ""
        if unit == "Rs":
            return "%s to %s" % (inr_short(doc["min"]), inr_short(doc["max"]))
        return "%s–%s%s" % (tc._fmt_val(doc["min"]), tc._fmt_val(doc["max"]), (" " + unit) if unit and unit != "%" else unit)
    return {"bool": "on or off", "enum": "one of " + ", ".join(tc._fmt_val(c) for c in doc.get("choices") or []),
            "string": "text", "dates": "dates, YYYY-MM-DD, one a line", "map": "name: URL, one a line"}.get(doc["type"], "")


def _value_text(v, doc):
    if v is None:
        return "none"
    if doc.get("unit") == "Rs" and isinstance(v, (int, float)) and not isinstance(v, bool):
        return inr_short(v) if abs(v) >= 1e5 else inr(v, 2 if v != int(v) else 0)
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, str):
        return v if v.strip() else "(empty)"
    if isinstance(v, list):
        return ", ".join(v) if v else "none"
    if isinstance(v, dict):
        return "%d source%s" % (len(v), "" if len(v) == 1 else "s")
    unit = doc.get("unit") or ""
    return tc._fmt_val(v) + ("%" if unit == "%" else (" " + unit) if unit and doc["type"] in ("number", "int") else "")


def setting_field(key, cur, saved, raw_has):
    doc = tc.DEFAULT_CONFIG_DOCS[key]
    dflt = A._flat(tc.DEFAULT_CONFIG).get(key)
    v = cur.get(key)
    f = {"key": key, "label": field_name(key), "type": doc["type"], "unit": doc.get("unit"), "account": tc.is_account_key(key),
         "min": doc.get("min"), "max": doc.get("max"), "choices": doc.get("choices"), "nullable": bool(doc.get("nullable")),
         "default": dflt, "value": v, "saved": key in saved, "changed": v != dflt,
         "default_text": _value_text(dflt, doc), "value_text": _value_text(v, doc), "range_text": _range_text(doc),
         "slider": doc["type"] in ("number", "int") and doc.get("min") is not None and doc.get("unit") != "Rs"
                   and (doc["max"] - doc["min"]) <= 1000, "step": _step(doc) if doc["type"] in ("number", "int") else None}
    short = key.split(".")[-1]
    if key.startswith("halal.") and short in TASIS_LOOSER:
        f["tasis"] = tc.TASIS_HALAL[short]
        f["looser"] = TASIS_LOOSER[short]
        f["tasis_text"] = "TASIS %s%%: %s it is looser and needs your source" % (
            tc._fmt_val(tc.TASIS_HALAL[short]), "higher" if TASIS_LOOSER[short] == "above" else "lower")
    if key == "halal.allow_review":
        f["tasis_text"] = "on is looser than TASIS and needs your source"
    if key == "halal.loosen_note":
        f["label"] = "Your source / scholar note: who allowed thresholds looser than TASIS"
        f["multiline"] = True
    if key.startswith("scanner.setups.") and short == "enabled":
        f["toggle_section"] = True
    return f


def reset_keys(account=False):
    """The keys "Reset all to defaults" sends as {"reset": [...]}: every editable setting, without the account
    facts (capital, cash, broker and charges) unless `account`. Only the form changes; a save writes it."""
    return [k for k, doc in tc.DEFAULT_CONFIG_DOCS.items()
            if doc["type"] != "locked" and (account or not tc.is_account_key(k))]


def api_settings(q):
    raw, problem = A.raw_config()
    base, dropped = tc.clean_user_config(raw)
    cfg, notes = tc.validate_config(base)
    cur, saved = A._flat(cfg), A._flat(base)
    groups = {g: {"id": g, "title": t, "intro": i, "sections": []} for g, t, i in SETTING_GROUPS}
    for key, doc in tc.DEFAULT_CONFIG_DOCS.items():
        if doc["type"] == "locked":
            continue                                        # hard rules: in the "Always on" card, not an option
        g, sec = _group_of(key)
        secs = groups[g]["sections"]
        if not secs or secs[-1]["title"] != sec:
            found = [x for x in secs if x["title"] == sec]
            if found:
                secs.append(secs.pop(secs.index(found[0])))
            else:
                secs.append({"title": sec, "fields": []})
        f = setting_field(key, cur, saved, key in saved)
        if f.get("toggle_section"):
            secs[-1]["toggle"] = f
        else:
            secs[-1]["fields"].append(f)
    for g in groups.values():
        order = SECTION_ORDER.get(g["id"], ())
        g["sections"].sort(key=lambda x: order.index(x["title"]) if x["title"] in order else len(order))
        g["keys"] = []                                # what "Reset this section" puts back to the defaults
        for sec in g["sections"]:
            fs = sec["fields"] + ([sec["toggle"]] if sec.get("toggle") else [])
            sec["changed"] = sum(1 for f in fs if f["changed"])
            g["keys"] += [f["key"] for f in fs]
    snap = tc.settings_snapshot(cfg)
    return {"groups": [groups[g] for g, _, _ in SETTING_GROUPS], "version": A.config_version(),
            "label": snap["label"], "changed": len(snap["differs_from_default"]),
            "always_on": list(tc.HARD_RULES) + ["only halal-compliant stocks can pass (review needs your source; "
                                                "excluded and unknown never pass)"],
            "notes": [friendly_info(n) for n in ([problem] if problem else []) + dropped]
                     + [e["full"] for e in friendly_errors(A._errors_by_key(tc.config_errors(notes)))],
            "account_note": account_note(snap),
            "reset_all": reset_keys(False), "account_keys": [k for k in reset_keys(True) if tc.is_account_key(k)],
            "banner": tc.halal_banner(cfg), "backups": A.list_backups(), "keep_backups": A.KEEP_BACKUPS,
            "apply_note": A.APPLY_NOTE, "data_dir": tc.data_dir(),
            "preview": preview_view(tc.risk_preview(cfg))}


def preview_view(rp):
    """tc.risk_preview, formatted for the page."""
    binding = {"risk": "risk per trade", "position": "max position", "both": "both"}
    return {"risk_rs": inr(rp["risk_per_trade_rs"], 0), "risk_pct": tc._fmt_val(rp["risk_per_trade_pct"]) + "%",
            "capital": inr_short(rp["capital"]), "max_position": "%s%% = %s" % (tc._fmt_val(rp["max_position_pct"]),
                                                                              inr(rp["max_position_rs"], 0)),
            "streaks": [{"losses": x["losses"], "label": "%d losses in a row" % x["losses"],
                         "drawdown": "−%s%%" % tc._fmt_val(round(x["drawdown_pct"], 1)),
                         "fraction": min(1.0, x["drawdown_pct"] / 100.0),
                         "detail": "%s lost, %s left" % (inr(x["lost_rs"], 0), inr(x["capital_left_rs"], 0))}
                        for x in rp["losing_streaks"]],
            "samples": [{"stop": tc._fmt_val(x["stop_pct"]) + "%", "qty": str(x["qty"]), "binding": binding[x["binding"]],
                         "position": "%s (%s%%)" % (inr(x["position_rs"], 0), tc._fmt_val(round(x["position_pct"], 1))),
                         "loss": inr(x["loss_at_stop_rs"], 0)} for x in rp["samples"]],
            "sample_entry": inr(rp["samples"][0]["entry"], 0) if rp["samples"] else UNKNOWN,
            "binding_stop": None if rp["binding_stop_pct"] is None else tc._fmt_val(rp["binding_stop_pct"]) + "%",
            "explain": rp["explain"].replace("Rs ", "₹"), "note": rp["note"],
            "warning": rp["warning"].replace("Rs ", "₹") if rp.get("warning") else None}


def diff_view(diff):
    for d in diff:
        doc = tc.DEFAULT_CONFIG_DOCS[d["key"]]
        d["from_text"], d["to_text"] = _value_text(d["from"], doc), _value_text(d["to"], doc)
        d["default_text"] = _value_text(d["default"], doc)
        d["description"] = field_name(d["key"])
    return diff


def api_risk_preview(q):
    """What a pending change would do, without saving: the risk preview in rupees, the diff, the validator's
    messages per key, the halal banner and the settings label after saving."""
    raw = (q.get("change") or ["{}"])[0]
    if len(raw) > MAX_BODY:
        return {"error": "change too large"}
    try:
        change = json.loads(raw)
        plan = A.plan_change(change)
    except ValueError:
        return {"error": "change must be JSON"}
    except A.Refused as e:
        return {"error": "; ".join(e.errors)}
    return {"ok": plan["ok"], "errors": friendly_errors(plan["errors"]), "diff": diff_view(plan["diff"]),
            "dropped": [friendly_info(n) for n in plan["dropped"]], "account_note": account_note(plan["snap"]),
            "label": plan["label"], "label_now": plan["label_now"], "banner": plan["banner"],
            "info": [friendly_info(n) for n in plan["info"]],
            "preview": preview_view(tc.risk_preview(plan["cfg"])), "apply_note": A.APPLY_NOTE}


def api_backups(q):
    return {"backups": A.list_backups(), "keep": A.KEEP_BACKUPS}


def api_backup_diff(q):
    """What restoring a backup would change (read only; restoring is POST /api/config {"restore": NAME})."""
    try:
        plan = A.plan_change(A.restore_change((q.get("name") or [""])[0]))
    except A.Refused as e:
        return {"error": "; ".join(e.errors)}
    except ValueError as e:
        return {"error": "the backup could not be read: %s" % e}
    return {"ok": plan["ok"], "errors": friendly_errors(plan["errors"]), "diff": diff_view(plan["diff"]),
            "label": plan["label"], "label_now": plan["label_now"], "account_note": account_note(plan["snap"]),
            "dropped": [friendly_info(n) for n in plan["dropped"]], "info": [friendly_info(n) for n in plan["info"]],
            "banner": plan["banner"]}


def run_status(runner):
    st = runner.status()
    e = st.get("elapsed_s")
    st["elapsed_text"] = "" if e is None else "%d:%02d" % (e // 60, e % 60)
    try:
        st["started_text"] = dt.datetime.fromisoformat(st["started"]).strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        st["started_text"] = ""
    st["advice"] = A.run_advice()
    return st


ROUTES = {"/api/meta": api_meta, "/api/dates": api_dates, "/api/today": api_today, "/api/tracker": api_tracker,
          "/api/halal": api_halal, "/api/tickets": api_tickets, "/api/chart": api_chart, "/api/settings": api_settings,
          "/api/risk-preview": api_risk_preview, "/api/config/backups": api_backups,
          "/api/config/backup-diff": api_backup_diff}
PAGES = {"/": INDEX, "/index.html": INDEX}             # the only files served
POST_ROUTES = ("/api/config", "/api/run")             # the only two requests that change anything (actions.py)


class Handler(BaseHTTPRequestHandler):
    server_version = "tayyib-dashboard"
    sys_version = ""

    def log_message(self, fmt, *args):                 # quiet: errors only
        pass

    def _host_ok(self):
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").strip().lower() in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _send(self, code, body, ctype, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                         "style-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; "
                         "form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, code, obj, head=False):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", head)

    def _get(self, head=False):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"}, head)
        u = urllib.parse.urlsplit(self.path)
        p = u.path
        if p in PAGES:
            with open(PAGES[p], "rb") as f:
                page = f.read().replace(TOKEN_SLOT, self.server.token.encode("ascii"))
            return self._send(200, page, "text/html; charset=utf-8", head)
        if p in POST_ROUTES:
            return self._refuse()
        if p == "/api/run/status":
            return self._json(200, run_status(self.server.runner), head)
        fn = ROUTES.get(p)
        if fn is None:
            return self._json(404, {"error": "not found"}, head)
        try:
            return self._json(200, fn(urllib.parse.parse_qs(u.query)), head)
        except Exception as e:                           # never a stack trace in the page
            return self._json(500, {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}, head)

    def do_GET(self):
        self._get()

    def do_HEAD(self):
        self._get(head=True)

    def _length(self):
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return None
        return n if n >= 0 else None

    def _drain(self):
        """Read and drop a refused request's body (at most 1 MB, briefly) so the connection closes cleanly."""
        n = self._length()
        left = min(MAX_BODY if n is None else n, 1 << 20)      # no usable length: whatever arrives, briefly
        try:
            self.connection.settimeout(0.5)
            while left > 0:
                chunk = self.rfile.read1(min(left, 65536))
                if not chunk:
                    break
                left -= len(chunk)
        except (OSError, ValueError):
            pass

    def _no(self, code, msg):
        self._drain()
        return self._json(code, {"error": msg})

    def _refuse(self):
        self._drain()
        p = urllib.parse.urlsplit(self.path).path
        self.send_response(405)
        self.send_header("Allow", "POST" if p in POST_ROUTES else "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _origin_ok(self):
        port = self.server.server_address[1]
        return (self.headers.get("Origin") or "") in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port)

    def do_POST(self):
        """Exactly two POST routes. Each needs: the Host check, an Origin of this server, the per-start token,
        Content-Type application/json and a body of at most 64 KB."""
        if not self._host_ok():
            return self._no(403, "forbidden host")
        p = urllib.parse.urlsplit(self.path).path
        if p not in POST_ROUTES:
            return self._refuse()
        if not self._origin_ok():
            return self._no(403, "forbidden origin")
        if not hmac.compare_digest((self.headers.get("X-Tayyib-Token") or "").encode("utf-8"),
                                   self.server.token.encode("ascii")):
            return self._no(403, "missing or wrong token: reload the page")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._no(415, "Content-Type must be application/json")
        n = self._length()
        if n is None:
            return self._no(411, "Content-Length required")
        if n > MAX_BODY:
            return self._no(413, "body larger than %d bytes" % MAX_BODY)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "body must be JSON"})
        try:
            if p == "/api/config":
                out = A.save_config(body)
                out["account_note"] = account_note({"account_differs": out.pop("account", []), "label": out["label"]})
            else:
                self.server.runner.start(body)
                out = run_status(self.server.runner)
        except A.Refused as e:
            obj = {"error": e.errors[0] if len(e.errors) == 1 else "refused", "errors": e.errors}
            if p == "/api/config":                     # the validator's words stay in errors; the page shows these
                obj["problems"] = [x["full"] for x in friendly_errors(A._errors_by_key(e.errors))]
            return self._json(e.code, obj)
        except Exception as e:                           # never a stack trace in the page
            return self._json(500, {"error": "%s: %s" % (type(e).__name__, str(e)[:200])})
        return self._json(200, out)

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def make_server(port=DEFAULT_PORT, runner=None):
    srv = ThreadingHTTPServer((HOST, port), Handler)
    srv.token = secrets.token_urlsafe(32)               # new on every start; only the served page knows it
    srv.runner = runner or A.Runner()
    return srv


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port on 127.0.0.1 (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    a = p.parse_args(argv)
    try:
        srv = make_server(a.port)
    except OSError as e:
        tc.die("cannot listen on %s:%d (%s): is the dashboard already running? Try --port %d"
               % (HOST, a.port, e, a.port + 1))
    url = "http://%s:%d/" % (HOST, srv.server_address[1])
    print("tayyib dashboard on %s  data: %s" % (url, tc.data_dir()))
    print("It reads your files; it changes only config.json (Settings, with backups) and runs tayyib-daily when you "
          "press Run. It never places an order.")
    print("Press Ctrl+C to stop. Not financial advice, not a fatwa.")
    sys.stdout.flush()
    if not a.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
