"""v0.1.11: the tracker counts a stock once while it is waiting or held. A later listing of the same stock:
an earlier WAITING row -> REPLACED, an earlier OPEN row -> the new row is ALREADY_HELD. Neither is followed or
counted. Also: the Excel Settings column shows the label, and empty results are blank, not 0."""
import importlib.util
import os
import unittest
import zipfile

from _util import OfflineCase, ROOT, tc


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TR = _load("tayyib_tracker_v111", os.path.join(ROOT, "tayyib-tracker", "tracker.py"))
D = _load("tayyib_dashboard_v111", os.path.join(ROOT, "tayyib-dashboard", "dashboard.py"))


def row(date, sym, status="WAITING", setup="trend", h="aaaa1111", **kw):
    r = {"date": date, "symbol": sym, "name": sym, "mode": "delivery", "setup": setup, "check": "PASS",
         "entry": 100.0, "stop": 90.0, "target": 130.0, "qty": 10, "risk_rs": 100.0, "valid_until": "2026-11-12",
         "max_hold_days": 250, "expectancy_r": None, "status": status, "settings_hash": h}
    r.update(kw)
    return r


def store_of(*rows):
    return {"rows": list(rows), "settings": {"aaaa1111": {"label": "default@2", "first_seen": "2026-11-04",
                                                          "differs_from_default": []}}}


class Rule(unittest.TestCase):
    def test_waiting_becomes_replaced(self):
        old, new = row("2026-11-04", "WELSPUNLIV"), row("2026-11-05", "WELSPUNLIV", setup="breakout")
        n = TR.overlap(store_of(old, new))
        self.assertEqual((old["status"], old["replaced_by"]), ("REPLACED", "2026-11-05"))
        self.assertEqual(new["status"], "WAITING")                       # the newer row is the one followed
        self.assertEqual(n, {"replaced": 1, "already_held": 0, "restored": 0})

    def test_open_makes_the_new_row_already_held(self):
        old = row("2026-11-04", "COFORGE", "OPEN", filled="2026-11-05", fill=100.5)
        new = row("2026-11-05", "COFORGE")
        TR.overlap(store_of(old, new))
        self.assertEqual((new["status"], new["held_from"]), ("ALREADY_HELD", "2026-11-04"))
        self.assertEqual(old["status"], "OPEN")                          # the held row keeps counting

    def test_closed_earlier_row_leaves_a_normal_row(self):
        for st, kw in (("TARGET", {"filled": "2026-11-02", "exited": "2026-11-04", "r": 2.9}),
                       ("STOP", {"filled": "2026-11-02", "exited": "2026-11-05", "r": -1.0}),
                       ("TIME EXIT", {"filled": "2026-10-01", "exited": "2026-11-03", "r": 0.4}),
                       ("NOT TRIGGERED", {"valid_until": "2026-11-04"}),
                       ("SUPERSEDED", {}), ("REPLACED", {"replaced_by": "2026-11-04"})):
            old = row("2026-11-03", "ALFA", st, **kw)
            new = row("2026-11-05", "ALFA")
            TR.overlap(store_of(old, new, row("2026-11-04", "ALFA", "SUPERSEDED")))
            self.assertEqual((old["status"], new["status"]), (st, "WAITING"), st)
            self.assertEqual(len(TR.counted([old, new])), 1 if st in TR.NOT_COUNTED else 2, st)

    def test_held_or_waiting_is_judged_on_the_new_lists_date(self):
        # filled after the newer list was made: it was still waiting then -> REPLACED
        old = row("2026-11-03", "BETA", "OPEN", filled="2026-11-06")
        new = row("2026-11-05", "BETA")
        TR.overlap(store_of(old, new))
        self.assertEqual((old["status"], new["status"]), ("REPLACED", "WAITING"))

    def test_any_setup_and_list_date_order(self):
        a = row("2026-11-03", "GAMA", "OPEN", setup="breakout", filled="2026-11-03")
        b = row("2026-11-04", "GAMA", setup="pullback")
        c = row("2026-11-05", "GAMA", setup="trend")
        TR.overlap(store_of(c, b, a))                                    # stored out of order: still by date
        self.assertEqual([x["status"] for x in (a, b, c)], ["OPEN", "ALREADY_HELD", "ALREADY_HELD"])
        self.assertEqual((b["held_from"], c["held_from"]), ("2026-11-03", "2026-11-03"))

    def test_idempotent(self):
        st = store_of(row("2026-11-04", "W"), row("2026-11-05", "W"),
                      row("2026-11-04", "C", "OPEN", filled="2026-11-05"), row("2026-11-05", "C"))
        TR.overlap(st)
        snap = [dict(r) for r in st["rows"]]
        self.assertEqual(TR.overlap(st), {"replaced": 0, "already_held": 0, "restored": 0})
        self.assertEqual(st["rows"], snap)

    def test_replaced_comes_back_when_its_replacement_is_gone(self):
        old, new = row("2026-11-04", "W"), row("2026-11-05", "W", h="aaaa1111")
        st = store_of(old, new)
        TR.overlap(st)
        new["status"] = "SUPERSEDED"                                     # that list was re-made without W
        self.assertEqual(TR.overlap(st)["restored"], 1)
        self.assertEqual(old["status"], "WAITING")
        self.assertNotIn("replaced_by", old)

    def test_skipped_without_prices(self):
        old, new = row("2026-11-04", "W"), row("2026-11-05", "W")
        TR.overlap(store_of(old, new), skip={"W"})
        self.assertEqual((old["status"], new["status"]), ("WAITING", "WAITING"))


