#!/usr/bin/env python3
"""tayyib-email: today's halal list by email, to your own inbox, sent from your own computer.

  email_report.py test                                   send a short test email (prints the exact SMTP error)
  email_report.py send [--date YYYY-MM-DD] [--dry-run]   send the list of that day (default today); --dry-run
                                                         writes trader/email/DATE.eml (and DATE.html to look at),
                                                         sends nothing and needs no password
  tayyib-daily --email                                   the daily list, then `send --scheduled` (what the
                                                         Windows scheduled task runs)

Settings: the "email" section of config.json (enabled, smtp_host, smtp_port 465 SSL or 587 STARTTLS, from, to
(at most 3; empty = yourself), send_when always | picks_only, attach_md). The password is read ONLY from the
environment variable TAYYIB_SMTP_PASSWORD: never from config.json, and never written, logged or printed.

Personal use: this is for your own inbox. Sending the list to other people can count as publishing stock
recommendations, which in India may need SEBI Research Analyst registration. Each person runs their own copy.

Never invents: a missing, stale (not that day's completed session) or failed list sends the FAILED email that
says what is missing, never picks from an older file. On a weekend or a holiday in your settings nothing is
sent ("market closed"). Every attempt is logged in trader/email/log.json (no addresses, no secrets).
It places no order and talks to no broker.
"""
import argparse
import datetime as dt
import html
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tayyib_core as tc  # noqa: E402

PW_ENV = "TAYYIB_SMTP_PASSWORD"
PASSWORD_MISSING = "TAYYIB_SMTP_PASSWORD is not set: see User guide, Get the list by email"
SKIPPED_NO_PASSWORD = "email skipped: password not set"
FROM_MISSING = "email.from is not set: set your address in Settings, Email (or the email section of config.json)"
PERSONAL_NOTE = ("This is for your own inbox. Sending the list to other people can count as publishing stock "
                 "recommendations, which in India may need SEBI Research Analyst registration. Team members "
                 "should run their own copy.")
FOOTER = ("Generated on your computer by tayyib-trader v%s. You place orders yourself in your broker app. "
          "Not financial advice, not a fatwa.")
SUBJECT_FAILED = "tayyib: run FAILED / data stale"
SUBJECT_NONE = "tayyib: no picks today"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CLOSE_MIN = 15 * 60 + 30
CLOSED = ("TARGET", "STOP", "BREAKEVEN", "TIME EXIT")
NOT_COUNTED = ("SUPERSEDED", "REPLACED", "ALREADY_HELD")
LOG_KEEP = 500
MAX_WHY = 5


class Problem(Exception):
    """A setting or input that stops a send: (message, exit code)."""

    def __init__(self, msg, code=2):
        Exception.__init__(self, msg)
        self.code = code


# --- settings -------------------------------------------------------------------------------------

def password():
    """The SMTP password, from the environment only. None when it is not set."""
    pw = (os.environ.get(PW_ENV) or "").strip()
    return pw or None


def recipients(cfg):
    """-> (from, [to]). to defaults to [from]; at most tc.MAX_EMAIL_TO."""
    e = cfg["email"]
    if any(n.startswith("CONFIG: email.to ") for n in tc.config_notes(cfg)):
        raise Problem("email.to is not valid: at most %d addresses, each like name@example.com (fix it in "
                      "Settings, Email)" % tc.MAX_EMAIL_TO)
    frm = e.get("from") or ""
    to = list(e.get("to") or ([frm] if frm else []))
    if len(to) > tc.MAX_EMAIL_TO:
        raise Problem("at most %d addresses in email.to" % tc.MAX_EMAIL_TO)
    return frm, to


def long_day(d):
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


# --- what the email says (shaped here, rendered to text and HTML below) -------------------------------

