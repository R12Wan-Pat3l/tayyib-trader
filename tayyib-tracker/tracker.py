#!/usr/bin/env python3
"""tayyib-tracker: did yesterday's list work? A paper-trading record, in Excel.

Every stock the daily list shows is recorded (PASS, WARN and BLOCK alike, so
you can see whether the checks were right). Each later run follows it on the
real prices with the plan's own rules: did it reach the buy price, then the
target or the stop first? Result in R and rupees after charges.

  add --from-daily [DATE]   record a day's list (tayyib-daily does this itself)
  update                    follow every unfinished row on the latest prices
  report                    win rate, average R and P&L, by check, mode and setup
  export                    trader/tracker.xlsx (Excel) and trader/tracker.csv

Paper only: nothing is bought. Statuses: WAITING (buy price not reached yet),
NOT TRIGGERED (never reached in its valid days), OPEN, TARGET, STOP,
BREAKEVEN (stop had moved to the buy price), TIME EXIT.
"""
import argparse
import csv
import datetime as dt
import io
import os
import sys
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

COLUMNS = [("date", "List date"), ("symbol", "Stock"), ("name", "Company"), ("mode", "Mode"),
           ("setup", "Setup"), ("check", "Check"), ("entry", "Buy above"), ("stop", "Stop"),
           ("target", "Target"), ("qty", "Qty"), ("risk_rs", "Risk Rs"), ("valid_until", "Buy valid until"),
           ("expectancy_r", "Time machine R"), ("status", "Status"), ("filled", "Bought on"),
           ("fill", "Buy price"), ("exited", "Exit on"), ("exit", "Exit price"), ("days", "Days held"),
           ("r", "Result R"), ("pnl_rs", "P&L Rs"), ("last", "Last close"), ("checked", "Checked"),
           ("settings_hash", "Settings")]
PRE = "pre-0.1.5"          # rows recorded before settings were tracked
# hashes from before DEFAULTS_VERSION existed (v0.1.5 as first committed hashed every value): the
# rows keep them, and the summary counts them under the label they stand for
LEGACY_LABELS = {"cf8b2136": "default@1"}


def load():
    store = tc.read_json("tracker.json", {"rows": []}) or {"rows": []}
    store.setdefault("rows", [])
    store.setdefault("settings", {})
    for r in store["rows"]:
        r.setdefault("settings_hash", PRE)
    return store


def save(store):
    """tracker.json: the rows, what each settings hash changed from the defaults, and the summary."""
    store["summary"] = summary(store["rows"], store)
    store["settings_split"] = settings_split(store)
    tc.write_json("tracker.json", store)


def key(r):
    return "%s|%s|%s" % (r["date"], r["symbol"], r["setup"])


def add_from_daily(store, date):
    d = tc.read_json(os.path.join("daily", date + ".json"))
    if not d:
        return 0, "no daily list for %s" % date
    st = d.get("settings") or {}
    h = st.get("hash") or PRE
    if st.get("hash"):
        store.setdefault("settings", {}).setdefault(h, {
            "label": st.get("label") or LEGACY_LABELS.get(h) or h, "first_seen": d["date"],
            "differs_from_default": st.get("differs_from_default") or []})
    have = {key(r) for r in store["rows"]}
    n = 0
    for r in d.get("rows", []):
        if r.get("entry") is None or r.get("stop") is None or r.get("target") is None:
            continue
        row = {"date": d["date"], "symbol": r["symbol"], "name": r.get("name", ""), "mode": r["mode"],
               "setup": r["setup"], "check": r.get("risk"), "entry": r["entry"], "stop": r["stop"],
               "target": r["target"], "qty": r.get("qty"), "risk_rs": r.get("loss_at_stop_rs"),
               "valid_until": r.get("valid_until"), "max_hold_days": r.get("max_hold_days"),
               "expectancy_r": r.get("expectancy_r"), "status": "WAITING", "settings_hash": h}
        if key(row) not in have:
            store["rows"].append(row)
            have.add(key(row))
            n += 1
    return n, None


