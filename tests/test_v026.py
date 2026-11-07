"""v0.2.6: pullback back on by default (default@4: every value and decision equals default@2), its one-time notice
(which replaces v0.2.5's), and the robustness test in tayyib-backtest (--robust N, --robust-compare A B) with its
Backtest-tab view. Offline: fixtures and small synthetic data only."""
import copy
import glob
import json
import os
import subprocess
import sys
import unittest

from _util import FIX, NOW, ROOT, OfflineCase, tc
import baseline

for d in ("tayyib-backtest", "tayyib-dashboard"):
    sys.path.insert(0, os.path.join(ROOT, d))
import backtest as bt  # noqa: E402
import dashboard as DASH  # noqa: E402
import actions as A  # noqa: E402

BT = "tayyib-backtest/backtest.py"
CFG = tc.validate_config({})[0]
NOTE = ("On by default. On its own it lost money in 5-year backtests (−0.21R over 46 trades), but switching it off "
        "made the whole strategy worse (5-year CAGR 8.0% → 4.1%), because other trades took its place.")
BANNER = ("Pullback is back on by default (v0.2.6): removing it made the whole strategy worse in 3- and 5-year "
          "backtests. You can still switch it off in Settings.")
PARAMS = {"mode": "all", "setups": None, "from": "2025-10-30", "to": "2026-10-30", "split": "2026-06-30",
          "max_positions": 5, "top": 10, "warmup_bars": 250, "tm_runs": 3000, "tm_seed": 7, "take_warn": True,
          "compare": False, "late": True, "end_rule": "--to 2026-10-30"}


# --- A1. default@4 = default@2 -----------------------------------------------------------------------------

class DefaultsV4(unittest.TestCase):
    def test_version_label_and_values(self):
        self.assertGreaterEqual(tc.DEFAULTS_VERSION, 4)                         # v0.2.7: 5 (same decisions)
        snap = tc.settings_snapshot(CFG)
        self.assertEqual((snap["label"], snap["same_as"]), ("default@%d" % tc.DEFAULTS_VERSION, "default@2"))
        self.assertTrue(CFG["scanner"]["setups"]["pullback"]["enabled"])
        self.assertIn("pullback", tc.enabled_setups(CFG, tc.SWING_SETUPS))
        hist = baseline.load_defaults()
        self.assertIn("4", hist)                         # the current values: test_v027.DefaultsV5
        self.assertEqual({k: hist["4"][k] for k in hist["2"]}, hist["2"])          # every default@2 value, unchanged
        extra = sorted(set(hist["4"]) - set(hist["2"]))
        self.assertEqual(extra, ["regime.action", "regime.enabled", "regime.index", "regime.rule"])
        self.assertIs(hist["4"]["regime.enabled"], False)                         # added off (v0.2.4): no decision
        self.assertEqual({k: hist["3"][k] for k in extra}, {k: hist["4"][k] for k in extra})

    def test_default3_stays_a_known_historic_label(self):
        self.assertIn(3, tc.DEFAULTS_HISTORY)
        self.assertIn("historic", tc.DEFAULTS_HISTORY[3])
        off = tc.settings_snapshot(tc.validate_config(baseline.PULLBACK_OFF)[0])
        self.assertNotEqual(off["label"], "default@3")                           # no longer the default
        self.assertEqual(off["same_as"], "default@3")
        other = tc.settings_snapshot(tc.validate_config({"scanner": {"setups": {"squeeze": {"enabled": False}}}})[0])
        self.assertIsNone(other["same_as"])
        acct = tc.settings_snapshot(tc.validate_config({"capital": 250000})[0])
        self.assertEqual((acct["label"], acct["same_as"]), ("default@%d" % tc.DEFAULTS_VERSION, "default@2"))
        sys.path.insert(0, os.path.join(ROOT, "tayyib-tracker"))
        import tracker
        store = {"settings": {"a1": {"label": "default@3"}, "b2": {"label": "default@4"}}}
        self.assertEqual([tracker.settings_group(store, h) for h in ("a1", "b2")], ["default@3", "default@4"])

    def test_settings_note_and_ticked_checkbox(self):
        self.assertEqual(tc.DEFAULT_CONFIG_DOCS["scanner.setups.pullback.enabled"]["note"], NOTE)
        self.assertEqual(tc.PULLBACK_NOTE, NOTE)
        os.environ["TAYYIB_DIR"] = os.path.join(FIX, "no-such-folder")
        f = DASH.setting_field("scanner.setups.pullback.enabled", A._flat(CFG), {}, False)
        self.assertEqual((f["value"], f["default"]), (True, True))
        self.assertEqual(f["note"], NOTE)