def load_daily(date):
    """daily/DATE.json -> (data or None, problem or None). A problem means: say what is missing, show no picks."""
    p = os.path.join(tc.data_dir(), "daily", date.isoformat() + ".json")
    if not os.path.exists(p):
        return None, ("the list for %s (daily/%s.json) is missing: tayyib-daily did not run or did not finish"
                      % (date.isoformat(), date.isoformat()))
    try:
        d = tc.read_json(p)
    except ValueError as e:
        return None, "the list for %s could not be read (%s)" % (date.isoformat(), e)
    if not isinstance(d, dict) or d.get("date") != date.isoformat():
        return None, "daily/%s.json is not the list of %s" % (date.isoformat(), date.isoformat())
    try:
        asof = dt.datetime.fromisoformat(d.get("asof") or "")
    except ValueError:
        return None, "the list for %s has no run time: it cannot be checked, so it is not shown" % date.isoformat()
    if asof.tzinfo is not None:
        asof = asof.astimezone(tc.IST)
    if asof.date() != date or asof.hour * 60 + asof.minute < CLOSE_MIN:
        return None, ("data stale: the list for %s was made at %s IST on %s, before that session closed (3:30 PM "
                      "IST), so its prices were not final" % (date.isoformat(), asof.strftime("%H:%M"),
                                                              asof.date().isoformat()))
    return d, None


def mark(ok):
    return "✓" if ok is True else "✗" if ok is False else "?"


def why_lines(row):
    """The first lines of the row's Why: what failed or is UNKNOWN first, then the setup and the plan."""
    items = [it for it in (row.get("why") or []) if it.get("op") != "info"]
    first = [it for it in items if it.get("ok") is not True]
    rest = [it for it in items if it.get("ok") is True and it.get("group") in ("SETUP", "HISTORY", "PLAN")]
    out = []
    for it in (first + rest)[:MAX_WHY]:
        s = "%s %s" % (it.get("check"), _val(it.get("value"), it.get("unit")))
        if it.get("op") and it.get("limit") is not None:
            s += " %s %s" % ({"==": "="}.get(it["op"], it["op"]), _val(it["limit"], it.get("unit")))
        note = (it.get("note") or "").replace("UNKNOWN: ", "")
        if note and it.get("ok") is not True:
            s += " (%s)" % note[:120]
        out.append({"mark": mark(it.get("ok")), "text": s.replace("Rs ", "₹")})
    return out


def _val(v, unit):
    if v is None:
        return "UNKNOWN"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if unit == "Rs":
            return rs(v)
        if unit == "%":
            return "%.2f%%" % v
        if unit == "R":
            return "%.2fR" % v
        return str(v) if isinstance(v, int) else "%.2f" % v
    return str(v)


def rs(v, dec=None):
    if v is None:
        return "UNKNOWN"
    if dec is None:
        dec = 0 if abs(v) >= 1000 else 2
    return tc.fmt_rs(v, dec).replace("Rs ", "₹")


def price(v):
    return "UNKNOWN" if v is None else "%.2f" % v


def r_text(v):
    return "UNKNOWN" if v is None else "%+.2fR" % v


def card(row):
    return {"symbol": row["symbol"], "name": row.get("name") or "", "setup": row.get("setup"), "mode": row.get("mode"),
            "check": row.get("risk"), "entry": price(row.get("entry")), "stop": price(row.get("stop")),
            "stop_pct": "UNKNOWN" if row.get("stop_pct") is None else "%.1f%%" % row["stop_pct"],
            "target": price(row.get("target")), "qty": "UNKNOWN" if row.get("qty") is None else str(row["qty"]),
            "position": rs(row.get("position_rs")), "loss_at_stop": rs(row.get("loss_at_stop_rs")),
            "expectancy": r_text(row.get("expectancy_r")),
            "past_trades": "UNKNOWN" if row.get("past_trades") is None else str(row["past_trades"]),
            "valid_until": row.get("valid_until") or "UNKNOWN", "why": why_lines(row)}


def other_row(row):
    reason = (row.get("reason") or "").replace("Rs ", "₹")
    return {"symbol": row["symbol"], "setup": row.get("setup"), "mode": row.get("mode"), "check": row.get("risk"),
            "entry": price(row.get("entry")), "stop": price(row.get("stop")),
            "reason": reason if len(reason) <= 140 else reason[:137] + "..."}