def update(store, cfg):
    todo = [r for r in store["rows"] if r.get("status") not in tc.FINAL_OUTCOMES]
    bars_by, errors = {}, []
    for r in todo:
        s = r["symbol"]
        if s not in bars_by:
            try:
                bars_by[s] = tc.get_daily_bars(s)[0]
            except tc.FetchError as e:
                bars_by[s] = None
                errors.append("%s: %s" % (s, e))
        if bars_by[s] is None:
            continue
        plan = dict(r, date=r["date"])
        if not plan.get("max_hold_days"):
            plan["max_hold_days"] = cfg["modes"][r["mode"]]["max_hold_days"]
        r.update(tc.trade_outcome(bars_by[s], plan, cfg))
    return len(todo), errors


def settings_group(store, h):
    """The label a row's settings_hash is counted under: default@N, the hash, or pre-0.1.5."""
    h = h or PRE
    if h == PRE:
        return PRE
    if h in LEGACY_LABELS:
        return LEGACY_LABELS[h]
    return ((store or {}).get("settings") or {}).get(h, {}).get("label") or h


def summary(rows, store=None):
    def stats(group):
        closed = [r for r in group if r.get("status") in ("TARGET", "STOP", "BREAKEVEN", "TIME EXIT")]
        trig = [r for r in group if r.get("filled")]
        rs = [r["r"] for r in closed if r.get("r") is not None]
        return {"listed": len(group), "triggered": len(trig), "closed": len(closed),
                "open": sum(r.get("status") == "OPEN" for r in group),
                "waiting": sum(r.get("status") == "WAITING" for r in group),
                "not_triggered": sum(r.get("status") == "NOT TRIGGERED" for r in group),
                "target": sum(r.get("status") == "TARGET" for r in group),
                "stop": sum(r.get("status") == "STOP" for r in group),
                "breakeven": sum(r.get("status") == "BREAKEVEN" for r in group),
                "time_exit": sum(r.get("status") == "TIME EXIT" for r in group),
                "win_rate_pct": round(sum(x > 0 for x in rs) / len(rs) * 100, 1) if rs else None,
                "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
                "total_r": round(sum(rs), 2) if rs else None,
                "pnl_rs": round(sum(r.get("pnl_rs") or 0 for r in closed), 2)}
    out = {"all": stats(rows)}
    for field in ("check", "mode", "setup"):
        for v in sorted({r.get(field) or "-" for r in rows}):
            out["%s: %s" % (field, v)] = stats([r for r in rows if (r.get(field) or "-") == v])
    for g in sorted({settings_group(store, r.get("settings_hash")) for r in rows}):
        out["settings: %s" % g] = stats([r for r in rows if settings_group(store, r.get("settings_hash")) == g])
    return out


def settings_label(store, g):
    """What a settings group (default@N, a hash, or pre-0.1.5) changed from the defaults, in words."""
    if g == PRE:
        return "recorded before v0.1.5: settings not known"
    if g.startswith("default@"):
        return "all defaults (defaults version %s)" % g.split("@", 1)[1]
    info = (store.get("settings") or {}).get(g)
    if info is None:
        return "UNKNOWN: not in tracker.json"
    d = info.get("differs_from_default") or []
    if not d:
        return "all defaults"
    return "; ".join("%s %s (default %s)" % (x["key"], tc._fmt_val(x["value"]), tc._fmt_val(x["default"]))
                     for x in d)