class BaselineV4(unittest.TestCase):
    def test_default4_pipeline_is_the_default2_snapshot_exactly(self):
        d2 = baseline.load_default_snapshot(2)
        cur = baseline.pipeline(config=None)
        self.assertEqual(baseline.diff(d2["pipeline"], cur, new_keys=frozenset()), [])   # no change, no new key
        self.assertEqual(baseline.digest(cur), baseline.digest(d2["pipeline"]))
        self.assertFalse(os.path.exists(baseline.snapshot_path(4)))   # nothing new to keep: it IS default@2


# --- A2. migration and the banner swap -----------------------------------------------------------------------

class Migration(OfflineCase):
    def earlier(self):
        os.makedirs(os.path.join(self.dir, "daily"), exist_ok=True)
        self.write(os.path.join("daily", "2026-10-29.json"), {"date": "2026-10-29"})

    def raw(self, name="config.json"):
        with open(os.path.join(self.dir, name), "rb") as f:
            return f.read()

    def test_following_the_default_moves_to_default4_untouched(self):
        self.earlier()
        self.write("config.json", {"capital": 200000, "scanner": {"setups": {"squeeze": {"enabled": False}}}})
        before = self.raw()
        banner, rec = tc.pullback_migration()
        self.assertEqual(banner, BANNER)
        self.assertEqual(tc.PULLBACK_BANNER, BANNER)
        self.assertEqual(self.raw(), before)                                   # config.json never written
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config_backups")))
        self.assertTrue(tc.load_config()["scanner"]["setups"]["pullback"]["enabled"])
        self.assertIn("default@4", rec["result"])                     # the v0.2.6 migration note (historic)
        cfg = tc.validate_config({"capital": 200000})[0]
        self.assertEqual(tc.settings_snapshot(cfg)["label"], "default@%d" % tc.DEFAULTS_VERSION)

    def test_no_config_follows_the_default(self):
        self.earlier()
        self.assertEqual(tc.pullback_migration()[0], BANNER)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))

    def test_your_own_pullback_setting_is_left_alone(self):
        for val in (False, True):
            self.earlier()
            if os.path.exists(os.path.join(self.dir, "notices.json")):
                os.remove(os.path.join(self.dir, "notices.json"))
            self.write("config.json", {"scanner": {"setups": {"pullback": {"enabled": val, "rsi_min": 30}}}})
            before = self.raw()
            banner, rec = tc.pullback_migration()
            self.assertIsNone(banner, val)
            self.assertEqual(rec["result"], "you set pullback yourself: left alone")
            self.assertEqual(self.raw(), before)
            self.assertIs(tc.load_config()["scanner"]["setups"]["pullback"]["enabled"], val)

    def test_new_folder_says_nothing(self):
        banner, rec = tc.pullback_migration()
        self.assertIsNone(banner)
        self.assertEqual(rec["result"], "new folder: nothing to change")

    def test_unseen_v025_banner_is_replaced_by_the_new_one_only(self):
        self.earlier()
        self.write("notices.json", {tc.PULLBACK_NOTICE_V025: {"date": "2026-10-29", "banner": True, "shown": None,
                                                              "result": "follows the new default (pullback off)"}})
        banner, rec = tc.pullback_migration()
        self.assertEqual(banner, BANNER)
        self.assertTrue(rec["replaced_v025_banner"])
        n = self.read("notices.json")
        self.assertIn("superseded", n[tc.PULLBACK_NOTICE_V025])
        self.assertIsNone(n[tc.PULLBACK_NOTICE_V025]["shown"])

    def test_seen_v025_banner_then_the_new_one(self):
        self.earlier()
        self.write("notices.json", {tc.PULLBACK_NOTICE_V025: {"banner": True, "shown": "2026-10-29"}})
        banner, rec = tc.pullback_migration()
        self.assertEqual(banner, BANNER)
        self.assertFalse(rec["replaced_v025_banner"])

    def test_banner_once_on_the_daily_list_and_never_the_old_one(self):
        self.build_universe()
        self.earlier()
        self.write("notices.json", {tc.PULLBACK_NOTICE_V025: {"banner": True, "shown": None}})
        out = self.run_script("tayyib-daily/daily.py", "--no-news", "--runs", "200")
        self.assertIn(BANNER, out["banners"])
        self.assertNotIn(tc.PULLBACK_BANNER_V025, out["banners"])
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertIn("Pullback is back on by default (v0.2.6)", md)
        self.assertNotIn("Pullback is now off", md)
        self.assertEqual(out["settings"]["label"], "default@%d" % tc.DEFAULTS_VERSION)
        again = self.run_script("tayyib-daily/daily.py", "--no-news", "--runs", "200")
        self.assertNotIn(BANNER, again["banners"])
        self.assertEqual(self.read("notices.json")[tc.PULLBACK_NOTICE]["shown"], "2026-10-30")


