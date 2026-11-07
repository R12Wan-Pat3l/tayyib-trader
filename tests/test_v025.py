"""v0.2.5: pullback off by default (default@3, historic since v0.2.6; with it on, every decision is the default@2 one), the import of your
real holdings from a Zerodha / Groww export (read only, preview first, holdings are not trades), and fixes: the
"status at purchase unknown" wording, risk-off date ranges in the backtest. Offline: fixtures only; the export
files are built here (small CSV and XLSX files, standard library only). Nothing is placed anywhere."""
import io
import json
import os
import subprocess
import sys
import time
import unittest
import zipfile
from xml.sax.saxutils import escape

from _util import FIX, NOW, ROOT, OfflineCase, tc
from test_v018 import ServerCase
import baseline

for d in ("tayyib-backtest", "tayyib-dashboard"):
    sys.path.insert(0, os.path.join(ROOT, d))
import backtest as bt  # noqa: E402
import dashboard as DASH  # noqa: E402
import actions as A  # noqa: E402

TICKET = "tayyib-broker/ticket.py"


# --- export files, built here ----------------------------------------------------------------------------

def write_xlsx(fn, rows, second=None):
    """A minimal .xlsx: text in shared strings (one inline string too), numbers as numbers; an optional second
    sheet (which the import must ignore: first sheet only)."""
    shared, sheets = [], []

    def sheet_xml(rs):
        out = []
        for i, row in enumerate(rs, 1):
            cells = []
            for k, v in enumerate(row):
                ref = "%s%d" % (chr(65 + k) if k < 26 else "A" + chr(65 + k - 26), i)
                if v is None or v == "":
                    continue
                if isinstance(v, (int, float)):
                    cells.append('<c r="%s"><v>%s</v></c>' % (ref, v))
                elif str(v).startswith("~"):                 # an inline string
                    cells.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(str(v)[1:])))
                else:
                    if v not in shared:
                        shared.append(v)
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, shared.index(v)))
            out.append('<row r="%d">%s</row>' % (i, "".join(cells)))
        return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % "".join(out))
    sheets.append(sheet_xml(rows))
    if second:
        sheets.append(sheet_xml(second))
    with zipfile.ZipFile(fn, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships"><sheets>%s</sheets></workbook>' % "".join(
                       '<sheet name="S%d" sheetId="%d" r:id="rId%d"/>' % (k, k, k) for k in range(1, len(sheets) + 1)))
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(
                       '<Relationship Id="rId%d" Target="worksheets/sheet%d.xml" Type="x"/>' % (k, k)
                       for k in range(1, len(sheets) + 1)))
        for k, x in enumerate(sheets, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % k, x)
        z.writestr("xl/sharedStrings.xml", '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main">%s</sst>' % "".join("<si><t>%s</t></si>" % escape(s) for s in shared))


def write_csv(fn, rows):
    import csv
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)


CONSOLE = [["Client ID", "~XX0000"], [], ["Equity Holdings Statement as on 2026-10-30"], [],
           ["Symbol", "ISIN", "Sector", "Quantity Available", "Quantity Discrepant", "Quantity Long Term",
            "Quantity Pledged (Margin)", "Quantity Pledged (Loan)", "Average Price", "Previous Closing Price",
            "Unrealized P&L", "Unrealized P&L Pct."],
           ["ALFA", "INE000A01011", "Capital Goods", 10, 0, 10, 2, 0, 100.5, 120, 234, 19.4],
           ["ECHO", "INE000E01015", "Media", 5, 0, 0, 0, 0, 150, 168, 90, 12],
           ["SMEXYZ-SM", "INE999Z01019", "", 100, 0, 0, 0, 0, 12, 13, 100, 8],
           ["ZZNOPE", "INE998Z01010", "", 3, 0, 0, 0, 0, 40, 41, 3, 2]]