def settings_split(store):
    """{label: {differs, hashes, first_seen, stats}} so results can be compared settings by settings."""
    rows = store["rows"]
    out = {}
    for g in sorted({settings_group(store, r.get("settings_hash")) for r in rows}):
        mine = [r for r in rows if settings_group(store, r.get("settings_hash")) == g]
        hashes = sorted({r.get("settings_hash") or PRE for r in mine})
        infos = [(store.get("settings") or {}).get(h) or {} for h in hashes]
        seen = [i["first_seen"] for i in infos if i.get("first_seen")]
        out[g] = {"differs": settings_label(store, g), "hashes": hashes, "first_seen": min(seen) if seen else None,
                  "differs_from_default": next((i.get("differs_from_default") for i in infos if i), None),
                  "stats": summary(mine)["all"]}
    return out


# --- minimal .xlsx writer (standard library only) ---------------------------

def _col(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _sheet_xml(rows, widths):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
           'state="frozen"/></sheetView></sheetViews><cols>']
    for i, w in enumerate(widths, 1):
        out.append('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i, i, w))
    out.append("</cols><sheetData>")
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, v in enumerate(row, 1):
            ref = "%s%d" % (_col(ci), ri)
            style = ' s="1"' if ri == 1 else ""
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append('<c r="%s"%s><v>%s</v></c>' % (ref, style, v))
            elif v not in (None, ""):
                cells.append('<c r="%s" t="inlineStr"%s><is><t>%s</t></is></c>' % (ref, style, escape(str(v))))
        out.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
    out.append("</sheetData>")
    if len(rows) > 1:
        out.append('<autoFilter ref="A1:%s%d"/>' % (_col(len(rows[0])), len(rows)))
    out.append("</worksheet>")
    return "".join(out)


def write_xlsx(path, sheets):
    """sheets: [(name, rows, widths)] -> a real .xlsx Excel opens directly."""
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook '
          'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i, (name, _, _) in enumerate(sheets, 1):
        ct.append('<Override PartName="/xl/worksheets/sheet%d.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i)
        wb.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name), i, i))
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i))
    n = len(sheets)
    rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/styles" Target="styles.xml"/></Relationships>' % (n + 1))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet '
              'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct) + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", "".join(wb) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        z.writestr("xl/styles.xml", styles)
        for i, (_, rows, widths) in enumerate(sheets, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, _sheet_xml(rows, widths))
    try:
        os.replace(tmp, path)
    except PermissionError:                              # Excel has the file open (Windows)
        alt = path.replace(".xlsx", "-%s.xlsx" % tc.now_ist().strftime("%H%M%S"))
        os.replace(tmp, alt)
        return alt
    return path