# --- B1. --robust ----------------------------------------------------------------------------------------

def loader(*a, **k):
    return bt.load_bars(*a, sleep=0, **k)


class Counting:
    """A price source that counts every call (and fails like the offline benchmarks do)."""

    def __init__(self):
        self.calls = []

    def __call__(self, sym, range_="2y"):
        self.calls.append((sym, range_))
        raise tc.FetchError("offline: %s" % sym)


class Robust(OfflineCase):
    def setUp(self):
        super().setUp()
        self.build_universe()
        self.uni = tc.load_universe()
        self.cfg = tc.load_config()
        self.data, _, _ = loader(sorted(bt.halal_universe(self.uni)[0]), "2y", PARAMS["from"], PARAMS["to"])

    def side(self, n=4, cache=None, data=None, cfg=None):
        return bt.robust_side(data or self.data, cfg or self.cfg, PARAMS, self.uni, n, cache or bt.RunCache(),
                              lambda st: None)

    def test_same_seed_same_result(self):
        a, b = self.side(), self.side()
        self.assertEqual(a, b)
        self.assertEqual([r["seed"] for r in a["runs"]], [1, 2, 3, 4])
        self.assertEqual([r["max_positions"] for r in a["max_positions"]], [3, 5, 8])
        one = bt.simulate(self.data, self.cfg, a["runs"][1]["start"], PARAMS["to"], uni=self.uni, tie=bt.tie_key(2))
        self.assertEqual(bt.run_row("x", one, 100000.0, PARAMS["split"], None)["overall"], a["runs"][1]["overall"])

    def test_different_seeds_different_tie_orders_and_shifts(self):
        syms = ["S%02d" % k for k in range(30)]
        orders = {tuple(bt.tie_order(seed, syms)) for seed in range(1, 21)}
        self.assertEqual(len(orders), 20)
        self.assertEqual(bt.tie_order(None, syms), sorted(syms))
        self.assertEqual(bt.tie_order(7, syms), bt.tie_order(7, list(reversed(syms))))      # fixed per seed
        self.assertEqual({bt.seed_shift(s) for s in range(1, 21)}, {-1, 1})
        self.assertEqual([bt.seed_shift(s) for s in range(1, 9)], [bt.seed_shift(s) for s in range(1, 9)])
        dates = ["2026-01-0%d" % k for k in range(1, 8)]
        self.assertEqual(bt.shifted_start(dates, "2026-01-04", -1), "2026-01-03")
        self.assertEqual(bt.shifted_start(dates, "2026-01-04", 1), "2026-01-05")
        rows = self.side(n=6)["runs"]
        self.assertEqual(len({tuple(r["tie_first"]) for r in rows}), 6)
        for r in rows:
            self.assertEqual(r["start"], bt.shifted_start(sorted({b["date"] for bs in self.data.values() for b in bs}),
                                                          PARAMS["from"], r["shift_days"]))

    def test_the_seed_only_breaks_ties(self):
        def cand(sym, score):
            return {"symbol": sym, "setup": "breakout", "mode": "swing", "score": score, "sig": {}, "plan": {}, "i": 0}
        cands = [cand("AAA", 50), cand("BBB", 50), cand("CCC", 50), cand("DDD", 70), cand("EEE", 10)]
        plain = bt._choose_day([dict(c) for c in cands], CFG, "swing", set(), None)
        self.assertEqual([c["symbol"] for c in plain], ["DDD", "AAA", "BBB", "CCC", "EEE"])
        seen = set()
        for seed in range(1, 12):
            got = [c["symbol"] for c in bt._choose_day([dict(c) for c in cands], CFG, "swing", set(), bt.tie_key(seed))]
            self.assertEqual((got[0], got[-1]), ("DDD", "EEE"))                    # the score still decides
            self.assertEqual(got[1:4], bt.tie_order(seed, ["AAA", "BBB", "CCC"]))
            seen.add(tuple(got))
        self.assertGreater(len(seen), 2)

    def test_cache_changes_nothing(self):
        plain = bt.simulate(self.data, self.cfg, PARAMS["from"], PARAMS["to"], uni=self.uni)
        cached = bt.simulate(self.data, self.cfg, PARAMS["from"], PARAMS["to"], uni=self.uni, cache=bt.RunCache())
        self.assertEqual(plain, cached)
        c = bt.RunCache()
        for seed in (3, 3, 5):
            a = bt.simulate(self.data, self.cfg, PARAMS["from"], PARAMS["to"], uni=self.uni, tie=bt.tie_key(seed))
            b = bt.simulate(self.data, self.cfg, PARAMS["from"], PARAMS["to"], uni=self.uni, tie=bt.tie_key(seed), cache=c)
            self.assertEqual(a, b, seed)

    def test_no_look_ahead_with_a_seed_and_the_cache(self):
        # test_v020.NoLookAhead with the seeded tie order and the shared cache: every later bar changed, same plans
        from test_v020 import fixture_bars
        data = fixture_bars()
        books = {s: bt.Book(b) for s, b in data.items()}
        seen = 0
        for b in data["ALFA"][210::5]:
            t = b["date"]
            changed = {s: [dict(x, open=x["open"] * 1.4, high=x["high"] * 1.5, low=x["low"] * 1.3, close=x["close"] * 1.4,
                                volume=x["volume"] * 3) if x["date"] > t else x for x in bars] for s, bars in data.items()}
            books2 = {s: bt.Book(x) for s, x in changed.items()}
            for seed in (2, 9):
                tie = bt.tie_key(seed)
                a = bt.scan_day(books, t, CFG, "all", None, set(), tie=tie, cache=bt.RunCache())
                c = bt.scan_day(books2, t, CFG, "all", None, set(), tie=tie, cache=bt.RunCache())
                self.assertEqual(a, c, t)
                if a:
                    seen += 1
                    ra = bt.rank_day(books, copy.deepcopy(a), CFG, all_mc=True, tie=tie, cache=bt.RunCache())
                    rc = bt.rank_day(books2, copy.deepcopy(c), CFG, all_mc=True, tie=tie, cache=bt.RunCache())
                    self.assertEqual(ra, rc, t)
        self.assertGreater(seen, 3)

    def test_no_new_downloads(self):
        calls = []

        def data_fn(*a, **k):
            calls.append(a[1])
            return loader(*a, **k)
        bench = Counting()
        res = bt.run(dict(PARAMS, robust=5, robust_given=True), self.cfg, self.uni, data_fn=data_fn, bench_fn=bench)
        self.assertEqual(len(calls), 1)                                       # the bars, loaded once
        self.assertEqual(sorted(set(bench.calls)), sorted(bench.calls))       # each benchmark asked for once
        self.assertEqual(len(bench.calls), 2)
        self.assertEqual(res["robust"]["summary"]["runs"], 5)
        self.assertIsNone(res["robust"]["summary"]["beat_benchmark"]["runs"])        # ETF offline: UNKNOWN, never 0
        self.assertIn("UNKNOWN", res["robust"]["summary"]["beat_benchmark"]["text"])
        orig = tc.get_daily_bars
        try:
            tc.get_daily_bars = lambda *a, **k: self.fail("downloaded during the robust runs")
            bt.robust_side(self.data, self.cfg, PARAMS, self.uni, 3, bt.RunCache(), lambda st: None)
        finally:
            tc.get_daily_bars = orig

    def test_run_deterministic_and_plain_run_unchanged(self):
        plain = bt.run(dict(PARAMS), self.cfg, self.uni, data_fn=loader, bench_fn=Counting())
        r1 = bt.run(dict(PARAMS, robust=3, robust_given=True), self.cfg, self.uni, data_fn=loader, bench_fn=Counting())
        r2 = bt.run(dict(PARAMS, robust=3, robust_given=True), self.cfg, self.uni, data_fn=loader, bench_fn=Counting())
        self.assertEqual(r1, r2)
        self.assertEqual(r1["metrics"], plain["metrics"])            # the main run is the plain run
        self.assertEqual(r1["trades"], plain["trades"])
        self.assertNotIn("robust", plain)
        five = [r for r in r1["robust"]["max_positions"] if r["max_positions"] == 5][0]
        self.assertEqual(five["overall"]["trades"], plain["metrics"]["overall"]["trades"])
        self.assertIn("## Robustness: 3 seeded runs", bt.render_md(r1))

    def test_distribution(self):
        d = bt.distribution([5, 1, 3, None, 2, 4])
        self.assertEqual((d["n"], d["unknown"], d["median"], d["min"], d["max"]), (5, 1, 3, 1, 5))
        self.assertAlmostEqual(d["p10"], 1.4)
        self.assertAlmostEqual(d["p90"], 4.6)
        self.assertIsNone(bt.distribution([None])["median"])
        s = self.side(n=3)["summary"]
        for grp in ("overall",):
            for k in ("cagr_pct", "expectancy_r", "max_drawdown_pct", "trades"):
                for x in ("median", "p10", "p90", "min", "max"):
                    self.assertIn(x, s[grp][k])
        self.assertTrue(s["by_mode"])
        self.assertTrue(s["by_setup"])
        self.assertIn("beat_benchmark", s["by_mode"][sorted(s["by_mode"])[0]])
        rows = [{"overall": {"cagr_pct": c}, "benchmark_cagr_pct": 5.0} for c in (4.0, 6.0, 7.0, None)]
        self.assertEqual(bt.beat_share(rows, lambda r: r["overall"]["cagr_pct"])["runs"], 2)
        self.assertEqual(bt.beat_share(rows, lambda r: r["overall"]["cagr_pct"])["of"], 3)