MF_SHEET = [["Symbol", "ISIN", "Quantity Available", "Average Price"], ["SOMEFUND", "INF000X01011", 50, 10]]
KITE = [["Instrument", "Qty.", "Avg. cost", "LTP", "Cur. val", "P&L", "Net chg.", "Day chg."],
        ["ALFA", "12", "100.50", "120", "1440", "234", "19.4", "0.5"],
        ["CHRL-BE", "4", "1900", "1930", "7720", "120", "1.6", "0.2"]]
GROWW = [["Name", "Example Person"], ["Unique Client Code", "0000"], [],
         ["Stock Name", "ISIN", "Quantity", "Average buy price", "Buy value", "Closing price", "Closing value",
          "Unrealised P&L"],
         ["Alfa Industries Ltd.", "INE000A01011", "8", "1,005.50", "8044", "1200", "9600", "1556"],
         ["Charlie Pharma Ltd.", "INE000C01013", "3", "1900", "5700", "1930", "5790", "90"],
         ["Unknown Co Ltd.", "INE777X01011", "2", "50", "100", "55", "110", "10"]]


def position(sym, qty=10, pid=None):
    return {"id": pid or sym + "-2026-10-01-trend", "symbol": sym, "mode": "delivery", "setup": "trend", "qty": qty,
            "entry": 100.0, "stop": 90.0, "initial_stop": 90.0, "target": 130.0, "opened": "2026-10-01",
            "status": "open", "buy_charges_rs": 12.0, "product": "CNC",
            "halal_at_buy": {"status": "compliant", "ratios": {}, "as_of": "2026-03-31", "date": "2026-10-01",
                             "source": "x", "backfilled": False}}


class ImportCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.build_universe()
        os.makedirs(os.path.join(self.dir, "import"), exist_ok=True)

    def f(self, name):
        return os.path.join(self.dir, "import", name)

    def imp(self, name, *args, ok=True):
        return self.run_script(TICKET, "import", self.f(name), *args, ok=ok)

    def by(self, plan):
        return {h["symbol"]: h for h in plan["holdings"]}


# --- A. pullback off by default --------------------------------------------------------------------------

class DefaultsV3(unittest.TestCase):
    """default@3 is historic since v0.2.6 (pullback back on, default@4): its record and its label stay known."""

    def test_default3_record_and_label(self):
        hist = baseline.load_defaults()
        self.assertEqual([k for k in hist["3"] if k in hist["2"] and hist["2"][k] != hist["3"][k]],
                         ["scanner.setups.pullback.enabled"])            # the ONLY default v0.2.5 changed
        self.assertIs(hist["3"]["scanner.setups.pullback.enabled"], False)
        off = tc.settings_snapshot(tc.validate_config(baseline.PULLBACK_OFF)[0])
        self.assertEqual([d["key"] for d in off["differs_from_default"]], ["scanner.setups.pullback.enabled"])
        self.assertEqual(off["same_as"], "default@3")


class BaselineV3(unittest.TestCase):
    """A2: pullback off was v0.2.5's only decision change. Snapshots: tests/fixtures/baseline_default{2,3}.json.gz.
    Since v0.2.6 pullback is on by default again; PULLBACK_OFF reproduces default@3."""

    def test_pullback_on_matches_default2_exactly(self):
        d2 = baseline.load_default_snapshot(2)
        self.assertEqual(d2["defaults_version"], 2)
        self.assertEqual(baseline.diff(d2["pipeline"], baseline.pipeline(config=baseline.PULLBACK_ON)), [])

    def test_default3_snapshot(self):
        d3, d2 = baseline.load_default_snapshot(3), baseline.load_default_snapshot(2)
        cur = baseline.pipeline(config=baseline.PULLBACK_OFF)
        self.assertEqual(baseline.diff(d3["pipeline"], cur), [])
        setups = lambda p: {c.get("setup") for r in p.values() for c in (r["scan"] or [])}
        self.assertIn("pullback", setups(d2["pipeline"]))                # the fixtures do arm a pullback...
        self.assertNotIn("pullback", setups(cur))                         # ...which pullback off leaves out
        self.assertEqual(d2["pipeline"]["delivery"], cur["delivery"])      # delivery never had pullback

    def test_snapshot_writer_refuses_to_rewrite(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "baseline.py"), "--write-default", "3"],
                           capture_output=True, encoding="utf-8")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("refused", p.stderr)                  # since v0.2.6 also: 3 is not the code's version