def tracker_view(date):
    """Open paper trades, results this month and the win rate by PASS / WARN / BLOCK (None when no tracker)."""
    store = tc.read_json("tracker.json", None)
    if not store or not store.get("rows"):
        return None
    rows = [r for r in store["rows"] if r.get("status") not in NOT_COUNTED]
    month = date.isoformat()[:7]
    closed = [r for r in rows if r.get("status") in CLOSED and (r.get("exited") or "")[:7] == month]
    rr = [r["r"] for r in closed if r.get("r") is not None]
    summ = store.get("summary") or {}
    by = []
    for k in ("PASS", "WARN", "BLOCK"):
        s = summ.get("check: " + k) or {}
        by.append({"check": k, "closed": s.get("closed") or 0,
                   "win_rate": "no closed trades yet" if not s.get("closed") or s.get("win_rate_pct") is None
                   else "%.1f%% of %s" % (s["win_rate_pct"], tc.plural(s["closed"], "closed trade")),
                   "avg_r": r_text(s.get("avg_r")) if s.get("closed") else "UNKNOWN"})
    return {"open": sum(r.get("status") == "OPEN" for r in rows),
            "waiting": sum(r.get("status") == "WAITING" for r in rows),
            "month": "%s %d" % (MONTHS[date.month - 1], date.year),
            "month_closed": len(closed), "month_wins": sum(x > 0 for x in rr),
            "month_r": r_text(round(sum(rr), 2)) if rr else "UNKNOWN",
            "month_pnl": rs(round(sum(r.get("pnl_rs") or 0 for r in closed), 2)) if closed else "UNKNOWN",
            "month_text": ("%d (%d won) · %s · %s" % (len(closed), sum(x > 0 for x in rr),
                                                      r_text(round(sum(rr), 2)) if rr else "UNKNOWN",
                                                      rs(round(sum(r.get("pnl_rs") or 0 for r in closed), 2)))
                           if closed else "none yet"),
            "by_check": by}


def held_not_compliant():
    """Open positions (positions.json) whose halal status is no longer compliant."""
    pos = (tc.read_json("positions.json", {}) or {}).get("positions") or []
    held = sorted({p.get("symbol") for p in pos if p.get("status") == "open" and p.get("symbol")})
    if not held:
        return []
    uni = tc.load_universe()
    out = []
    for s in held:
        h = tc.halal_status(s, uni)
        if h.get("status") != "compliant":
            out.append({"symbol": s, "status": h.get("status") or "unknown",
                        "reason": "; ".join((h.get("reasons") or [])[:2]) or "no reason recorded"})
    return out


def build(date, cfg, run_failed=None):
    """-> the email as data: kind (picks | none | failed), subject and every section in order."""
    daily, problem = load_daily(date)
    if run_failed:
        problem = "tayyib-daily failed: %s" % run_failed + ("; " + problem if problem else "")
    rep = {"date": date.isoformat(), "day": long_day(date), "version": tc.VERSION, "footer": FOOTER % tc.VERSION,
           "personal_note": PERSONAL_NOTE, "held_not_compliant": held_not_compliant(), "tracker": tracker_view(date)}
    if problem:
        rep.update(kind="failed", subject=SUBJECT_FAILED, problem=problem, banners=[], picks=[], others=[],
                   notes=[], counts={})
        return rep
    rows = daily.get("rows") or []
    counts = {k: sum(1 for r in rows if r.get("risk") == k) for k in ("PASS", "WARN", "BLOCK")}
    top = [s for s in daily.get("top_picks") or []]
    by_sym = {r["symbol"]: r for r in rows}
    picks = [card(by_sym[s]) for s in top if s in by_sym]
    others = [other_row(r) for r in rows if r["symbol"] not in top]
    banners = ([daily["banner"]] if daily.get("banner") else []) + list(daily.get("banners") or [])
    if picks:
        subject = "tayyib: %s for %s (PASS %d · WARN %d)" % (tc.plural(len(picks), "pick"), rep["day"],
                                                             counts["PASS"], counts["WARN"])
    else:
        subject = SUBJECT_NONE
    rep.update(kind="picks" if picks else "none", subject=subject, problem=None, banners=banners, picks=picks,
               others=others, counts=counts, notes=list(daily.get("notes") or []),
               asof=daily.get("asof"), capital=rs(daily.get("capital")), settings=(daily.get("settings") or {}).get("label"),
               broker=daily.get("broker"), risk_pct=daily.get("risk_per_trade_pct"))
    return rep