class RobustCli(OfflineCase):
    def test_limits_and_default(self):
        self.build_universe()
        for n in ("51", "0"):
            p = self.run_script(BT, "run", "--years", "1", "--robust", n, ok=False)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("--robust N must be 1 to 50", p.stderr)
        res = self.run_script(BT, "run", "--years", "1", "--robust")
        self.assertEqual((res["params"]["robust"], res["robust"]["summary"]["runs"]), (20, 20))
        p = self.run_script(BT, "run", "--years", "1", "--robust-compare", "pullback=on", "nonsense.key=1", ok=False)
        self.assertIn("not a strategy setting", p.stderr)

    def test_write_api_and_tab(self):
        self.build_universe()
        self.run_script(BT, "run", "--years", "1", "--robust", "4", "--robust-compare", "pullback=on", "pullback=off",
                        "--write", as_json=False)
        f = glob.glob(os.path.join(self.dir, "backtest", "*.json"))
        self.assertEqual(len(f), 1)
        res = json.load(open(f[0], encoding="utf-8"))
        self.assertEqual(res["params"]["robust_compare"], ["pullback=on", "pullback=off"])
        self.assertIn("robust", res)                        # --robust given too: your settings (= A here, reused)
        self.assertEqual(res["robust"]["runs"], res["robust_compare"]["a"]["runs"])
        d = DASH.api_backtest({"id": [res["id"]]})
        self.assertIn("robust", d["order"])
        self.assertLess(d["order"].index("banners"), d["order"].index("robust"))
        rb = d["robust"]
        self.assertEqual([s["title"] for s in rb["sides"]], ["Your settings: " + "default@%d" % tc.DEFAULTS_VERSION, "A: pullback=on", "B: pullback=off"])
        self.assertEqual(rb["compare"]["verdict_text"], bt.NO_CLEAR + ".")
        for m in rb["sides"][0]["metrics"] + rb["compare"]["metrics"]:
            self.assertTrue(m["text"].startswith(m["label"]))
            b = m["bar"]
            self.assertTrue(0 <= b["min"] <= b["lo"] <= b["mid"] <= b["hi"] <= b["max"] <= 100, m)
            if m["key"] != "trades":
                self.assertIsNotNone(b["zero"])
        self.assertEqual([r["max_positions"] for r in rb["sides"][0]["max_positions"]], ["3", "5", "8"])
        html = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        for s in ("robust:function", "function btRanges", "rb-band", "rb-mid", "btVerdict", "aria-label\":m.text"):
            self.assertIn(s, html)
        md = open(f[0][:-5] + ".md", encoding="utf-8").read()
        self.assertIn("## Robust compare: A = pullback=on, B = pullback=off", md)
        self.assertIn("**%s.**" % bt.NO_CLEAR, md)
        self.assertIsNone(DASH.bt_robust({"params": {}}))