class Migration(OfflineCase):
    """The v0.2.5 migration (pullback off) was replaced in v0.2.6: see tests/test_v026.py."""

    def test_old_tracker_rows_keep_default2(self):
        import importlib
        sys.path.insert(0, os.path.join(ROOT, "tayyib-tracker"))
        tracker = importlib.import_module("tracker")
        store = {"settings": {"a28d32c9": {"label": "default@2"}, "e0000000": {"label": "default@3"}}}
        self.assertEqual(tracker.settings_group(store, "a28d32c9"), "default@2")
        self.assertEqual(tracker.settings_group(store, "e0000000"), "default@3")


# --- B. holdings import ----------------------------------------------------------------------------------

class Import(ImportCase):
    def test_zerodha_console_xlsx(self):
        write_xlsx(self.f("holdings.xlsx"), CONSOLE, second=MF_SHEET)
        p = self.imp("holdings.xlsx")
        self.assertEqual((p["broker"], p["header_line"], p["written"]), ("zerodha", 5, False))
        h = self.by(p)
        self.assertEqual(sorted(h), ["ALFA", "ECHO"])
        self.assertEqual((h["ALFA"]["qty"], h["ALFA"]["avg_price"], h["ALFA"]["matched_by"]), (12, 100.5, "ISIN"))  # 10 + 2 pledged
        self.assertEqual(p["qty_extra"], ["Quantity Pledged (Margin)", "Quantity Pledged (Loan)"])
        self.assertEqual((h["ALFA"]["halal_now"], h["ALFA"]["alert_level"], h["ALFA"]["action"]), ("compliant", None, "add"))
        self.assertEqual(h["ECHO"]["alert_level"], "BLOCK")
        self.assertEqual(h["ECHO"]["alert"], "Not compliant now (status at purchase unknown)")
        un = {u["label"]: u["reason"] for u in p["could_not_match"]}
        self.assertEqual(sorted(un), ["SMEXYZ-SM", "ZZNOPE"])
        self.assertIn("SME", un["SMEXYZ-SM"])
        self.assertIn("no NSE price data", un["ZZNOPE"])
        self.assertNotIn("SOMEFUND", json.dumps(p))                        # the second sheet is never read
        self.assertFalse(os.path.exists(os.path.join(self.dir, "positions.json")))   # preview writes nothing

    def test_zerodha_kite_csv(self):
        write_csv(self.f("kite.csv"), KITE)
        p = self.imp("kite.csv", "--broker", "zerodha")
        h = self.by(p)
        self.assertEqual((h["ALFA"]["qty"], h["ALFA"]["matched_by"]), (12, "symbol"))
        self.assertEqual((h["CHRL"]["qty"], h["CHRL"]["label"]), (4, "CHRL-BE"))
        self.assertEqual(p["could_not_match"], [])

    def test_groww_csv_and_xlsx_by_isin(self):
        write_csv(self.f("groww.csv"), GROWW)
        write_xlsx(self.f("groww.xlsx"), GROWW)
        for name in ("groww.csv", "groww.xlsx"):
            p = self.imp(name)
            self.assertEqual(p["broker"], "groww", name)
            h = self.by(p)
            self.assertEqual((h["ALFA"]["qty"], h["ALFA"]["avg_price"], h["ALFA"]["matched_by"]), (8, 1005.5, "ISIN"))
            self.assertEqual(h["CHRL"]["qty"], 3)
            u = p["could_not_match"]
            self.assertEqual((u[0]["label"], u[0]["isin"]), ("Unknown Co Ltd.", "INE777X01011"))
            self.assertIn("--map INE777X01011=SYMBOL", u[0]["reason"])      # never matched by name
        p = self.imp("groww.csv", "--map", "INE777X01011=ZZNOPE")
        self.assertIn("ZZNOPE", self.by(p))                                # your own map, only when given

    def test_wrong_broker_and_unknown_headers_refused(self):
        write_csv(self.f("groww.csv"), GROWW)
        self.assertIn("looks like a groww export", self.imp("groww.csv", "--broker", "zerodha", ok=False).stderr)
        write_csv(self.f("odd.csv"), [["Stock", "Units", "Price"], ["ALFA", "3", "100"]])
        r = self.imp("odd.csv", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not find the columns", r.stderr)
        self.assertIn("Headers found: Stock | Units | Price", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "positions.json")))

    def test_yes_writes_backs_up_reimport_no_duplicates_journal_untouched(self):
        journal = position("CHRL", qty=1)
        self.write("positions.json", {"positions": [journal]})
        write_csv(self.f("kite.csv"), KITE)
        p = self.imp("kite.csv", "--yes")
        self.assertTrue(p["written"])
        self.assertTrue(p["backup"].startswith("positions.backup-"))
        self.assertEqual(json.load(open(os.path.join(self.dir, p["backup"]))), {"positions": [journal]})
        pos = self.read("positions.json")["positions"]
        hold = {x["symbol"]: x for x in pos if x.get("kind") == "holding"}
        self.assertEqual(sorted(hold), ["ALFA", "CHRL"])
        a = hold["ALFA"]
        self.assertEqual((a["qty"], a["avg_price"], a["status"], a["id"]), (12, 100.5, "open", "HOLD-ALFA"))
        self.assertEqual(a["source"], "import:zerodha:2026-10-30")
        self.assertEqual(a["halal_at_buy"]["status"], "unknown (imported)")
        for k in ("stop", "target", "entry", "initial_stop"):
            self.assertNotIn(k, a)                                            # not a trade
        self.assertEqual((hold["CHRL"]["qty"], hold["CHRL"]["journal_qty"]), (3, 1))   # 4 in the export, 1 is the trade
        self.assertEqual([x for x in pos if x["id"] == journal["id"]], [journal])
        # re-import: same file, nothing duplicated; then one holding gone from the export
        p2 = self.imp("kite.csv", "--yes")
        self.assertEqual(p2["counts"], {"add": 0, "update": 0, "leave": 2, "not_in_latest_import": 0, "could_not_match": 0})
        self.assertEqual(len([x for x in self.read("positions.json")["positions"] if x.get("kind") == "holding"]), 2)
        write_csv(self.f("kite.csv"), [KITE[0], ["ALFA", "20", "101", "", "", "", "", ""]])
        p3 = self.imp("kite.csv", "--yes")
        self.assertEqual(self.by(p3)["ALFA"]["action"], "update")
        pos = self.read("positions.json")["positions"]
        hold = {x["symbol"]: x for x in pos if x.get("kind") == "holding"}
        self.assertEqual((hold["ALFA"]["qty"], hold["CHRL"]["status"]), (20, "not_in_latest_import"))   # kept, marked
        self.assertEqual([x for x in pos if x["id"] == journal["id"]], [journal])
        self.assertEqual(len(pos), 3)

    def test_unmatched_kept_and_never_compliant(self):
        write_xlsx(self.f("h.xlsx"), CONSOLE)
        self.imp("h.xlsx", "--yes")
        pos = self.read("positions.json")
        self.assertEqual(sorted(u["label"] for u in pos["unmatched_holdings"]["rows"]), ["SMEXYZ-SM", "ZZNOPE"])
        self.assertNotIn("ZZNOPE", {x["symbol"] for x in pos["positions"]})
        tk = DASH.api_tickets({})
        self.assertEqual(sorted(u["label"] for u in tk["unmatched_holdings"]), ["SMEXYZ-SM", "ZZNOPE"])
        self.assertNotIn("compliant", json.dumps(tk["unmatched_holdings"]))

    def test_never_places_anything(self):
        src = open(os.path.join(ROOT, TICKET), encoding="utf-8").read()
        for word in ("kiteconnect", "place_order", "urlopen", "requests"):
            self.assertNotIn(word, src)
        self.assertNotIn("TICKET", A.run_request.__doc__.split("(tayyib-broker import")[0][-5:])