ORDER = ("problem", "held_not_compliant", "banners", "picks", "others", "tracker", "notes", "personal_note", "footer")


def render_text(rep):
    L = [rep["subject"], ""]
    if rep.get("problem"):
        L += ["RUN FAILED / DATA STALE (%s)" % rep["day"], rep["problem"],
              "No picks are shown: an older list is never presented as today's. Run tayyib-daily again, or open "
              "the dashboard.", ""]
    if rep["held_not_compliant"]:
        L.append("!! HELD BUT NO LONGER COMPLIANT: check these positions (a full alert comes in a later version)")
        L += ["  %s: %s (%s)" % (h["symbol"], h["status"], h["reason"]) for h in rep["held_not_compliant"]]
        L.append("")
    for b in rep["banners"]:
        L += ["WARNING: " + b, ""]
    if rep["picks"]:
        L.append("TOP PICKS (PASS) for %s" % rep["day"])
        for i, c in enumerate(rep["picks"], 1):
            L += ["", "%d. %s  %s %s  check %s" % (i, c["symbol"], c["mode"], c["setup"], c["check"]),
                  "   buy above %s · stop %s (-%s) · target %s" % (c["entry"], c["stop"], c["stop_pct"], c["target"]),
                  "   qty %s · position %s · loss at stop %s" % (c["qty"], c["position"], c["loss_at_stop"]),
                  "   time machine %s (%s past trades) · valid until %s" % (c["expectancy"], c["past_trades"],
                                                                           c["valid_until"])]
            L += ["   %s %s" % (w["mark"], w["text"]) for w in c["why"]]
        L.append("")
    elif rep["kind"] == "none":
        L += ["No PASS picks for %s. The other rows are below with their checks." % rep["day"], ""]
    if rep["others"]:
        L.append("OTHER ROWS")
        L += ["  %-12s %-6s %s %s · buy above %s · stop %s · %s" % (o["symbol"], o["check"], o["mode"], o["setup"],
                                                                   o["entry"], o["stop"], o["reason"])
              for o in rep["others"]]
        L.append("")
    t = rep["tracker"]
    if t:
        L += ["PAPER TRACKER", "  open paper trades: %d (waiting for entry: %d)" % (t["open"], t["waiting"]),
              "  closed in %s: %s" % (t["month"], t["month_text"])]
        L += ["  %s: %s" % (b["check"], b["win_rate"]) for b in t["by_check"]]
        L.append("")
    else:
        L += ["PAPER TRACKER: no paper trades recorded yet.", ""]
    if rep["notes"]:
        L.append("NOTES")
        L += ["  - " + n.replace("Rs ", "₹") for n in rep["notes"]]
        L.append("")
    L += [rep["personal_note"], "", rep["footer"]]
    return "\n".join(L) + "\n"


# Inline CSS only (mail apps drop <style> and never load web fonts or images); tables for layout.
C = {"ink": "#1f2a2e", "muted": "#5b6b70", "line": "#dfe3df", "bg": "#f6f4ee", "card": "#ffffff",
     "warn_bg": "#fff4d6", "warn_ink": "#7a4b00", "bad_bg": "#fde8e6", "bad_ink": "#9b1c12", "brand": "#0d4d4b"}
FONT = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"


def _e(x):
    return html.escape("" if x is None else str(x))


def _box(inner, bg, ink, border):
    return ('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="margin:0 0 12px 0;'
            'border-collapse:separate;"><tr><td style="background:%s;color:%s;border:1px solid %s;border-left:6px solid '
            '%s;border-radius:8px;padding:12px 14px;font-size:14px;line-height:1.45;">%s</td></tr></table>'
            % (bg, ink, border, ink, inner))


