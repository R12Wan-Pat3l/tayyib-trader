#!/usr/bin/env python3
"""tayyib-dashboard: a local, read-only dashboard over your trader/ files.

  py tayyib-dashboard/dashboard.py              opens http://127.0.0.1:8765/ in your browser
  py tayyib-dashboard/dashboard.py --port 8800 --no-browser

Four tabs: Today (the daily list, top picks, each row's Why), Results (the paper tracker, price
charts, equity curve), Halal (the screened universe, ratios against the limits, your overrides),
Tickets (unplaced tickets with the Kite / Groww steps to copy, and your positions journal).

Read-only by design: it listens on 127.0.0.1 only, answers GET and HEAD only (anything else gets
405), refuses requests whose Host header is not 127.0.0.1 or localhost on its own port, sends no
CORS headers, serves a fixed list of files and writes nothing. It cannot place, change or cancel an
order, and neither can anything else in tayyib-trader. Python does every calculation (formatting,
statuses, chart coordinates); the page only draws what the server sends.

Not financial advice, not a fatwa.
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tayyib_core as tc  # noqa: E402

ROOT = os.path.dirname(HERE)
HOST = "127.0.0.1"                    # loopback only, never all interfaces: for this computer alone
DEFAULT_PORT = 8765
INDEX = os.path.join(HERE, "index.html")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SYM_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
CLOSED = ("TARGET", "STOP", "BREAKEVEN", "TIME EXIT")
NOISE_UNTIL = 30                      # closed trades before the results mean anything
HINT = "run tayyib-daily"
SETTINGS_NOTE = "editing settings arrives in v0.1.8"
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
            return inr(v, 0 if abs(v) >= 1000 else 2)
        if unit == "%":
            return "%.2f%%" % v
        if unit == "R":
            return "%.2fR" % v
        if isinstance(v, int):
            return str(v)
        return "%.2f" % v
    return str(v)


OPS = {"<": "<", "<=": "≤", ">": ">", ">=": "≥", "==": "="}


def why_view(items):
    """why[] -> groups in order, each item with its mark (✓ / ✗ / UNKNOWN) and display text."""
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
            rows.append({"check": x.get("check"), "value": why_value(x.get("value"), x.get("unit")),
                         "limit": limit, "mark": mark,
                         "symbol": {"ok": "✓", "failed": "✗", "unknown": UNKNOWN, "info": "i"}[mark],
                         "note": x.get("note"), "near_limit": bool(x.get("near_limit")),
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
            "settings_header": "Settings: %s (%s)" % (snap["label"], SETTINGS_NOTE),
            "differs_from_default": snap["differs_from_default"],
            "latest_date": dates[0] if dates else None,
            "banners": (latest or {}).get("banners") or [],
            "halal_banner": tc.halal_banner(cfg, uni), "config_notes": tc.config_notes(cfg),
            "disclaimer": "Not financial advice, not a fatwa.", "full_disclaimer": tc.DISCLAIMER}


def api_dates(q):
    return {"dates": daily_dates()}


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


def row_view(r, k_min):
    disp = {"entry": inr(r.get("entry")), "stop": inr(r.get("stop")), "target": inr(r.get("target")),
            "stop_pct": num(r.get("stop_pct"), 1, "%"), "qty": text(r.get("qty")),
            "position_rs": inr(r.get("position_rs"), 0), "loss_at_stop_rs": inr(r.get("loss_at_stop_rs"), 0),
            "gain_at_target_rs": inr(r.get("gain_at_target_rs"), 0), "rr_net": num(r.get("rr_net")),
            "expectancy_r": signed_r(r.get("expectancy_r")), "past_trades": text(r.get("past_trades")),
            "score": num(r.get("score"), 1), "valid_until": text(r.get("valid_until")),
            "verdict": text(r.get("verdict"))}
    use = r.get("expectancy_use") or tc.expectancy_label(r.get("expectancy_r"), r.get("past_trades"), k_min)
    why = r.get("why") or []
    return dict(r, display=disp, expectancy_use=use,
                ranked_by=r.get("ranked_by") or ("score" if tc.thin_evidence(r.get("past_trades"), k_min)
                                                 else "expectancy"),
                stop_capped=bool(r.get("stop_capped") or any(x.get("stop_capped") for x in why)),
                near_limit=any(x.get("near_limit") for x in why),
                why_view=why_view(why))


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
    k_min = (vals.get("daily") or {}).get("min_past_trades_for_rank", 0)
    rows, changed = [], []
    for r in d.get("rows") or []:
        h = status_of(r["symbol"])
        if h.get("status") != "compliant":                 # compliance cross-check: the universe NOW
            rows.append(changed_row(r["symbol"], h.get("status"), h.get("reasons")))
            changed.append(r["symbol"])
            continue
        rows.append(row_view(r, k_min))
    by = {r["symbol"]: r for r in rows}
    picks = [by[s] for s in d.get("top_picks") or [] if s in by]
    st = d.get("settings") or {}
    return {"date": d.get("date"), "asof": d.get("asof"), "staleness": staleness(d),
            "banner": d.get("banner"), "banners": d.get("banners") or [],
            "capital": inr(d.get("capital"), 0), "broker": text(d.get("broker")), "mode": text(d.get("mode")),
            "scanned": text(d.get("scanned")), "universe_updated": text(d.get("universe_updated")),
            "risk_per_trade_pct": num(d.get("risk_per_trade_pct"), 2, "%"),
            "settings_label": st.get("label") or "pre-0.1.5 (not recorded)",
            "min_past_trades_for_rank": k_min,
            "top_picks": picks, "rows": rows, "notes": d.get("notes") or [], "halal_changed": changed,
            "checks": sorted({r.get("risk") for r in rows if r.get("risk")}),
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
                    "zero_y": round(Y(0.0), 1), "dots": [{"x": round(c[0], 1), "y": round(c[1], 1),
                                                          "label": p["label"]} for c, p in zip(coords[1:], pts)],
                    "y_ticks": [{"y": round(Y(v), 1), "label": signed_r(v)} for v in (lo, 0.0, hi)]}}


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
        rows.append(dict(r, row_id=k, verdict=v, settings_label=tr.settings_group(store, r.get("settings_hash")),
                         display={"entry": inr(r.get("entry")), "stop": inr(r.get("stop")),
                                  "target": inr(r.get("target")), "fill": inr(r.get("fill")),
                                  "exit": inr(r.get("exit")), "r": signed_r(r.get("r")),
                                  "pnl_rs": inr(r.get("pnl_rs")), "filled": text(r.get("filled")),
                                  "exited": text(r.get("exited")), "days": text(r.get("days")),
                                  "check": text(r.get("check")), "last": inr(r.get("last"))}))
    closed = summ["all"]["closed"]
    groups = []
    for g, s in summ.items():
        kind, _, val = g.partition(": ")
        groups.append({"group": g, "by": "all" if g == "all" else kind, "value": val or "all", "stats": s,
                       "display": {"win_rate_pct": num(s["win_rate_pct"], 1, "%"), "avg_r": signed_r(s["avg_r"]),
                                   "total_r": signed_r(s["total_r"]), "pnl_rs": inr(s["pnl_rs"])}})
    return {"rows": rows, "summary": summ, "groups": groups, "settings_split": tr.settings_split(store),
            "equity": equity_curve(store["rows"]), "closed": closed,
            "noise_banner": ("still noise: don't judge yet (%d of %d closed trades)" % (closed, NOISE_UNTIL))
            if closed < NOISE_UNTIL else None}


RATIO_ROWS = (("debt_to_assets_pct", "Debt / total assets", "max_debt_to_assets_pct"),
              ("interest_income_pct", "Reported interest / total income", "max_noncompliant_income_pct"),
              ("noncompliant_income_pct", "Non-compliant income (reported + assumed 8%)",
               "max_noncompliant_income_pct"),
              ("cash_receivables_to_assets_pct", "Cash + receivables / total assets",
               "max_cash_receivables_to_assets_pct"))


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
        bars = []
        for key, label, lim in RATIO_ROWS:
            v, L = ratios.get(key), limits.get(lim)
            nl = tc.is_near_limit(v, L, near)
            over = v is not None and L is not None and v >= L
            bars.append({"key": key, "label": label, "value": v, "limit": L,
                         "value_text": num(v, 2, "%"), "limit_text": num(L, 0, "%"),
                         "fill_pct": None if v is None or not L else round(min(v / L, 1.5) * 100 / 1.5, 1),
                         "limit_pct": round(100 / 1.5, 1), "near_pct": round(near / 1.5, 1),
                         "near_limit": nl, "over": over,
                         "state": "unknown" if v is None else "over" if over else "near" if nl else "ok"})
        ov = overrides.get(sym)
        stocks.append({"symbol": sym, "name": rec.get("name", ""), "industry": rec.get("industry", ""),
                       "status": st, "reasons": rec.get("reasons") or [], "as_of": text(rec.get("as_of")),
                       "assumed_return_text": num(ratios.get("assumed_return_pct"), 2, "%"),
                       "total_income_basis": ratios.get("total_income_basis"),
                       "ratios": bars, "near_limit": [b["key"] for b in bars if b["near_limit"]],
                       "override": {"status": ov.get("status"), "note": text(ov.get("note")),
                                    "date": text(ov.get("date"))} if ov else None})
    return {"updated": text(uni.get("updated")), "source": text(uni.get("source")), "method": text(uni.get("method")),
            "limits": limits, "list_thresholds": uni.get("thresholds"), "near_limit_pct": near,
            "banner": tc.halal_banner(cfg, uni), "counts": counts, "stocks": stocks,
            "age_days": tc.universe_age_days(uni)}


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
    return {"tickets": tickets, "open": [pview(p) for p in opened], "closed": [pview(p) for p in closed],
            "totals": {"closed": len(closed), "winners": sum(1 for p in closed if (p.get("pnl_rs") or 0) > 0),
                       "pnl_rs": inr(tot), "avg_r": signed_r(round(sum(rs) / len(rs), 2) if rs else None)},
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
                          "label": "%s %s at %s" % ("bought" if kind == "fill" else "exit", d, inr(price))})
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


ROUTES = {"/api/meta": api_meta, "/api/dates": api_dates, "/api/today": api_today, "/api/tracker": api_tracker,
          "/api/halal": api_halal, "/api/tickets": api_tickets, "/api/chart": api_chart}
PAGES = {"/": INDEX, "/index.html": INDEX}             # the only files served


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
                return self._send(200, f.read(), "text/html; charset=utf-8", head)
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

    def _refuse(self):
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def make_server(port=DEFAULT_PORT):
    return ThreadingHTTPServer((HOST, port), Handler)


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
    print("tayyib dashboard (read-only) on %s  data: %s" % (url, tc.data_dir()))
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