# --- B3. --robust-compare --------------------------------------------------------------------------------

class RobustCompare(OfflineCase):
    def test_verdict_thresholds(self):
        V = bt.verdict
        self.assertEqual(V(16, 4, 20), ("better", "B is better in 16 of 20 runs"))
        self.assertEqual(V(20, 0, 20), ("better", "B is better in 20 of 20 runs"))
        self.assertEqual(V(15, 5, 20)[0], "unclear")
        self.assertEqual(V(15, 5, 20)[1], "No clear difference: don't change the default on this evidence")
        self.assertEqual(V(4, 16, 20), ("worse", "B is worse in 16 of 20 runs"))      # B beat A in 4 = 20%
        self.assertEqual(V(5, 15, 20)[0], "unclear")
        self.assertEqual(V(0, 0, 20)[0], "unclear")                                     # all equal: no evidence
        self.assertEqual(V(8, 2, 10)[0], "better")
        self.assertEqual(V(7, 3, 10)[0], "unclear")

    def test_pairs_by_seed(self):
        a = [{"seed": s, "start": "d%d" % s, "overall": {"cagr_pct": 5.0, "expectancy_r": 0.1, "max_drawdown_pct": -10.0,
                                                         "trades": 50}} for s in (1, 2, 3, 4, 5)]
        b = [dict(r, overall=dict(r["overall"], cagr_pct=5.0 + (1 if r["seed"] != 3 else -1), trades=48)) for r in a]
        pr = bt.paired(a, b)
        self.assertEqual([p["seed"] for p in pr], [1, 2, 3, 4, 5])
        self.assertEqual([p["cagr_pct"] for p in pr], [1.0, 1.0, -1.0, 1.0, 1.0])
        self.assertEqual([p["trades"] for p in pr], [-2] * 5)
        cs = bt.compare_summary(pr)
        self.assertEqual((cs["b_beat_a"], cs["b_lost"], cs["seeds"], cs["verdict"]), (4, 1, 5, "better"))
        self.assertEqual(cs["verdict_text"], "B is better in 4 of 5 runs")
        self.assertEqual(cs["difference"]["cagr_pct"]["median"], 1.0)
        with self.assertRaises(AssertionError):
            bt.paired(a, list(reversed(b)))                                   # never pairs different seeds

    def test_parse_settings(self):
        raw = {"capital": 150000}
        lab, c, rg = bt.parse_settings("pullback=off", raw)
        self.assertEqual((lab, rg, c["scanner"]["setups"]["pullback"]["enabled"], c["capital"]), ("pullback=off", "off", False, 150000))
        lab, c, rg = bt.parse_settings("default", raw)
        self.assertTrue(c["scanner"]["setups"]["pullback"]["enabled"])
        _, c, rg = bt.parse_settings("regime=close_below_200dma:half_risk, daily.top=8", raw)
        self.assertEqual((rg, c["daily"]["top"]), ("close_below_200dma:half_risk", 8))
        _, c, _ = bt.parse_settings("scanner.setups.pullback.enabled=false", raw)
        self.assertFalse(c["scanner"]["setups"]["pullback"]["enabled"])
        self.assertEqual(raw, {"capital": 150000})                               # your config is never changed
        for bad in ("no.such.key=1", "capital=5", "pullback", "regime=sell:all", "daily.top=999", "pullback=maybe"):
            with self.assertRaises(ValueError, msg=bad):
                bt.parse_settings(bad, raw)

    def test_compare_run_same_bars_and_seeds(self):
        self.build_universe()
        uni, cfg = tc.load_universe(), tc.load_config()
        sides = [("a", "pullback=on", bt.parse_settings("pullback=on", {})[1], "off"),
                 ("b", "pullback=off", bt.parse_settings("pullback=off", {})[1], "off")]
        calls = []

        def data_fn(*a, **k):
            calls.append(1)
            return loader(*a, **k)
        res = bt.run(dict(PARAMS, robust=4, robust_given=False, robust_compare=["pullback=on", "pullback=off"]), cfg, uni,
                     data_fn=data_fn, bench_fn=Counting(), robust_sides=sides)
        self.assertEqual(len(calls), 1)
        rc = res["robust_compare"]
        self.assertNotIn("robust", res)
        self.assertEqual([(r["seed"], r["start"]) for r in rc["a"]["runs"]], [(r["seed"], r["start"]) for r in rc["b"]["runs"]])
        self.assertEqual(rc["compare"]["seeds"], 4)
        self.assertEqual(rc["a"]["settings"]["same_as"], "default@2")
        self.assertEqual(rc["b"]["settings"]["same_as"], "default@3")
        self.assertIn(rc["compare"]["verdict"], ("better", "worse", "unclear"))
        self.assertIn("Robust compare", bt.render_md(res))


# --- docs and release ------------------------------------------------------------------------------------

class Docs(unittest.TestCase):
    def test_version_and_docs(self):
        self.assertTrue(tc.VERSION >= "0.2.6")              # pinned exactly by the newest test file
        guide = open(os.path.join(ROOT, "docs", "USER_GUIDE.md"), encoding="utf-8").read()
        faq = open(os.path.join(ROOT, "docs", "FAQ.md"), encoding="utf-8").read()
        for doc in (guide, faq):
            self.assertIn("Why one backtest number isn't enough", doc)
            self.assertIn("--robust-compare", doc)
        ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        top = ch.split("## v0.2.5")[0]
        self.assertIn("## v0.2.6", top)
        self.assertIn("--robust-compare", top)
        brief = open(os.path.join(ROOT, "docs", "PROJECT_BRIEF.md"), encoding="utf-8").read()
        self.assertIn("80%", brief)
        self.assertIn("default@4", brief)
        tech = open(os.path.join(ROOT, "docs", "TECHNICAL.md"), encoding="utf-8").read()
        self.assertIn("--robust", tech)
        self.assertIn("default@4", tech)


if __name__ == "__main__":
    unittest.main()