def render_html(rep):
    H = []
    if rep.get("problem"):
        H.append(_box('<b>&#9888; Run FAILED / data stale (%s)</b><br>%s<br><span style="font-size:13px;">No picks are '
                      'shown: an older list is never presented as today\'s. Run tayyib-daily again, or open the '
                      'dashboard.</span>' % (_e(rep["day"]), _e(rep["problem"])), C["bad_bg"], C["bad_ink"], "#f3b8b1"))
    if rep["held_not_compliant"]:
        items = "".join("<li><b>%s</b>: %s (%s)</li>" % (_e(h["symbol"]), _e(h["status"]), _e(h["reason"]))
                        for h in rep["held_not_compliant"])
        H.append(_box('<b>&#9888; Held but no longer compliant</b><br><span style="font-size:13px;">Check these '
                      'positions (a full alert comes in a later version).</span><ul style="margin:6px 0 0 18px;'
                      'padding:0;">%s</ul>' % items, C["bad_bg"], C["bad_ink"], "#f3b8b1"))
    for b in rep["banners"]:
        H.append(_box("<b>&#9888; Warning:</b> " + _e(b), C["warn_bg"], C["warn_ink"], "#f0d58a"))
    if rep["picks"]:
        H.append('<h2 style="font-size:17px;margin:18px 0 8px;color:%s;">Top picks (PASS)</h2>' % C["ink"])
        for i, c in enumerate(rep["picks"], 1):
            cells = [("Buy above", c["entry"]), ("Stop", "%s (&minus;%s)" % (_e(c["stop"]), _e(c["stop_pct"]))),
                     ("Target", c["target"]), ("Qty", c["qty"]), ("Position", c["position"]),
                     ("Loss at stop", c["loss_at_stop"]), ("Time machine", "%s (%s past)" % (_e(c["expectancy"]),
                                                                                           _e(c["past_trades"]))),
                     ("Valid until", c["valid_until"])]
            grid = "".join('<td style="padding:4px 10px 4px 0;vertical-align:top;width:50%%;"><span style="font-size:'
                           '12px;color:%s;">%s</span><br><b style="font-size:15px;">%s</b></td>%s'
                           % (C["muted"], _e(k), v if "&" in str(v) else _e(v), "</tr><tr>" if j % 2 else "")
                           for j, (k, v) in enumerate(cells))
            why = "".join('<div style="font-size:13px;color:%s;margin-top:2px;">%s %s</div>'
                          % (C["ink"] if w["mark"] == "✓" else C["bad_ink"], _e(w["mark"]), _e(w["text"]))
                          for w in c["why"])
            H.append('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="margin:0 0 12px;'
                     'background:%s;border:1px solid %s;border-radius:10px;"><tr><td style="padding:14px;">'
                     '<div style="font-size:18px;font-weight:700;color:%s;">%d. %s <span style="font-size:12px;'
                     'font-weight:700;border:1px solid %s;border-radius:10px;padding:1px 8px;">&#10003; %s</span></div>'
                     '<div style="font-size:13px;color:%s;margin:2px 0 8px;">%s &middot; %s %s</div>'
                     '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0"><tr>%s</tr></table>'
                     '<div style="margin-top:8px;border-top:1px solid %s;padding-top:6px;"><div style="font-size:12px;'
                     'color:%s;">Why (first lines; the full list is in the attachment and the dashboard)</div>%s</div>'
                     '</td></tr></table>'
                     % (C["card"], C["line"], C["brand"], i, _e(c["symbol"]), C["brand"], _e(c["check"]), C["muted"],
                        _e(c["name"]), _e(c["mode"]), _e(c["setup"]), grid, C["line"], C["muted"], why))
    elif rep["kind"] == "none":
        H.append('<p style="font-size:15px;">No PASS picks for %s. The other rows are below with their checks.</p>'
                 % _e(rep["day"]))
    if rep["others"]:
        rows = "".join('<tr><td style="padding:6px 6px 6px 0;border-top:1px solid %s;vertical-align:top;"><b>%s</b>'
                       '<br><span style="font-size:12px;color:%s;">%s %s</span></td><td style="padding:6px;border-top:'
                       '1px solid %s;vertical-align:top;white-space:nowrap;"><b>%s</b></td><td style="padding:6px 0 6px '
                       '6px;border-top:1px solid %s;vertical-align:top;font-size:12px;color:%s;">%s &middot; stop %s'
                       '<br>%s</td></tr>' % (C["line"], _e(o["symbol"]), C["muted"], _e(o["mode"]), _e(o["setup"]),
                                             C["line"], _e(o["check"]), C["line"], C["muted"],
                                             "buy above " + _e(o["entry"]), _e(o["stop"]), _e(o["reason"]))
                       for o in rep["others"])
        H.append('<h2 style="font-size:17px;margin:18px 0 8px;color:%s;">Other rows</h2><table role="presentation" '
                 'width="100%%" cellpadding="0" cellspacing="0" style="font-size:14px;color:%s;">%s</table>'
                 % (C["ink"], C["ink"], rows))
    t = rep["tracker"]
    if t:
        by = "".join("<li>%s: %s</li>" % (_e(b["check"]), _e(b["win_rate"])) for b in t["by_check"])
        H.append('<h2 style="font-size:17px;margin:18px 0 8px;color:%s;">Paper tracker</h2><div style="font-size:14px;">'
                 'Open paper trades: <b>%d</b> (waiting for entry: %d)<br>Closed in %s: <b>%s</b><br>Win rate by check:<ul style="margin:4px 0 0 18px;padding:0;">%s</ul></div>'
                 % (C["ink"], t["open"], t["waiting"], _e(t["month"]), _e(t["month_text"]), by))
    else:
        H.append('<p style="font-size:14px;color:%s;">Paper tracker: no paper trades recorded yet.</p>' % C["muted"])
    if rep["notes"]:
        H.append('<h2 style="font-size:15px;margin:18px 0 6px;color:%s;">Notes</h2><ul style="margin:0 0 0 18px;padding:0;'
                 'font-size:13px;color:%s;">%s</ul>' % (C["ink"], C["muted"], "".join(
                     "<li>%s</li>" % _e(n.replace("Rs ", "₹")) for n in rep["notes"])))
    H.append('<p style="font-size:12px;color:%s;margin-top:20px;">%s</p><p style="font-size:12px;color:%s;border-top:1px '
             'solid %s;padding-top:10px;">%s</p>' % (C["muted"], _e(rep["personal_note"]), C["muted"], C["line"],
                                                    _e(rep["footer"])))
    head = ('<div style="font-size:12px;color:%s;letter-spacing:.04em;text-transform:uppercase;">tayyib &middot; %s</div>'
            '<h1 style="font-size:20px;margin:4px 0 14px;color:%s;">%s</h1>' % (C["muted"], _e(rep["day"]), C["ink"],
                                                                               _e(rep["subject"])))
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            'initial-scale=1"><title>%s</title></head><body style="margin:0;padding:0;background:%s;%s">'
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0"><tr><td align="center" '
            'style="padding:16px 10px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'style="max-width:640px;color:%s;%s"><tr><td>%s%s</td></tr></table></td></tr></table></body></html>'
            % (_e(rep["subject"]), C["bg"], FONT, C["ink"], FONT, head, "".join(H)))