def export(store):
    rows = sorted(store["rows"], key=lambda r: (r["date"], r["symbol"]), reverse=True)
    table = [[label for _, label in COLUMNS]] + [[r.get(k) for k, _ in COLUMNS] for r in rows]
    widths = [11, 12, 26, 9, 10, 7, 10, 10, 10, 6, 9, 14, 14, 14, 11, 10, 11, 10, 9, 9, 10, 10, 11, 11]
    summ = summary(store["rows"], store)
    sheads = ["Group", "Listed", "Bought (triggered)", "Closed", "Open", "Waiting", "Not triggered",
              "Target", "Stop", "Breakeven", "Time exit", "Win rate %", "Avg R", "Total R", "P&L Rs",
              "Settings vs defaults"]
    srows = [sheads] + [[g, s["listed"], s["triggered"], s["closed"], s["open"], s["waiting"],
                         s["not_triggered"], s["target"], s["stop"], s["breakeven"], s["time_exit"],
                         s["win_rate_pct"], s["avg_r"], s["total_r"], s["pnl_rs"],
                         settings_label(store, g[len("settings: "):]) if g.startswith("settings: ") else None]
                        for g, s in summ.items()]
    note = [["How to read this"],
            ["Paper record of every stock the daily list showed. Nothing was bought."],
            ["Bought = the price reached 'Buy above' within its valid days (a buy-stop would have filled)."],
            ["Result R = profit or loss in units of the planned risk, after Indian charges (+2R = twice the risk)."],
            ["A day that touched both the stop and the target counts as the stop (conservative)."],
            ["Compare 'check: PASS' with 'check: BLOCK' in the Summary to see whether the risk check helped."],
            ["'settings: ...' rows split the results by the settings each list was made with: default@1 = all "
             "defaults, a code like abcd1234 = your changes (the last column says which). pre-0.1.5 = recorded "
             "before settings were tracked."],
            ["Results from a few weeks are noise. Judge after 30+ closed trades."],
            [tc.DISCLAIMER]]
    xlsx = write_xlsx(tc.path("tracker.xlsx"), [("Tracker", table, widths),
                                                 ("Summary", srows, [22] + [12] * 14 + [70]),
                                                 ("Read me", note, [110])])
    with open(tc.path("tracker.csv"), "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(table)
    return xlsx


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add")
    ad.add_argument("--from-daily", nargs="?", const="", default=None, metavar="DATE")
    sub.add_parser("update")
    sub.add_parser("report")
    sub.add_parser("export")
    for sp in sub.choices.values():
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    store = load()

    if a.cmd == "add":
        date = a.from_daily or tc.today_ist().isoformat()
        n, err = add_from_daily(store, date)
        save(store)
        if a.json:
            return tc.print_json({"added": n, "error": err})
        print(err or "recorded %d stock(s) from the %s list" % (n, date))
        return
    if a.cmd == "update":
        n, errors = update(store, cfg)
        save(store)
        if a.json:
            return tc.print_json({"checked": n, "errors": errors})
        print("followed %d unfinished row(s) on the latest prices" % n)
        for e in errors:
            print("  price error %s" % e)
        return
    if a.cmd == "export":
        path = export(store)
        if a.json:
            return tc.print_json({"xlsx": path, "csv": tc.path("tracker.csv"), "rows": len(store["rows"])})
        print("wrote %s and trader/tracker.csv (%d rows)" % (path, len(store["rows"])))
        return
    summ = summary(store["rows"], store)
    recent = sorted(store["rows"], key=lambda r: (r["date"], r["symbol"]), reverse=True)[:15]
    split = settings_split(store)
    if a.json:
        return tc.print_json({"summary": summ, "recent": recent, "settings_split": split})
    s = summ["all"]
    print("Tracker: %d listed, %d bought, %d closed (%d target, %d stop, %d breakeven, %d time), %d open, "
          "%d waiting, %d not triggered" % (s["listed"], s["triggered"], s["closed"], s["target"], s["stop"],
                                            s["breakeven"], s["time_exit"], s["open"], s["waiting"], s["not_triggered"]))
    if s["closed"]:
        print("  closed trades: win rate %s%%, average %+.2fR, total %+.2fR, P&L %s"
              % (s["win_rate_pct"], s["avg_r"], s["total_r"], tc.fmt_rs(s["pnl_rs"])))
    for g, v in summ.items():
        if g != "all" and v["closed"]:
            print("  %-22s %3d closed, win %5s%%, avg %+.2fR" % (g, v["closed"], v["win_rate_pct"], v["avg_r"]))
    if len(split) > 1 or PRE not in split:
        print("By settings:")
        for h, v in split.items():
            st = v["stats"]
            print("  %-10s %3d listed, %3d closed, win %5s%%, avg %s  (%s)"
                  % (h, st["listed"], st["closed"], "-" if st["win_rate_pct"] is None else st["win_rate_pct"],
                     "-" if st["avg_r"] is None else "%+.2fR" % st["avg_r"], v["differs"]))
    print("Recent:")
    for r in recent:
        res = "" if r.get("r") is None else " %+.2fR" % r["r"]
        print("  %s %-12s %-8s %-9s %-6s %s%s" % (r["date"], r["symbol"], r["mode"], r["setup"], r["check"] or "-",
                                                   r["status"], res))
    if s["closed"] < 30:
        print("Fewer than 30 closed trades: too few to judge the list yet.")


if __name__ == "__main__":
    main()