class HoldingsAreNotTrades(ImportCase):
    def setUp(self):
        super().setUp()
        write_xlsx(self.f("h.xlsx"), CONSOLE)
        self.write("positions.json", {"positions": [position("BRVO", qty=2)]})
        self.imp("h.xlsx", "--yes")

    def test_left_out_of_trade_stats_sizing_risk_and_alerts(self):
        pos = self.read("positions.json")["positions"]
        self.assertEqual([p["symbol"] for p in tc.trade_positions(pos)], ["BRVO"])
        out = self.run_script(TICKET, "positions", as_json=False)
        self.assertIn("Holdings (imported, not trades", out)
        self.assertNotIn("ALFA", out.split("Holdings (imported")[0])
        tk = DASH.api_tickets({})
        self.assertEqual([p["symbol"] for p in tk["open"]], ["BRVO"])
        self.assertEqual(sorted(h["symbol"] for h in tk["holdings"]), ["ALFA", "ECHO"])
        al = self.run_script("tayyib-alerts/alerts.py", "add", "--from-positions")
        self.assertEqual({a["symbol"] for a in (al if isinstance(al, list) else al["added"]) if a}, {"BRVO"})
        sys.path.insert(0, os.path.join(ROOT, "tayyib-budget"))
        import size
        self.assertEqual(size.open_value(tc.trade_positions(pos)), 200.0)
        for f in ("tayyib-budget/size.py", "tayyib-risk/check.py"):
            self.assertIn("tc.trade_positions(", open(os.path.join(ROOT, f), encoding="utf-8").read())
        bsrc = open(os.path.join(ROOT, "tayyib-backtest", "backtest.py"), encoding="utf-8").read()
        trsrc = open(os.path.join(ROOT, "tayyib-tracker", "tracker.py"), encoding="utf-8").read()
        self.assertNotIn('read_json("positions.json"', bsrc + trsrc)    # neither reads your positions at all

    def test_included_in_held_alerts_already_held_and_purify(self):
        out = self.run_script("tayyib-halal/halal.py", "held", "--write")
        lv = {x["symbol"]: (x["level"], x["title"]) for x in out["held"]}
        self.assertEqual(lv["ECHO"], ("BLOCK", "Not compliant now (status at purchase unknown)"))
        self.assertIn("ALFA", lv)
        echo = [x for x in out["alerts"] if x["symbol"] == "ECHO"][0]
        self.assertEqual(echo["sell_ticket"]["qty"], 5)
        self.assertIn("ticket.py close HOLD-ECHO", echo["sell_ticket"]["steps"][-1])
        self.assertEqual(echo["wording"], tc.HELD_WORDING_UNKNOWN_BUY)
        daily = self.run_script("tayyib-daily/daily.py", "--no-news", "--runs", "200")
        self.assertNotIn("ALFA", [r["symbol"] for r in daily["rows"]])           # skip stocks I already hold
        self.assertTrue(any("ALFA" in n and "already held" in n for n in daily["notes"]), daily["notes"])
        pe = self.run_script("tayyib-purify/purify.py", "estimate", "ECHO", "--since", "2026-10-30")
        self.assertEqual(pe["qty"], 5)
        # selling a holding: no R, never in the trade totals; the alert is resolved
        self.run_script(TICKET, "close", "HOLD-ECHO", "--price", "170", "--reason", "halal")
        closed = [p for p in self.read("positions.json")["positions"] if p["id"] == "HOLD-ECHO"][0]
        self.assertEqual((closed["status"], closed["r"], closed["pnl_rs"] is not None), ("closed", None, True))
        self.assertEqual(DASH.api_tickets({})["totals"]["closed"], 0)
        z = [a for a in self.read("alerts.json")["alerts"] if a["kind"] == "halal" and a["symbol"] == "ECHO"][0]
        self.assertEqual(z["status"], "resolved")