def message(rep, cfg, frm, to, attach=True):
    msg = EmailMessage()
    msg["Subject"] = rep["subject"]
    if frm:
        msg["From"] = frm
    if to:
        msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="tayyib-trader.local")
    msg.set_content(render_text(rep))
    msg.add_alternative(render_html(rep), subtype="html")
    md = os.path.join(tc.data_dir(), "daily", rep["date"] + ".md")
    if attach and cfg["email"].get("attach_md") and rep["kind"] != "failed" and os.path.exists(md):
        with open(md, "rb") as f:
            msg.add_attachment(f.read(), maintype="text", subtype="markdown", filename=rep["date"] + ".md")
    return msg


def test_message(frm, to):
    msg = EmailMessage()
    msg["Subject"] = "tayyib: test email"
    msg["From"] = frm
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="tayyib-trader.local")
    msg.set_content("This is a test from tayyib-trader on your computer (v%s), sent %s IST to %s.\n\nIf you can "
                    "read this, email works. Switch it on in Settings, Email, and schedule the daily run.\n\n%s\n\n%s\n"
                    % (tc.VERSION, tc.now_ist().strftime("%Y-%m-%d %H:%M"), tc.plural(len(to), "address", "addresses"),
                       PERSONAL_NOTE, FOOTER % tc.VERSION))
    return msg