class Live(OfflineCase):
    """The user's data shape on 2026-11-05: ten 2026-11-04 rows (nine bought on 11-05, WELSPUNLIV waiting) and a
    2026-11-05 list made twice (default@1 rows SUPERSEDED, default@2 rows counted)."""

    def live_store(self):
        rows = [row("2026-11-04", s, "OPEN", h="pre-0.1.5", filled="2026-11-05", fill=100.0)
                for s in ("COFORGE", "CPPLUS", "EMCURE", "ETERNAL", "MANKIND", "PERSISTENT", "SANSERA", "SHYAMMETL",
                          "SONACOMS")]
        rows.append(row("2026-11-04", "WELSPUNLIV", h="pre-0.1.5"))
        new = ("AUROPHARMA", "COFORGE", "EMCURE", "ETERNAL", "LAURUSLABS", "MOTHERSON", "SAILIFE", "SHYAMMETL",
               "SONACOMS", "WELSPUNLIV")
        rows += [row("2026-11-05", s, "SUPERSEDED", h="6f0db736", superseded_by="default@2") for s in new]
        rows += [row("2026-11-05", s, h="a28d32c9") for s in new]
        return {"rows": rows, "settings": {"6f0db736": {"label": "default@1"}, "a28d32c9": {"label": "default@2"}}}

    def test_migration_on_the_users_data(self):
        st = self.live_store()
        self.assertEqual(len(TR.counted(st["rows"])), 20)
        TR.overlap(st)
        got = sorted((r["date"], r["symbol"], r["status"]) for r in st["rows"] if r["status"] in ("REPLACED", "ALREADY_HELD"))
        self.assertEqual(got, [("2026-11-04", "WELSPUNLIV", "REPLACED")] +
                         [("2026-11-05", s, "ALREADY_HELD") for s in ("COFORGE", "EMCURE", "ETERNAL", "SHYAMMETL", "SONACOMS")])
        self.assertEqual(len(TR.counted(st["rows"])), 14)
        TR.overlap(st)
        self.assertEqual(len(TR.counted(st["rows"])), 14)

    def test_migrate_command_and_summaries(self):
        st = self.live_store()
        tc.write_json("tracker.json", st)
        out = self.run_script("tayyib-tracker/tracker.py", "migrate")
        self.assertEqual((out["counted_before"], out["counted_after"], out["replaced"], out["already_held"]), (20, 14, 1, 5))
        again = self.run_script("tayyib-tracker/tracker.py", "migrate")
        self.assertEqual((again["counted_before"], again["counted_after"], again["replaced"], again["already_held"]),
                         (14, 14, 0, 0))
        saved = self.read("tracker.json")
        self.assertEqual(saved["summary"]["all"]["listed"], 14)               # tracker.json summary
        self.assertEqual(sum(v["stats"]["listed"] for v in saved["settings_split"].values()), 14)
        t = D.api_tracker({})                                                 # the dashboard Results
        self.assertEqual((t["summary"]["all"]["listed"], t["kpis"]["tracked"]), (14, "14"))
        self.assertEqual(sum(t["result_counts"].values()), 14)
        grey = [r for r in t["rows"] if r["not_counted"]]
        self.assertEqual(len(grey), 16)                                       # 10 superseded + 1 replaced + 5 held
        rep = [r for r in grey if r["status"] == "REPLACED"][0]
        self.assertEqual(rep["verdict"]["label"], "REPLACED by the 2026-11-05 list: not counted")
        self.assertIn("still waiting", rep["verdict"]["tip"])
        held = [r for r in grey if r["status"] == "ALREADY_HELD"][0]
        self.assertEqual(held["verdict"]["label"], "ALREADY HELD from the 2026-11-04 list: not counted")
        self.assertEqual(held["display"]["r"], "not counted")
        page = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertIn("r.verdict.tip || null", page)                          # the chip's tooltip
        TR.export(TR.load())                                                  # the Excel Summary: summary() too
        xml = zipfile.ZipFile(os.path.join(self.dir, "tracker.xlsx")).read("xl/worksheets/sheet2.xml").decode()
        self.assertIn("<is><t>all</t></is></c><c r=\"B2\"><v>14</v>", xml)

    def test_update_does_not_follow_the_new_statuses(self):
        st = self.live_store()
        TR.overlap(st)
        TR.update(st, tc.load_config())
        self.assertEqual(len([r for r in st["rows"] if r["status"] == "ALREADY_HELD"]), 5)
        self.assertEqual([r["status"] for r in st["rows"] if r["symbol"] == "WELSPUNLIV" and r["date"] == "2026-11-04"],
                         ["REPLACED"])