# --- B5. the dashboard's Import holdings section -----------------------------------------------------------

class ImportAction(ServerCase):
    def setUp(self):
        super().setUp()
        self.build_universe()
        os.makedirs(os.path.join(self.dir, "import"))
        write_csv(os.path.join(self.dir, "import", "kite.csv"), KITE)

    def wait(self, timeout=60):
        t = time.time()
        while time.time() - t < timeout:
            s = self.get("/api/run/status")
            if s["state"] != "running":
                return s
            time.sleep(0.1)
        self.fail("run did not finish")

    def post(self, body):
        return self.req("/api/run", "POST", body, self.good())

    def test_only_files_inside_import_and_preview_first(self):
        listing = self.get("/api/import")
        self.assertEqual([f["name"] for f in listing["files"]], ["kite.csv"])
        self.assertFalse(listing["files"][0]["previewed"])
        self.assertIn("may change", listing["note"])
        with open(os.path.join(self.dir, "secret.csv"), "w") as f:
            f.write("Instrument,Qty.\nALFA,1\n")
        for bad in ("../secret.csv", "..\\secret.csv", "/etc/passwd", "C:\\x.csv", "sub/kite.csv", "kite.txt", "",
                    None, 5, "secret.csv"):
            r, out = self.post({"import": {"file": bad}})
            self.assertIn(r.status, (400, 404), bad)
        r, out = self.post({"import": {"file": "kite.csv", "apply": True, "path": "/x"}})
        self.assertEqual(r.status, 400)
        r, out = self.post({"import": {"file": "kite.csv", "apply": True}})            # no Preview yet
        self.assertEqual(r.status, 409)
        self.assertIn("Preview this file first", json.dumps(out))
        r, out = self.post({"import": {"file": "kite.csv"}})
        self.assertEqual(r.status, 200, out)
        s = self.wait()
        self.assertEqual(s["state"], "ok", s)
        self.assertEqual(s["command"], "tayyib-broker import trader/import/kite.csv")
        self.assertEqual(sorted(h["symbol"] for h in s["import_result"]["holdings"]), ["ALFA", "CHRL"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "positions.json")))
        self.assertTrue(self.get("/api/import")["files"][0]["previewed"])
        # the file changed after the Preview: Import refused again
        with open(os.path.join(self.dir, "import", "kite.csv"), "a") as f:
            f.write("THIN,1,10,,,,,\n")
        r, out = self.post({"import": {"file": "kite.csv", "apply": True}})
        self.assertEqual(r.status, 409)
        self.post({"import": {"file": "kite.csv"}})
        self.wait()
        r, out = self.post({"import": {"file": "kite.csv", "apply": True}})
        self.assertEqual(r.status, 200, out)
        s = self.wait()
        self.assertEqual((s["state"], s["import_result"]["written"]), ("ok", True))
        self.assertEqual(len([p for p in self.read("positions.json")["positions"] if p.get("kind") == "holding"]), 3)
        r, out = self.post({"import": {"file": "kite.csv", "apply": True}})            # each Import needs a Preview
        self.assertEqual(r.status, 409)
        page = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertIn('"Import holdings"', page)
        self.assertNotIn('type:"file"', page)                                        # no upload over HTTP
        self.assertNotIn("FormData", page)