# --- sending and the log ---------------------------------------------------------------------------

def scrub(text, cfg, pw=None):
    """An error text with no password and no address in it (it goes to the log and the dashboard)."""
    text = str(text)
    if pw:
        text = text.replace(pw, "***")
    e = cfg["email"]
    for a in sorted(set([e.get("from") or ""] + list(e.get("to") or [])), key=len, reverse=True):
        if a:
            text = text.replace(a, "<address>")
    return text


def describe(err):
    """The exact SMTP error, readable."""
    if isinstance(err, smtplib.SMTPResponseException):
        m = err.smtp_error.decode("utf-8", "replace") if isinstance(err.smtp_error, bytes) else str(err.smtp_error)
        s = "%s %d: %s" % (type(err).__name__, err.smtp_code, " ".join(m.split()))
    elif isinstance(err, smtplib.SMTPRecipientsRefused):
        s = "SMTPRecipientsRefused: %s" % "; ".join("%s %s" % (c, (m.decode("utf-8", "replace") if isinstance(
            m, bytes) else str(m))) for c, m in err.recipients.values())
    else:
        s = "%s: %s" % (type(err).__name__, err)
    if isinstance(err, smtplib.SMTPAuthenticationError):
        s += (" (the login was refused: for Gmail use an App Password, made under Google account > Security > "
              "2-Step Verification > App passwords, not your normal password)")
    return s


def smtp_send(cfg, msg, frm, to, pw):
    """Send over SSL (465) or STARTTLS (587), certificate checked. Raises smtplib / OS errors."""
    e = cfg["email"]
    host, port = e["smtp_host"], int(e["smtp_port"])
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
    try:
        if port != 465:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
        s.login(frm, pw)
        s.send_message(msg, from_addr=frm, to_addrs=to)
    finally:
        try:
            s.quit()
        except Exception:
            pass


def log(entry):
    """Append to trader/email/log.json: date, time, command, status, recipient count, error. No addresses, no secrets."""
    p = os.path.join(tc.data_dir(), "email", "log.json")
    try:
        cur = tc.read_json(p, {"entries": []}) or {"entries": []}
    except ValueError:
        cur = {"entries": []}
    e = {"at": tc.now_ist().isoformat(timespec="seconds")}
    e.update(entry)
    cur["entries"] = (cur.get("entries") or [])[-(LOG_KEEP - 1):] + [e]
    tc.write_json(p, cur)
    return e


def result(status, **kw):
    out = {"status": status}
    out.update(kw)
    return out


def do_test(cfg):
    frm, to = recipients(cfg)
    pw = password()
    if not pw:
        log({"date": tc.today_ist().isoformat(), "command": "test", "status": "failed", "recipients": len(to),
             "error": "password not set"})
        raise Problem(PASSWORD_MISSING)
    if not frm:
        raise Problem(FROM_MISSING)
    try:
        smtp_send(cfg, test_message(frm, to), frm, to, pw)
    except (smtplib.SMTPException, OSError) as err:
        msg = scrub(describe(err), cfg, pw)
        log({"date": tc.today_ist().isoformat(), "command": "test", "status": "failed", "recipients": len(to),
             "error": msg})
        raise Problem("the test email was not sent: %s" % msg, 1)
    log({"date": tc.today_ist().isoformat(), "command": "test", "status": "sent", "recipients": len(to), "error": None})
    return result("sent", message="test email sent to %s via %s:%s: check your inbox (and the spam folder)"
                  % (tc.plural(len(to), "address", "addresses"), cfg["email"]["smtp_host"], cfg["email"]["smtp_port"]),
                  recipients=len(to))


