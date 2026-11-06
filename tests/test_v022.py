"""v0.2.2: the Backtest tab (GET /api/backtests, /api/backtest, a "Run backtest" button through POST /api/run),
a window that ends on the last completed session, and the late-joiner sensitivity (--no-late, compare column c,
the P&L share). Offline, on fixtures."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest

from _util import FIX, ROOT, OfflineCase, tc
from test_v018 import ServerCase, D, A, script

sys.path.insert(0, os.path.join(ROOT, "tayyib-backtest"))
import backtest as bt  # noqa: E402

BT = "tayyib-backtest/backtest.py"
PAGE = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()


def when(x):
    return tc.dt.datetime.strptime(x, "%Y-%m-%d %H:%M").replace(tzinfo=tc.IST)


def fake_bench(sym, range_="2y"):
    """Benchmarks from fixture bars (offline): SHARIABEES from ALFA, the Nifty from CHRL."""
    bars, meta = tc.get_daily_bars("ALFA" if sym == bt.SHARIAH_BENCH else "CHRL", range_=range_)
    return bars, meta


def params(**kw):
    p = {"mode": "all", "setups": None, "from": "2025-10-30", "to": "2026-10-30", "split": "2026-06-30",
         "max_positions": 5, "top": 10, "warmup_bars": 250, "tm_runs": 3000, "tm_seed": 7, "take_warn": True,
         "compare": False, "late": True, "end_rule": "--to 2026-10-30"}
    p.update(kw)
    return p


def saved_run(case, **kw):
    """A backtest on the fixtures, saved to trader/backtest/ like --write -> result."""
    case.build_universe()
    loader = lambda *a, **k: bt.load_bars(*a, sleep=0, **k)
    res = bt.run(params(**kw), tc.load_config(), tc.load_universe(), data_fn=loader, bench_fn=fake_bench)
    bt.save(res)
    return res


# --- A1. the window ends on the last completed session ---------------------------------------------------

class WindowEnd(OfflineCase):
    def test_fixed_clock(self):
        cfg = tc.load_config()
        cases = (("2026-10-30 11:05", "2026-10-29"),     # Friday, market open: Thursday's bar is the last full one
                 ("2026-10-30 15:29", "2026-10-29"),
                 ("2026-10-30 15:30", "2026-10-30"),     # the close: today
                 ("2026-10-30 18:00", "2026-10-30"),
                 ("2026-10-31 10:00", "2026-10-30"),     # Saturday: Friday
                 ("2026-11-02 09:00", "2026-10-30"))     # Monday before the open: Friday
        for now, end in cases:
            self.assertEqual(bt.default_end(when(now), cfg)[0], end, now)
        self.assertIn("previous trading day", bt.default_end(when("2026-10-30 11:05"), cfg)[1])
        self.assertIn("after 15:30 IST", bt.default_end(when("2026-10-30 18:00"), cfg)[1])
        cfg["holidays"] = ["2026-10-29"]
        self.assertEqual(bt.default_end(when("2026-10-30 11:05"), cfg)[0], "2026-10-28")
        cfg["holidays"] = ["2026-10-30"]
        self.assertEqual(bt.default_end(when("2026-10-30 18:00"), cfg)[0], "2026-10-29")

    def test_window_and_params(self):
        a = argparse.Namespace(to=None, from_=None, years=1, split=None)
        start, end, split, rule = bt.window(a, when("2026-10-30 11:05"), tc.load_config())
        self.assertEqual((start, end), ("2025-10-29", "2026-10-29"))
        self.assertIn("previous trading day", rule)
        self.assertTrue(start < split <= end)
        a.to = "2026-06-30"
        _, end, _, rule = bt.window(a, when("2026-10-30 11:05"), tc.load_config())
        self.assertEqual((end, rule), ("2026-06-30", "--to 2026-06-30"))

    def test_cli_in_market_hours_stops_at_yesterday(self):
        self.build_universe()
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=FIX, TAYYIB_NOW="2026-10-30 11:05")
        out = subprocess.run([sys.executable, os.path.join(ROOT, BT), "run", "--years", "1", "--json"], env=env,
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout)
        self.assertEqual((r["params"]["to"], r["window"]["last_day"]), ("2026-10-29", "2026-10-29"))
        self.assertIn("previous trading day", r["params"]["end_rule"])
        r = self.run_script(BT, "run", "--years", "1")                      # 18:00: today
        self.assertEqual((r["params"]["to"], r["window"]["last_day"]), ("2026-10-30", "2026-10-30"))
        self.assertIn("after 15:30 IST", r["window"]["end_rule"])


# --- A2. late joiners ---------------------------------------------------------------------------------------

class LateJoiners(OfflineCase):
    def test_share_line_no_late_and_compare_c(self):
        res = saved_run(self, compare=True)
        late = {x["symbol"] for x in res["joined_late"]}
        self.assertEqual(late, {"CHRL"})
        lj = res["late_joiners"]
        lp = round(sum(t["pnl_rs"] for t in res["trades"] if t["symbol"] in late), 2)
        tot = round(sum(t["pnl_rs"] for t in res["trades"]), 2)
        self.assertEqual((lj["stocks"], lj["pnl_rs"], lj["total_pnl_rs"]), (1, lp, tot))
        self.assertEqual(lj["pct_of_total"], round(lp / tot * 100, 1))
        self.assertTrue(lj["text"].startswith("Late joiners: 1 stock, contributing %.1f%% of total P&L" % lj["pct_of_total"]))
        md = bt.render_md(res)
        self.assertIn(lj["text"], md)
        c = res["compare"]["no_late"]
        self.assertIsNotNone(c)
        self.assertIn("| | (a) as run | (b) score only | (c) as run without late joiners |", md)
        no = bt.run(params(late=False), tc.load_config(), tc.load_universe(),
                    data_fn=lambda *a, **k: bt.load_bars(*a, sleep=0, **k), bench_fn=fake_bench)
        self.assertFalse([t for t in no["trades"] if t["symbol"] in late])
        self.assertTrue(no["universe"]["late_excluded"])
        self.assertTrue(no["late_joiners"]["excluded"])
        self.assertEqual(no["late_joiners"]["pct_of_total"], 0.0)
        self.assertIn("left out with --no-late", no["late_joiners"]["text"])
        self.assertEqual(c["trades"], no["metrics"]["overall"]["trades"])        # (c) is exactly a --no-late run
        self.assertEqual(c["pnl_rs"], no["metrics"]["overall"]["pnl_rs"])

    def test_compare_c_needs_no_download(self):
        self.build_universe()
        calls = []

        def data_fn(*a, **k):
            calls.append(1)
            return bt.load_bars(*a, sleep=0, **k)

        bt.run(params(compare=True), tc.load_config(), tc.load_universe(), data_fn=data_fn, bench_fn=fake_bench)
        self.assertEqual(len(calls), 1)

    def test_share_when_total_is_not_positive(self):
        t = lambda s, p: {"symbol": s, "pnl_rs": p}
        x = bt.late_share([t("A", 100.0), t("B", -300.0)], [{"symbol": "A"}])
        self.assertIsNone(x["pct_of_total"])
        self.assertIn("UNKNOWN%", x["text"])

    def test_cli_no_late(self):
        self.build_universe()
        r = self.run_script(BT, "run", "--years", "1", "--no-late")
        self.assertFalse(r["params"]["late"])
        self.assertNotIn("CHRL", {t["symbol"] for t in r["trades"]})
        self.assertIn("Late joiners:", r["late_joiners"]["text"])


# --- B. the API ---------------------------------------------------------------------------------------------

class BacktestApi(ServerCase):
    def test_missing_folder(self):
        self.assertEqual(self.get("/api/backtests"), {"missing": "backtest", "hint": "run a backtest"})
        self.assertEqual(self.get("/api/backtest?id=2026-10-30_all_2025-10-30_abcdef"),
                         {"missing": "backtest", "hint": "run a backtest"})

    def test_shapes(self):
        res = saved_run(self, compare=True)
        lst = self.get("/api/backtests")
        self.assertEqual(lst["count"], 1)
        row = lst["runs"][0]
        for k in ("id", "run_at", "window_text", "mode", "settings", "trades", "cagr", "max_dd", "label"):
            self.assertIn(k, row)
        self.assertEqual((row["id"], row["mode"], row["settings"], row["trades"]),
                         (res["id"], "all", "default@2", res["metrics"]["overall"]["trades"]))
        d = self.get("/api/backtest?id=" + res["id"])
        self.assertEqual(d["order"], ["header", "banners", "cards", "equity", "breakdown", "compare", "trades",
                                      "universe", "footer"])
        self.assertEqual(d["banners"], res["banners"])
        self.assertIn(bt.BANNER_NEWS, d["banners"])
        self.assertLess(d["order"].index("banners"), d["order"].index("cards"))
        self.assertLess(d["order"].index("banners"), d["order"].index("equity"))
        h = {x["label"]: x["value"] for x in d["header"]["items"]}
        self.assertEqual((h["Capital"], h["Max positions"], h["Settings"], h["WARN plans"], h["Risk per trade"]),
                         ("₹1,00,000", "5", "default@2", "taken", "1%"))
        self.assertEqual([c["key"] for c in d["cards"]], ["strategy", "SHARIABEES.NS", "^NSEI"])
        self.assertEqual([i["label"] for i in d["cards"][0]["items"]],
                         ["CAGR", "Max drawdown", "Expectancy", "Trades", "Win rate"])
        nifty = d["cards"][2]
        self.assertEqual(nifty["label"], "not halal-screened, reference only")
        self.assertTrue(nifty["reference_only"])
        self.assertFalse(d["cards"][1]["reference_only"])
        eq = d["equity"]
        self.assertEqual(eq["status"], "ok")
        self.assertEqual([s["key"] for s in eq["series"]], ["strategy", "SHARIABEES.NS", "^NSEI"])
        self.assertEqual(eq["capital_label"], "₹1,00,000")
        self.assertEqual([m["kind"] for m in eq["dd"]["marks"]], ["peak", "trough"])
        o = res["metrics"]["overall"]
        self.assertIn(o["drawdown_trough"], eq["dd"]["marks"][1]["label"])
        for s in eq["series"]:                                           # every line starts at the capital
            first = s["points"].split()[0].split(",")
            self.assertAlmostEqual(float(first[1]), eq["capital_y"], delta=0.11)
        self.assertEqual(len(d["trades"]), len(res["trades"]))
        t = d["trades"][0]
        self.assertRegex(t["display"]["r"], r"^[+−]\d+\.\d\dR$|^0\.00R$")
        self.assertEqual(sorted(d["filters"]), ["exit_reason", "mode", "setup"])
        self.assertEqual(d["universe"]["late_line"], res["late_joiners"]["text"].replace("Rs ", "₹"))
        self.assertEqual([x["symbol"] for x in d["universe"]["joined_late"]], ["CHRL"])
        self.assertEqual(d["footer"], "Past results do not predict future results. Not financial advice, not a fatwa.")
        cp = d["compare"]
        self.assertEqual(cp["columns"], ["(a) as run", "(b) score only", "(c) as run without late joiners"])
        self.assertTrue(all(len(r["cells"]) == 3 for r in cp["rows"]))
        ch = self.get("/api/chart?bt=%s&n=0" % res["id"])
        self.assertEqual(ch["status"], "ok")
        self.assertEqual(ch["symbol"], res["trades"][0]["symbol"])
        self.assertTrue(ch["svg"]["markers"])
        self.assertEqual(self.get("/api/chart?bt=%s&n=999" % res["id"]), {"error": "no such trade in this backtest"})

    def test_too_few_flagged(self):
        res = saved_run(self)
        d = self.get("/api/backtest?id=" + res["id"])
        rows = {(s["title"], r["name"]): r for s in d["breakdown"]["sections"] for r in s["rows"]}
        few = [r for r in rows.values() if r["too_few"]]
        self.assertTrue(few)                                             # 10 trades: every group is noise
        for r in few:
            self.assertEqual(r["note"], "(too few to judge)")
        self.assertFalse(rows[("Overall", "strategy")]["too_few"])
        self.assertTrue(any(r["too_few"] for (t, _), r in rows.items() if t.startswith("In-sample")))

    def test_ids_are_whitelisted(self):
        saved_run(self)
        with open(os.path.join(tc.data_dir(), "backtest", "notes.json"), "w") as f:
            f.write("{}")
        self.assertEqual(self.get("/api/backtests")["count"], 1)                 # only names a backtest writes
        for bad in ("notes", "../config", "..%2Fconfig", "2026-10-30_all_2025-10-30_zzzzzz", ""):
            self.assertEqual(self.get("/api/backtest?id=" + bad), {"error": "no saved backtest with that id"}, bad)

    def test_host_check_and_methods(self):
        saved_run(self)
        r, out = self.req("/api/backtests", host="evil.example:%d" % self.port)
        self.assertEqual(r.status, 403)
        r, out = self.req("/api/backtest?id=x", host="evil.example")
        self.assertEqual(r.status, 403)
        for path in ("/api/backtests", "/api/backtest", "/api/chart"):
            for m in ("POST", "PUT", "DELETE", "PATCH"):
                h = self.good() if m == "POST" else None
                r, _ = self.req(path, m, {}, h)
                self.assertEqual(r.status, 405, (m, path))
        self.assertEqual(D.POST_ROUTES, ("/api/config", "/api/run"))


# --- B. the page --------------------------------------------------------------------------------------------

class Page(unittest.TestCase):
    def test_tab_and_order(self):
        self.assertIn('id="tab-backtest"', PAGE)
        self.assertIn('id="p-backtest"', PAGE)
        body = PAGE[PAGE.index("function renderBacktest("):PAGE.index("// --- tabs, header")]
        self.assertIn("d.order.forEach", body)                         # the sections come in the server's order
        self.assertEqual(body.count("add(panel, parts[k]())"), 1)       # and nothing is drawn outside it
        self.assertLess(body.index("banners:function"), body.index("cards:function"))
        self.assertIn('"Run backtest"', PAGE)
        self.assertIn("{ backtest:{ years:opt.years, mode:opt.mode, compare:cb.checked } }", PAGE)
        self.assertNotRegex(PAGE, r"(src|href)=\"https?://")


# --- B. the Run backtest button -----------------------------------------------------------------------------

class RunBacktest(ServerCase):
    def wait(self, timeout=60):
        t = time.time()
        while time.time() - t < timeout:
            s = self.get("/api/run/status")
            if s["state"] != "running":
                return s
            time.sleep(0.1)
        self.fail("run did not finish")

    def fake(self, body):
        self.srv.runner.backtest_script = script(self.scripts, "fake_bt.py", body)

    def test_whitelisted_args_only(self):
        self.fake('''
            import os, sys
            print("args", sys.argv[1:])
            sys.stderr.write("  day 1/10 2026-01-01\\n")
            d = os.path.join(os.environ["TAYYIB_DIR"], "backtest"); os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "2026-10-30_swing_2021-10-30_abcdef.json"), "w").write("{}")
        ''')
        r, s = self.post("/api/run", {"backtest": {"years": 5, "mode": "swing", "compare": True}})
        self.assertEqual(r.status, 200, s)
        self.assertEqual(s["kind"], "backtest")
        s = self.wait()
        self.assertEqual(s["state"], "ok", s)
        self.assertEqual(s["lines"][0], "args ['run', '--years', '5', '--mode', 'swing', '--compare', '--write']")
        self.assertEqual(s["backtest_id"], "2026-10-30_swing_2021-10-30_abcdef")
        self.assertEqual(s["command"], "tayyib-backtest run --years 5 --mode swing --compare --write")
        self.assertEqual(s["progress"], "day 1/10 2026-01-01")
        self.post("/api/run", {"backtest": {}})                         # defaults: 3 years, all, no compare
        s = self.wait()
        self.assertEqual(s["lines"][0], "args ['run', '--years', '3', '--mode', 'all', '--write']")
        self.assertEqual(A.backtest_argv({"years": 3, "mode": "all", "compare": False}),
                         ["run", "--years", "3", "--mode", "all", "--write"])
        for bad in ({"backtest": {"years": 4}}, {"backtest": {"years": "3"}}, {"backtest": {"years": True}},
                    {"backtest": {"years": 10}}, {"backtest": {"mode": "intraday"}}, {"backtest": {"mode": None}},
                    {"backtest": {"compare": "yes"}}, {"backtest": {"to": "2020-01-01"}},
                    {"backtest": {"years": 3, "capital": 1e9}}, {"backtest": {"args": ["--write"]}},
                    {"backtest": {}, "skip_news": True}, {"backtest": [3]}, {"backtest": "run --years 3"},
                    {"script": "tayyib-backtest/backtest.py"}):
            r, out = self.post("/api/run", bad)
            self.assertEqual(r.status, 400, bad)
        self.assertEqual(self.srv.runner.status()["state"], "ok")         # nothing new started

    def test_one_run_at_a_time(self):
        self.fake("import time; time.sleep(3)\n")
        r, _ = self.post("/api/run", {"backtest": {"years": 3}})
        self.assertEqual(r.status, 200)
        for body in ({"backtest": {"years": 3}}, {"skip_news": False}):
            r, out = self.post("/api/run", body)
            self.assertEqual(r.status, 409, body)
            self.assertIn("a run is already going (a backtest", out["error"])
        s = self.wait()
        self.assertEqual(s["state"], "failed")
        self.assertIn("saved no backtest", s["error"])

    def test_needs_the_token_like_every_post(self):
        r, _ = self.post("/api/run", {"backtest": {"years": 3}}, **{"X-Tayyib-Token": "x" * 43})
        self.assertEqual(r.status, 403)
        r, _ = self.post("/api/run", {"backtest": {"years": 3}}, Origin="http://evil.example")
        self.assertEqual(r.status, 403)
        r, _ = self.req("/api/run", "POST", {"backtest": {"years": 3}}, self.good(), host="evil.example")
        self.assertEqual(r.status, 403)
        self.assertEqual(self.srv.runner.status()["state"], "idle")

    def test_real_run_touches_nothing_else(self):
        self.build_universe()
        os.makedirs(os.path.join(tc.data_dir(), "daily"), exist_ok=True)
        for name, obj in (("config.json", {"capital": 100000}), ("tracker.json", {"rows": []}),
                          ("orders.json", {"orders": []}), ("positions.json", {"positions": []}),
                          (os.path.join("daily", "2026-10-30.json"), {"date": "2026-10-30", "rows": []})):
            self.write(name, obj)

        def snap():
            out = {}
            for root, dirs, files in os.walk(tc.data_dir()):
                rel = os.path.relpath(root, tc.data_dir())
                if rel.split(os.sep)[0] in ("backtest", "cache"):
                    continue
                for f in files:
                    p = os.path.join(root, f)
                    out[os.path.relpath(p, tc.data_dir())] = hashlib.sha1(open(p, "rb").read()).hexdigest()
            return out

        before = snap()
        r, s = self.post("/api/run", {"backtest": {"years": 3, "mode": "all", "compare": False}})
        self.assertEqual(r.status, 200, s)
        s = self.wait(timeout=600)
        self.assertEqual(s["state"], "ok", s["lines"][-20:])
        self.assertEqual(snap(), before)
        lst = self.get("/api/backtests")
        self.assertEqual([x["id"] for x in lst["runs"]], [s["backtest_id"]])
        d = self.get("/api/backtest?id=" + s["backtest_id"])
        self.assertIn(bt.BANNER_HALAL, d["banners"])


class Version(unittest.TestCase):
    def test_version_and_defaults(self):
        self.assertEqual(tc.DEFAULTS_VERSION, 2)          # the version itself is pinned by the newest test file


if __name__ == "__main__":
    unittest.main()