# --- C. fixes --------------------------------------------------------------------------------------------

class Fixes(OfflineCase):
    def test_c1_wording(self):
        known = {"status": "compliant", "backfilled": False}
        self.assertEqual(tc.held_title("BLOCK", known), "No longer compliant")
        for at in ({"status": "compliant", "backfilled": True}, {"status": "unknown (imported)", "imported": True},
                   {"status": "review", "backfilled": True}, {}):
            self.assertEqual(tc.held_title("BLOCK", at), "Not compliant now (status at purchase unknown)")
        self.assertEqual(tc.held_title("WARN", {}), "Near a limit")
        self.assertEqual(tc.held_title("UNKNOWN", {}), "Could not verify")

    def test_c1_backfilled_position(self):
        self.build_universe()
        p = position("ECHO")
        del p["halal_at_buy"]
        self.write("positions.json", {"positions": [p]})
        x = self.run_script("tayyib-halal/halal.py", "held")["alerts"][0]
        self.assertEqual(x["title"], "Not compliant now (status at purchase unknown)")
        self.write("positions.json", {"positions": [position("ECHO")]})
        x = self.run_script("tayyib-halal/halal.py", "held")["alerts"][0]
        self.assertEqual((x["title"], x["wording"]), ("No longer compliant", tc.HELD_WORDING))

    def test_c3_ranges(self):
        st = {d: {"state": s} for d, s in (("2026-01-01", "risk-on"), ("2026-01-02", "risk-off"),
                                           ("2026-01-05", "risk-off"), ("2026-01-06", "risk-on"),
                                           ("2026-01-07", "risk-off"), ("2026-01-08", "UNKNOWN"))}
        self.assertEqual(bt.risk_off_ranges(st), [{"start": "2026-01-02", "end": "2026-01-05", "days": 2},
                                                  {"start": "2026-01-07", "end": "2026-01-07", "days": 1}])
        ix = {"name": "Nifty 50", "index": "^NSEI", "status": "OK",
              "risk_off_ranges": {"close_below_200dma": bt.risk_off_ranges(st)}}
        md = "\n".join(bt.ranges_md(ix))
        self.assertIn("### Risk-off date ranges: close_below_200dma (Nifty 50)", md)
        self.assertIn("| 2026-01-02 | 2026-01-05 | 2 |", md)
        v = DASH.bt_ranges(ix)
        self.assertEqual((v[0]["count"], v[0]["days"]), (2, 3))
        self.assertIn("Risk-off date ranges: ", open(os.path.join(ROOT, "tayyib-dashboard", "index.html"),
                                                    encoding="utf-8").read())

    def test_c3_in_a_backtest(self):
        self.build_universe()
        loader = lambda *a, **k: bt.load_bars(*a, sleep=0, **k)
        from test_v024 import bars_from
        p = {"mode": "all", "setups": None, "from": "2025-10-30", "to": "2026-10-30", "split": "2026-06-30",
             "max_positions": 5, "top": 10, "warmup_bars": 250, "tm_runs": 3000, "tm_seed": 7, "take_warn": True,
             "compare": False, "late": True, "end_rule": "--to 2026-10-30", "regime": "close_below_200dma:no_new_swing"}
        closes = [3000 - i * 2 if i < 900 else 1200 + (i - 900) * 9 for i in range(1100)]
        r = bt.run(p, tc.load_config(), tc.load_universe(), data_fn=loader, bench_fn=lambda *a, **k: ([], {}),
                   index_fn=lambda sym, range_="2y": (bars_from(closes, "2024-01-01"), {}))
        rg = r["regime"]["index"]["risk_off_ranges"]["close_below_200dma"]
        self.assertTrue(rg)
        self.assertEqual(sum(x["days"] for x in rg), r["regime"]["index"]["risk_off_days"]["close_below_200dma"])
        self.assertIn("### Risk-off date ranges", bt.render_md(r))
        self.assertTrue(DASH.bt_regime(r)["ranges"])


class Docs(unittest.TestCase):
    def test_version_and_docs(self):
        self.assertTrue(tc.VERSION >= "0.2.5")              # pinned exactly by the newest test file
        guide = open(os.path.join(ROOT, "docs", "USER_GUIDE.md"), encoding="utf-8").read()
        faq = open(os.path.join(ROOT, "docs", "FAQ.md"), encoding="utf-8").read()
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("Import your holdings (Zerodha / Groww)", guide)
        self.assertLess(guide.index("Start without Claude Code"), guide.index("## Part 2"))   # an option in Part 1
        self.assertIn("Windows, without Claude Code", readme)          # v0.2.7: the three quick starts
        for img in ("email-held-example.png", "today-regime-held.png", "tickets-held.png"):
            for doc in (guide, readme):
                for line in doc.splitlines():
                    if img in line:
                        self.assertIn("example data", line.lower(), img)
        ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        self.assertIn("## v0.2.5", ch)
        self.assertIn("46 trades", ch.split("## v0.2.4")[0])
        for f in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
            self.assertIn('"%s"' % tc.VERSION, open(os.path.join(ROOT, f), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