def do_send(cfg, date, dry_run=False, scheduled=False, run_failed=None):
    """-> result dict. Writes only trader/email/ (the .eml on a dry run, and the log)."""
    cmd = "dry_run" if dry_run else "scheduled" if scheduled else "send"
    base = {"date": date.isoformat(), "command": cmd}
    if scheduled and not cfg["email"].get("enabled"):
        log(dict(base, status="skipped", recipients=0, error="email is off (Settings, Email)"))
        return result("skipped", message="email is off: nothing sent (switch it on in Settings, Email)")
    if not tc.is_trading_day(date, cfg):
        log(dict(base, status="market_closed", recipients=0, error=None))
        return result("market_closed", message="market closed on %s (weekend or a holiday in your settings): nothing "
                                               "sent" % date.isoformat())
    frm, to = recipients(cfg)
    rep = build(date, cfg, run_failed)
    if cfg["email"].get("send_when") == "picks_only" and rep["kind"] == "none" and not dry_run:
        log(dict(base, status="skipped", recipients=0, kind=rep["kind"], error="no picks (send_when picks_only)"))
        return result("skipped", kind=rep["kind"], subject=rep["subject"],
                      message="no picks today and email.send_when is picks_only: nothing sent")
    msg = message(rep, cfg, frm, to)
    if dry_run:
        d = os.path.join(tc.data_dir(), "email")
        os.makedirs(d, exist_ok=True)
        eml, htm = os.path.join(d, date.isoformat() + ".eml"), os.path.join(d, date.isoformat() + ".html")
        with open(eml, "wb") as f:
            f.write(msg.as_bytes())
        with open(htm, "w", encoding="utf-8") as f:
            f.write(render_html(rep))
        log(dict(base, status="dry_run", recipients=len(to), kind=rep["kind"], error=None))
        return result("dry_run", kind=rep["kind"], subject=rep["subject"], eml=eml, html=htm, recipients=len(to),
                      message="nothing sent: the email is in %s (open %s in a browser to look at it)%s"
                      % (eml, htm, "" if frm else "; email.from is not set, so it has no From / To"))
    pw = password()
    if not pw:
        log(dict(base, status="skipped", recipients=len(to), kind=rep["kind"], error="password not set"))
        if scheduled:
            return result("skipped", kind=rep["kind"], message=SKIPPED_NO_PASSWORD)
        raise Problem(PASSWORD_MISSING)
    if not frm:
        log(dict(base, status="skipped", recipients=0, kind=rep["kind"], error="email.from not set"))
        if scheduled:
            return result("skipped", kind=rep["kind"], message="email skipped: email.from is not set")
        raise Problem(FROM_MISSING)
    try:
        smtp_send(cfg, msg, frm, to, pw)
    except (smtplib.SMTPException, OSError) as err:
        m = scrub(describe(err), cfg, pw)
        log(dict(base, status="failed", recipients=len(to), kind=rep["kind"], error=m))
        raise Problem("not sent: %s" % m, 1)
    log(dict(base, status="sent", recipients=len(to), kind=rep["kind"], error=None))
    return result("sent", kind=rep["kind"], subject=rep["subject"], recipients=len(to),
                  message="sent to %s: %s" % (tc.plural(len(to), "address", "addresses"), rep["subject"]))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("test", help="send a short test email")
    t.add_argument("--json", action="store_true")
    s = sub.add_parser("send", help="send the list of a day (default today)")
    s.add_argument("--date", help="YYYY-MM-DD (default today)")
    s.add_argument("--dry-run", action="store_true", help="write trader/email/DATE.eml, send nothing (no password needed)")
    s.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)      # tayyib-daily --email
    s.add_argument("--run-failed", default=None, help=argparse.SUPPRESS)            # why tayyib-daily failed
    s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    cfg = tc.load_config()
    try:
        if a.cmd == "test":
            out = do_test(cfg)
        else:
            try:
                date = tc.parse_date(a.date) if a.date else tc.today_ist()
            except ValueError:
                raise Problem("--date must be YYYY-MM-DD")
            if date > tc.today_ist():
                raise Problem("--date %s is in the future" % date.isoformat())
            out = do_send(cfg, date, dry_run=a.dry_run, scheduled=a.scheduled, run_failed=a.run_failed)
    except Problem as e:
        if getattr(a, "json", False):
            tc.print_json(result("error", error=str(e)))
        sys.stderr.write("error: %s\n" % e)
        return e.code
    if a.json:
        tc.print_json(out)
    else:
        print(out["message"])
        if a.cmd == "send" and out["status"] in ("dry_run", "sent"):
            print(PERSONAL_NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