class SameDay(OfflineCase):
    def test_same_day_supersede_still_works(self):
        os.makedirs(os.path.join(self.dir, "daily"), exist_ok=True)

        def daily(h, label, syms):
            tc.write_json(os.path.join("daily", "2026-10-30.json"), {
                "date": "2026-10-30", "settings": {"hash": h, "label": label, "differs_from_default": []},
                "rows": [{"symbol": s, "name": s, "mode": "swing", "setup": "breakout", "risk": "PASS", "entry": 100.0,
                          "stop": 95.0, "target": 110.0, "qty": 10, "loss_at_stop_rs": 50, "valid_until": "2026-10-30",
                          "max_hold_days": 20} for s in syms]})
        st = TR.load()
        daily("aaaa1111", "default@2", ["A", "B"])
        TR.add_from_daily(st, "2026-10-30")
        daily("aaaa1111", "default@2", ["A", "B"])
        self.assertEqual(TR.add_from_daily(st, "2026-10-30")[0], 0)            # same settings: no duplicates
        daily("bbbb2222", "bbbb2222", ["A"])
        TR.add_from_daily(st, "2026-10-30")
        self.assertEqual(sorted((r["symbol"], r["settings_hash"], r["status"]) for r in st["rows"]),
                         [("A", "aaaa1111", "SUPERSEDED"), ("A", "bbbb2222", "WAITING"), ("B", "aaaa1111", "SUPERSEDED")])
        TR.overlap(st)                                                         # same date: never REPLACED
        self.assertEqual(sorted(r["status"] for r in st["rows"]), ["SUPERSEDED", "SUPERSEDED", "WAITING"])

    def test_an_already_held_row_is_superseded_by_a_same_day_rerun(self):
        st = store_of(row("2026-11-04", "C", "OPEN", filled="2026-11-05"), row("2026-11-05", "C"))
        TR.overlap(st)
        self.assertFalse(TR.filled(st["rows"][1]))                             # never bought: a re-run may supersede it
        TR.supersede(st, "2026-11-05", "bbbb2222", "bbbb2222")
        self.assertEqual(st["rows"][1]["status"], "SUPERSEDED")


class Excel(OfflineCase):
    def test_settings_label_and_blanks(self):
        st = {"rows": [row("2026-11-04", "A", h="a28d32c9"), row("2026-11-04", "B", h="6f0db736"),
                       row("2026-11-03", "C", h="pre-0.1.5"), row("2026-11-03", "D", h="1234abcd"),
                       row("2026-11-02", "E", h="cf8b2136")],
              "settings": {"a28d32c9": {"label": "default@2"}, "6f0db736": {"label": "default@1"},
                           "1234abcd": {"label": "1234abcd", "differs_from_default": []}}}
        s = TR.summary(st["rows"], st)["all"]
        self.assertEqual((s["closed"], s["win_rate_pct"], s["avg_r"], s["total_r"], s["pnl_rs"]), (0, None, None, None, None))
        TR.export(st)
        z = zipfile.ZipFile(os.path.join(self.dir, "tracker.xlsx"))
        rows_xml = z.read("xl/worksheets/sheet1.xml").decode()
        for lab in ("default@2", "default@1", "pre-0.1.5", "1234abcd"):
            self.assertIn("<t>%s</t>" % lab, rows_xml)
        self.assertNotIn("<t>a28d32c9</t>", rows_xml)
        self.assertNotIn("<t>cf8b2136</t>", rows_xml)                          # a legacy hash shows its label
        summ = z.read("xl/worksheets/sheet2.xml").decode()
        all_row = summ[summ.index('<row r="2">'):summ.index("</row>", summ.index('<row r="2">'))]
        for col in "LMNO":                                                     # win rate, avg R, total R, P&L
            self.assertNotIn('r="%s2"' % col, all_row)                          # blank, not a 0
        readme = z.read("xl/worksheets/sheet3.xml").decode()
        for word in ("REPLACED =", "ALREADY_HELD =", "blank, not 0"):
            self.assertIn(word, readme)
        # with a closed trade the numbers are there
        st["rows"][0].update(status="TARGET", filled="2026-11-05", exited="2026-11-06", r=2.9, pnl_rs=290.0)
        s = TR.summary(st["rows"], st)["all"]
        self.assertEqual((s["win_rate_pct"], s["avg_r"], s["pnl_rs"]), (100.0, 2.9, 290.0))


class Version(unittest.TestCase):
    def test_version_and_defaults(self):
        self.assertEqual(tc.VERSION, "0.1.11")
        self.assertEqual(tc.DEFAULTS_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
