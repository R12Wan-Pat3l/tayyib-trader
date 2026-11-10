"""v0.2.8: "My stocks" in tayyib-backtest (--symbols / --holdings: the same strategy on a basket you choose, against
buying and holding the same stocks), the dashboard's Run panel choice and its checked action, the MCP tool, and the
doc leftovers from the v0.2.7 review. Offline: fixtures (compliant ALFA, BRVO, CHRL, THIN; review ECHO; excluded DLTA,
ITC, EXBANK; unknown GOLF) and small synthetic data only."""
import copy
import glob
import importlib.util
import json
import os
import re
import sys
import unittest
from unittest import mock

from _util import ROOT, OfflineCase, tc
from test_v018 import ServerCase

for d in ("tayyib-backtest", "tayyib-dashboard"):
    sys.path.insert(0, os.path.join(ROOT, d))
import backtest as bt  # noqa: E402
import dashboard as DASH  # noqa: E402
import actions as A  # noqa: E402

BT = "tayyib-backtest/backtest.py"
COMPLIANT = ["ALFA", "BRVO", "CHRL", "THIN"]
PARAMS = {"mode": "all", "setups": None, "from": "2025-10-30", "to": "2026-10-30", "split": "2026-06-30",
          "max_positions": 5, "top": 10, "warmup_bars": 250, "tm_runs": 3000, "tm_seed": 7, "take_warn": True,
          "compare": False, "late": True, "end_rule": "--to 2026-10-30"}
POSITIONS = {"positions": [
    {"id": "ALFA-1", "symbol": "ALFA", "status": "open", "qty": 5, "entry": 100.0, "stop": 95.0},
    {"id": "HOLD-CHRL", "kind": "holding", "symbol": "CHRL", "status": "open", "qty": 10},
    {"id": "BRVO-1", "symbol": "BRVO", "status": "closed", "qty": 3}]}
INJECTIONS = ["ALFA;rm -rf ~", "ALFA && calc", "ALFA BRVO", "ALFA ", "'ALFA'", '"ALFA"', "../ALFA", "..\\ALFA",
              "C:/Windows", "ALFA|x", "ALFA`x`", "$(x)", "ALFA\nBRVO", "alfa", "ALFA.NS", "A" * 21, ""]


def loader(*a, **k):
    return bt.load_bars(*a, sleep=0, **k)


class Counting:
    """A price source that counts every call and fails like the offline benchmarks do."""

    def __init__(self):
        self.calls = []

    def __call__(self, sym, range_="2y"):
        self.calls.append((sym, range_))
        raise tc.FetchError("offline: %s" % sym)


def mine(syms, mode="symbols", **over):
    return dict(PARAMS, universe_mode=mode, symbols=list(syms), **over)


class Base(OfflineCase):
    def setUp(self):
        super().setUp()
        self.build_universe()
        self.uni = tc.load_universe()
        self.cfg = tc.load_config()


# --- A1 / A2: the rule -----------------------------------------------------------------------------------------

class Validation(Base):
    def test_compliant_only_sorted_and_deduped(self):
        self.assertEqual(tc.check_backtest_symbols("CHRL, ALFA,CHRL,ALFA", self.uni), (["ALFA", "CHRL"], []))
        self.assertEqual(tc.check_backtest_symbols(["THIN", "ALFA", "THIN"], self.uni), (["ALFA", "THIN"], []))
        self.assertEqual(tc.check_backtest_symbols(",".join(COMPLIANT), self.uni)[1], [])

    def test_each_status_refused_with_its_name(self):
        for sym, word in (("ECHO", "is review"), ("ITC", "is excluded"), ("DLTA", "is excluded"),
                          ("EXBANK", "is excluded"), ("GOLF", "is unknown"), ("ZZZZ", "not in the list")):
            syms, errs = tc.check_backtest_symbols("ALFA," + sym, self.uni)
            self.assertEqual(len(errs), 1, sym)
            self.assertTrue(errs[0].startswith(sym + " "), errs)
            self.assertIn(word, errs[0])
            self.assertIn("only compliant stocks can be tested", errs[0])
        self.assertIn("debt is 40.0%", tc.check_backtest_symbols("DLTA", self.uni)[1][0])      # the reason, not "passed"

    def test_long_reason_cut_at_a_word(self):
        uni = json.loads(json.dumps(self.uni))
        long_why = "non-compliant income is 4.79% of total income (limit 3%): reported interest 1.54% + assumed 8% " \
                   "return on short-term investments and more words after that"
        uni["stocks"]["ECHO"]["reasons"] = [long_why]
        e = tc.check_backtest_symbols("ECHO", uni)[1][0]
        self.assertIn("return on short-term...)", e)
        self.assertNotIn("inve)", e)

    def test_regex_and_never_dropped(self):
        for bad in INJECTIONS:
            syms, errs = tc.check_backtest_symbols(["ALFA", bad], self.uni)
            self.assertTrue(errs, bad)                                        # the whole request is refused
            self.assertIn("not an NSE symbol", errs[0], bad)
        self.assertIn("(use capitals, e.g. TCS)", tc.parse_symbol_list("alfa")[1][0])
        self.assertIn("'AAAAAAAAAAAAAAAAAAAAAAAA…'", tc.parse_symbol_list("A" * 40)[1][0])  # cut short, never in full
        for good in ("M&M", "BAJAJ-AUTO", "3MINDIA", "A" * 20):
            self.assertTrue(tc.BT_SYMBOL_RE.match(good), good)
            self.assertEqual(tc.parse_symbol_list(good), ([good], []))
        self.assertEqual(tc.parse_symbol_list(" ALFA , BRVO,"), (["ALFA", "BRVO"], []))      # CLI text: spaces at commas
        self.assertTrue(tc.parse_symbol_list([" ALFA"])[1])                                 # a list entry is exact
        for bad in (None, 5, {"a": 1}, [5], [None]):
            self.assertTrue(tc.parse_symbol_list(bad)[1], bad)

    def test_max_20_after_dedupe(self):
        twenty = ["S%02d" % k for k in range(20)]
        self.assertEqual(tc.parse_symbol_list(twenty + twenty)[1], [])
        self.assertEqual(tc.parse_symbol_list(twenty + ["S99"])[1], ["21 stocks chosen: at most 20"])
        self.assertEqual(tc.parse_symbol_list([])[1], ["choose 1 to 20 stocks"])
        self.assertIn("choose 1 to 20", tc.parse_symbol_list(["A"] * 201)[1][0])         # huge input: refused at once

    def test_holdings(self):
        self.assertEqual(tc.held_symbols(POSITIONS), ["ALFA", "CHRL"])            # open trade + holding, not the closed
        self.assertEqual(tc.check_holdings(POSITIONS, self.uni), (["ALFA", "CHRL"], []))
        self.assertIn("nothing to test", tc.check_holdings({}, self.uni)[1][0])
        bad = copy.deepcopy(POSITIONS)
        bad["positions"].append({"id": "HOLD-ECHO", "kind": "holding", "symbol": "ECHO.NS", "status": "open"})
        syms, errs = tc.check_holdings(bad, self.uni)
        self.assertEqual(errs, ["held stock: ECHO is review on today's halal list (industry 'Media, Entertainment & "
                                "Publication' needs a manual look): only compliant stocks can be tested"])
        many = {"positions": [{"symbol": "S%02d" % k, "status": "open"} for k in range(21)]}
        self.assertIn("you hold 21 stocks", tc.check_holdings(many, self.uni)[1][0])

    def test_cli_refuses_before_anything(self):
        for args, text in ((("--symbols", "ECHO"), "--symbols refused: ECHO is review"),
                           (("--symbols", "ALFA;rm"), "is not an NSE symbol"),
                           (("--symbols", ",".join("S%02d" % k for k in range(21))), "21 stocks chosen"),
                           (("--symbols", "ALFA", "--holdings"), "can't be combined"),
                           (("--holdings",), "--holdings refused: no open trades")):
            p = self.run_script(BT, "run", "--years", "1", *args, "--write", ok=False)
            self.assertNotEqual(p.returncode, 0, args)
            self.assertIn(text, p.stderr, args)
            self.assertFalse(os.path.exists(os.path.join(self.dir, "backtest")), args)    # nothing written
            self.assertNotIn("prices 1/", p.stderr)                                       # nothing loaded

    def test_cli_holdings_run(self):
        self.write("positions.json", POSITIONS)
        res = self.run_script(BT, "run", "--years", "1", "--holdings")
        self.assertEqual((res["params"]["universe_mode"], res["params"]["symbols"]), ("holdings", ["ALFA", "CHRL"]))
        self.assertIn("_hold2_", res["id"])
        self.assertEqual(bt.universe_label(res), "2 held stocks: ALFA, CHRL")

    def test_run_checks_again(self):
        with self.assertRaises(ValueError):                    # the engine never tests a non-compliant stock
            bt.run(mine(["ALFA", "ECHO"]), self.cfg, self.uni, data_fn=loader, bench_fn=Counting())
        with self.assertRaises(ValueError):
            bt.run(dict(PARAMS, universe_mode="everything"), self.cfg, self.uni, data_fn=loader, bench_fn=Counting())


# --- A3 / A4 / A5 / A6 / A7 / A8: the run ---------------------------------------------------------------------

class Simulation(Base):
    def run_bt(self, params, data_fn=loader, **kw):
        return bt.run(params, self.cfg, self.uni, data_fn=data_fn, bench_fn=Counting(), **kw)

    def test_full_compliant_list_equals_option_1(self):
        plain = self.run_bt(dict(PARAMS))
        full = self.run_bt(mine(COMPLIANT))
        self.assertTrue(plain["trades"])
        for k in ("trades", "metrics", "split", "equity_curve", "counts", "late_joiners", "joined_late", "skipped"):
            self.assertEqual(full[k], plain[k], k)
        self.assertEqual(plain["params"]["universe_mode"], "all")
        self.assertEqual(plain["universe"]["mode"], "all")
        self.assertNotIn("basket", plain)
        self.assertNotIn("stocks", plain)
        self.assertNotIn(bt.BANNER_HINDSIGHT, plain["banners"])
        # the "all" id is the one v0.2.7 gave: universe_mode "all" is not hashed
        self.assertEqual(plain["id"], bt.run_id(dict(PARAMS), plain["settings"]["hash"], COMPLIANT))
        self.assertTrue(re.match(r"^2026-10-30_all_2025-10-30_[0-9a-f]{6}$", plain["id"]), plain["id"])
        self.assertTrue(re.match(r"^2026-10-30_all_2025-10-30_sym4_[0-9a-f]{6}$", full["id"]), full["id"])

    def test_universe_is_only_the_chosen_stocks(self):
        asked = []

        def data_fn(syms, *a, **k):
            asked.append(list(syms))
            return loader(syms, *a, **k)
        for syms in (["ALFA"], ["CHRL", "THIN"]):
            res = self.run_bt(mine(syms), data_fn=data_fn)
            self.assertEqual(asked[-1], syms)                        # only these are loaded
            self.assertTrue({t["symbol"] for t in res["trades"]} <= set(syms))
            self.assertEqual(res["stocks"]["outside"], [])
            self.assertEqual(res["universe"]["tested"], len(syms))
            self.assertEqual(res["universe"]["symbols"], syms)
        self.assertTrue(any(t["symbol"] == "CHRL" for t in res["trades"]))

    def basket(self, chosen, data, skipped=(), late=(), start=PARAMS["from"]):
        days = sorted({b["date"] for bs in data.values() for b in bs if start <= b["date"] <= PARAMS["to"]})
        return bt.basket_benchmark(chosen, data, list(skipped), list(late), days, 100000.0, self.cfg), days

    def test_basket_equal_split_and_charges(self):
        data, _, late = loader(["ALFA", "CHRL"], "2y", PARAMS["from"], PARAMS["to"])
        bk, days = self.basket(["ALFA", "CHRL"], data, late=late)
        self.assertEqual((bk["status"], bk["in_basket"], bk["share_rs"]), ("OK", 2, 50000.0))
        self.assertEqual(bk["curve"][0], [days[0], 100000.0])
        tot = 0.0
        for s in ("ALFA", "CHRL"):
            st = bk["stocks"][s]
            first = min(d for d in days if d >= bt.join_date(data[s]))      # its first day in the test
            self.assertEqual(st["buy_date"], first)
            self.assertEqual(st["joined_late"], first > days[0])
            buy_ch = bt._charges("BUY", st["buy_price"], st["units"], self.cfg)
            sell_ch = bt._charges("SELL", st["end_price"], st["units"], self.cfg)
            self.assertGreater(buy_ch, 0)
            self.assertAlmostEqual(st["units"] * st["buy_price"] + buy_ch, 50000.0, delta=1.0)
            self.assertAlmostEqual(st["units"] * st["end_price"] - sell_ch, st["end_value_rs"], delta=1.0)
            self.assertAlmostEqual(st["charges_rs"], buy_ch + sell_ch, delta=0.05)
            self.assertAlmostEqual(st["return_pct"], (st["end_value_rs"] / 50000.0 - 1) * 100, delta=0.01)
            tot += st["end_value_rs"]
        self.assertAlmostEqual(bk["curve"][-1][1], tot, delta=0.05)
        self.assertAlmostEqual(bk["total_return_pct"], (tot / 100000.0 - 1) * 100, delta=0.01)
        self.assertAlmostEqual(bk["charges_rs"], sum(bk["stocks"][s]["charges_rs"] for s in ("ALFA", "CHRL")), delta=0.05)

    def test_late_joiner_waits_as_cash(self):
        data, _, _ = loader(["ALFA"], "2y", PARAMS["from"], PARAMS["to"])
        start = bt.join_date(data["ALFA"])                               # the window starts on ALFA's join day
        lb = copy.deepcopy(data["ALFA"][100:])                           # the same prices, listed 100 sessions later
        data["LATE"] = lb
        j = bt.join_date(lb)
        bk, days = self.basket(["ALFA", "LATE"], data, late=[{"symbol": "LATE", "join_date": j}], start=start)
        self.assertEqual(days[0], start)
        self.assertGreater(j, days[0])
        a, l = bk["stocks"]["ALFA"], bk["stocks"]["LATE"]
        self.assertEqual((a["buy_date"], l["buy_date"], l["joined_late"]), (days[0], j, True))
        closes = {b["date"]: b["close"] for b in data["ALFA"]}
        curve = dict((d, v) for d, v in bk["curve"])
        before = [d for d in days[1:] if d < j]
        self.assertTrue(before)
        for d in before:                                     # LATE's half is plain cash until its join day
            self.assertAlmostEqual(curve[d], 50000.0 + a["units"] * closes[d], delta=0.05)
        lc = {b["date"]: b["close"] for b in lb}
        self.assertAlmostEqual(curve[j], a["units"] * closes[j] + l["units"] * lc[j], delta=0.05)

    def test_missing_data_stock_left_out_and_reported(self):
        def data_fn(syms, range_, start, end, progress=None):
            data, skipped, late = loader([s for s in syms if s != "THIN"], range_, start, end)
            return data, skipped + [{"symbol": "THIN", "reason": "no price data: offline test"}], late
        res = self.run_bt(mine(["ALFA", "CHRL", "THIN"]), data_fn=data_fn)
        bk = res["basket"]
        self.assertEqual((bk["status"], bk["in_basket"], bk["share_rs"]), ("OK", 2, 50000.0))
        self.assertEqual(bk["stocks"]["THIN"], {"status": "UNKNOWN", "reason": "no price data: offline test"})
        self.assertEqual(bk["left_out"], [{"symbol": "THIN", "reason": "no price data: offline test"}])
        row = [r for r in res["stocks"]["rows"] if r["symbol"] == "THIN"][0]
        self.assertEqual((row["hold_status"], row["hold_return_pct"], row["vs"], row["trades"]),
                         ("UNKNOWN", None, "no trades", 0))
        self.assertTrue(any(b.startswith("Left out of the test and the basket (UNKNOWN): THIN (no price data")
                            for b in res["banners"]))
        md = bt.render_md(res)
        self.assertIn("UNKNOWN (no price data: offline test)", md)
        nothing = bt.basket_benchmark(["THIN"], {}, [{"symbol": "THIN", "reason": "no price data"}], [],
                                      ["2026-01-01", "2026-01-02"], 100000.0, self.cfg)
        self.assertEqual(nothing["status"], "UNKNOWN")                       # never a 0% return
        self.assertNotIn("total_return_pct", nothing)

    def test_no_late_leaves_late_joiners_out_of_the_basket(self):
        data, _, _ = loader(["ALFA"], "2y", PARAMS["from"], PARAMS["to"])
        data["LATE"] = copy.deepcopy(data["ALFA"][100:])
        days = sorted({b["date"] for b in data["ALFA"] if PARAMS["from"] <= b["date"] <= PARAMS["to"]})
        bk = bt.basket_benchmark(["ALFA", "LATE"], data, [], [{"symbol": "LATE"}], days, 100000.0, self.cfg, no_late=True)
        self.assertEqual((bk["in_basket"], bk["stocks"]["LATE"]["status"]), (1, "UNKNOWN"))
        self.assertIn("--no-late", bk["stocks"]["LATE"]["reason"])
        res = self.run_bt(mine(["ALFA", "CHRL"], late=False))
        self.assertEqual(res["basket"]["status"], "OK")

    def test_per_stock_table_adds_up(self):
        res = self.run_bt(mine(COMPLIANT))
        st, o = res["stocks"], res["metrics"]["overall"]
        self.assertEqual([r["symbol"] for r in st["rows"]], COMPLIANT)
        self.assertEqual(sum(r["trades"] for r in st["rows"]), o["trades"])
        self.assertEqual(st["totals"]["trades"], o["trades"])
        self.assertAlmostEqual(st["totals"]["pnl_rs"], o["pnl_rs"], delta=0.05)
        self.assertEqual(st["totals"]["wins"], sum(1 for t in res["trades"] if t["r"] > 0))
        self.assertAlmostEqual(st["totals"]["total_r"], sum(t["r"] for t in res["trades"]), delta=0.01)
        for r in st["rows"]:
            ts = [t for t in res["trades"] if t["symbol"] == r["symbol"]]
            self.assertEqual(r["too_few"], len(ts) < 30)
            if ts:
                self.assertIn(r["vs"], ("better", "worse", "same"))
                self.assertEqual(r["win_rate_pct"], round(r["wins"] / len(ts) * 100, 1))
                self.assertEqual(r["vs"] == "better", r["strategy_return_pct"] > r["hold_return_pct"])
                self.assertAlmostEqual(r["strategy_return_pct"], r["pnl_rs"] / res["basket"]["share_rs"] * 100, delta=0.01)
            else:
                self.assertEqual((r["vs"], r["win_rate_pct"]), ("no trades", None))

    def test_banners(self):
        res = self.run_bt(mine(["ALFA", "CHRL"]))
        b = res["banners"]
        self.assertEqual(b[0], bt.BANNER_HINDSIGHT)
        self.assertEqual(b[1], bt.BANNER_SMALL)                                         # 2 stocks: under 10
        for x in (bt.BANNER_HALAL, bt.BANNER_SURVIVOR, bt.BANNER_PAST, bt.BANNER_NEWS):
            self.assertIn(x, b)
            self.assertGreater(b.index(x), b.index(bt.BANNER_HINDSIGHT))
        better = res["basket"]["cagr_pct"] > res["metrics"]["overall"]["cagr_pct"]
        self.assertEqual(bt.BANNER_HOLD in b, better)
        OK = {"status": "OK", "cagr_pct": 6.0}
        self.assertEqual(bt.basket_banners(12, {"cagr_pct": 5.0}, OK), [bt.BANNER_HINDSIGHT, bt.BANNER_HOLD])
        self.assertEqual(bt.basket_banners(10, {"cagr_pct": 7.0}, OK), [bt.BANNER_HINDSIGHT])
        self.assertEqual(bt.basket_banners(10, {"cagr_pct": 6.0}, OK), [bt.BANNER_HINDSIGHT])     # equal: not better
        self.assertEqual(bt.basket_banners(9, {"cagr_pct": None}, OK), [bt.BANNER_HINDSIGHT, bt.BANNER_SMALL])
        self.assertEqual(bt.basket_banners(3, {"cagr_pct": 1.0}, {"status": "UNKNOWN", "reason": "x"})[-1],
                         "Buying and holding these stocks is UNKNOWN: x.")

    def test_compare_robust_and_robust_compare_with_symbols(self):
        calls, bench = [], Counting()

        def data_fn(syms, *a, **k):
            calls.append(list(syms))
            return loader(syms, *a, **k)
        sides = [("a", "pullback=on", bt.parse_settings("pullback=on", {})[1], "off"),
                 ("b", "pullback=off", bt.parse_settings("pullback=off", {})[1], "off")]
        p = mine(["ALFA", "CHRL"], compare=True, robust=3, robust_given=True,
                 robust_compare=["pullback=on", "pullback=off"])
        r1 = bt.run(dict(p), self.cfg, self.uni, data_fn=data_fn, bench_fn=bench, robust_sides=sides)
        r2 = bt.run(dict(p), self.cfg, self.uni, data_fn=data_fn, bench_fn=Counting(), robust_sides=sides)
        r1.pop("run_at"), r2.pop("run_at")
        self.assertEqual(r1, r2)                                                       # deterministic
        self.assertEqual(calls, [["ALFA", "CHRL"], ["ALFA", "CHRL"]])                  # one load per run
        self.assertEqual(sorted(set(bench.calls)), sorted(bench.calls))                # each benchmark asked for once
        self.assertEqual({s for s, _ in bench.calls}, {"SHARIABEES.NS", "^NSEI"})      # the basket downloads nothing
        self.assertIn("compare", r1)
        self.assertEqual(r1["robust"]["summary"]["runs"], 3)
        self.assertEqual(r1["robust_compare"]["compare"]["seeds"], 3)
        for x in [r1["robust"]] + [r1["robust_compare"][k] for k in ("a", "b")]:
            for run in x["runs"]:
                self.assertEqual(run["tie_first"], bt.tie_order(run["seed"], ["ALFA", "CHRL"])[:5])
        self.assertIn("basket", r1)
        pre = loader(["ALFA", "CHRL"], "2y", PARAMS["from"], PARAMS["to"])
        orig = tc.get_daily_bars
        try:                                     # with the bars in hand, nothing else may be fetched at all
            tc.get_daily_bars = lambda *a, **k: self.fail("downloaded during the robust runs")
            r3 = bt.run(dict(p), self.cfg, self.uni, data_fn=lambda *a, **k: pre, bench_fn=Counting(),
                        robust_sides=sides)
        finally:
            tc.get_daily_bars = orig
        r3.pop("run_at")
        self.assertEqual(r3, r1)
        nl = self.run_bt(mine(["ALFA", "CHRL"], late=False, compare=True))
        self.assertEqual(nl["compare"]["no_late"], nl["compare"]["as_run"])

    def test_ids_list_and_labels(self):
        res = self.run_bt(mine(["ALFA", "CHRL"]))
        self.assertIn("_sym2_", res["id"])
        self.assertEqual(bt.universe_label(res), "2 stocks: ALFA, CHRL")
        seven = {"universe": {"mode": "symbols", "symbols": ["A", "B", "C", "D", "E", "F", "G"]}}
        self.assertEqual(bt.universe_label(seven), "7 stocks: A, B, C, D, E, +2 more")
        self.assertEqual(bt.universe_label({"universe": {"compliant": 183}}), "all 183")      # an older run
        self.assertEqual(bt.universe_label({"universe": {"mode": "symbols", "symbols": ["TCS"]}}), "1 stock: TCS")
        self.assertEqual(bt.summary(res)["universe"], "2 stocks: ALFA, CHRL")
        for rid in (res["id"], "2026-10-30_all_2025-10-30_ab12cd", "2026-10-30_swing_2025-10-30_hold12_ab12cd"):
            self.assertTrue(DASH.BT_ID_RE.match(rid), rid)
        for rid in ("2026-10-30_all_2025-10-30_sym_ab12cd", "2026-10-30_all_2025-10-30_x2_ab12cd",
                    "2026-10-30_all_2025-10-30_sym123_ab12cd", "../2026-10-30_all_2025-10-30_ab12cd"):
            self.assertFalse(DASH.BT_ID_RE.match(rid), rid)


# --- B: the dashboard ------------------------------------------------------------------------------------------

class FakeProc:
    def __init__(self):
        self.stdout = iter([])

    def wait(self):
        return 1


class Action(Base):
    def body(self, **b):
        return {"backtest": dict({"years": 5, "mode": "all", "compare": False}, **b)}

    def test_only_validated_symbols_or_holdings(self):
        kind, opts = A.run_request(self.body(symbols=["CHRL", "ALFA", "ALFA"]))
        self.assertEqual((kind, opts["symbols"]), ("backtest", ["ALFA", "CHRL"]))
        self.assertEqual(A.backtest_argv(opts), ["run", "--years", "5", "--mode", "all", "--symbols=ALFA,CHRL", "--write"])
        self.assertEqual(A.backtest_argv(A.run_request(self.body())[1]),
                         ["run", "--years", "5", "--mode", "all", "--write"])            # unchanged without a choice
        self.write("positions.json", POSITIONS)
        kind, opts = A.run_request(self.body(holdings=True, compare=True))
        self.assertEqual(A.backtest_argv(opts), ["run", "--years", "5", "--mode", "all", "--compare", "--holdings", "--write"])

    def test_injection_refused_before_any_process(self):
        self.write("positions.json", {"positions": [{"symbol": "ECHO", "status": "open"}]})
        bad = [self.body(symbols=["ALFA", x]) for x in INJECTIONS] + [
            self.body(symbols=["S%02d" % k for k in range(21)]),                  # 21 symbols
            self.body(symbols=["ECHO"]),                                          # a review stock
            self.body(symbols=["ALFA", "ITC"]), self.body(symbols=["ZZZZ"]),
            self.body(symbols="ALFA,BRVO"),                                        # text, not a list
            self.body(symbols=["ALFA"], holdings=True), self.body(holdings="yes"), self.body(holdings=True),
            self.body(symbols=[]), self.body(symbols=[["ALFA"]]), self.body(args=["--symbols", "ECHO"]),
            {"backtest": self.body()["backtest"], "symbols": ["ALFA"]}]
        runner = A.Runner(python="python-that-must-not-start")
        with mock.patch.object(A.subprocess, "Popen", side_effect=AssertionError("a process started")) as po:
            for b in bad:
                with self.assertRaises(A.Refused, msg=json.dumps(b)) as cm:
                    runner.start(b)
                self.assertEqual(cm.exception.code, 400, b)
            self.assertEqual(po.call_count, 0)
        self.assertEqual(runner.status()["state"], "idle")
        with self.assertRaises(A.Refused) as cm:
            A.run_request(self.body(symbols=["ECHO"]))
        self.assertIn("ECHO is review on today's halal list", cm.exception.errors[0])

    def test_args_are_a_list_never_a_shell(self):
        seen = []

        def fake(cmd, **kw):
            seen.append((cmd, kw))
            return FakeProc()
        runner = A.Runner(python="py-test")
        with mock.patch.object(A.subprocess, "Popen", side_effect=fake):
            st = runner.start(self.body(symbols=["ALFA", "CHRL"]))
        cmd, kw = seen[0]
        self.assertIsInstance(cmd, list)
        self.assertFalse(kw.get("shell", False))
        self.assertEqual(cmd[0], "py-test")
        self.assertEqual(cmd[2:], ["run", "--years", "5", "--mode", "all", "--symbols=ALFA,CHRL", "--write"])
        self.assertTrue(all(isinstance(x, str) for x in cmd))
        self.assertIn("--symbols=ALFA,CHRL", st["command"])

    def test_choices(self):
        ch = DASH.api_backtest_choices({})
        self.assertEqual([s["symbol"] for s in ch["stocks"]], COMPLIANT)              # compliant only
        self.assertEqual(ch["stocks"][0]["name"], "Alfa Industries Ltd.")
        self.assertEqual((ch["max"], ch["fair_note"]), (20, "Pick at least 10 stocks for a fairer test."))
        h = ch["holdings"]
        self.assertFalse(h["available"])
        self.assertIn("no open trades or imported holdings", h["reason"])
        self.write("positions.json", POSITIONS)
        self.assertEqual(DASH.api_backtest_choices({})["holdings"], {"available": True, "symbols": ["ALFA", "CHRL"], "reason": None})
        self.write("positions.json", {"positions": [{"symbol": "ECHO", "status": "open"}]})
        h = DASH.api_backtest_choices({})["holdings"]
        self.assertFalse(h["available"])
        self.assertIn("ECHO is review", h["reason"])


class Http(ServerCase):
    def test_400_with_the_reason_and_nothing_started(self):
        self.build_universe()
        with mock.patch.object(A.subprocess, "Popen", side_effect=AssertionError("a process started")) as po:
            for syms, text in ((["ECHO"], "ECHO is review"), (["ALFA;calc"], "not an NSE symbol"),
                               (["S%02d" % k for k in range(21)], "21 stocks chosen")):
                r, out = self.post("/api/run", {"backtest": {"years": 3, "mode": "all", "compare": False, "symbols": syms}})
                self.assertEqual(r.status, 400, out)
                self.assertIn(text, out["error"])
            self.assertEqual(po.call_count, 0)
        r, out = self.req("/api/backtest/choices")
        self.assertEqual(r.status, 200)
        self.assertEqual(len(out["stocks"]), 4)
        r, _ = self.req("/api/backtest/choices", "POST", {}, self.good())
        self.assertEqual(r.status, 405)                                         # still exactly two POST routes


class ApiShape(Base):
    def test_symbols_run_in_the_tab(self):
        self.run_script(BT, "run", "--years", "1", "--symbols", "ALFA,CHRL,THIN", "--write", as_json=False)
        self.run_script(BT, "run", "--years", "1", "--write", as_json=False)
        files = sorted(glob.glob(os.path.join(self.dir, "backtest", "*.json")))
        self.assertEqual(len(files), 2)
        rid = [os.path.basename(f)[:-5] for f in files if "_sym3_" in f][0]
        d = DASH.api_backtest({"id": [rid]})
        self.assertNotIn("error", d)
        o = d["order"]
        self.assertTrue(o.index("banners") < o.index("cards") < o.index("stocks") < o.index("trades"))
        self.assertEqual(d["banners"][0], bt.BANNER_HINDSIGHT)
        self.assertEqual([c["key"] for c in d["cards"]], ["strategy", "basket", "SHARIABEES.NS"])
        self.assertEqual(d["cards"][1]["title"], "Buy & hold these stocks")
        self.assertEqual(d["cards"][0]["label"], "the daily list's rules, on these stocks only")   # not "the daily list"
        self.assertEqual(d["cards"][1]["items"][0]["label"], "Total return")
        self.assertEqual(d["cards"][2]["status"], "UNKNOWN")                       # offline ETF: UNKNOWN, never 0
        keys = [s["key"] for s in d["equity"]["series"]]
        self.assertEqual(keys[:2], ["strategy", "basket"])
        self.assertTrue(any("Nifty 50" in x for x in d["equity"]["missing_lines"]))   # still listed, as reference
        st = d["stocks"]
        self.assertEqual([r["symbol"] for r in st["rows"]], ["ALFA", "CHRL", "THIN"])
        for r in st["rows"]:
            self.assertIn(r["vs"], ("better", "worse", "no trades", "same"))
            self.assertIn("display", r)
        self.assertIn("{'label': 'Stocks', 'value': '3 stocks: ALFA, CHRL, THIN'}", str(d["header"]["items"]))
        self.assertEqual((d["universe_mode"], d["universe"]["chosen"]), ("symbols", 3))
        runs = DASH.api_backtests({})["runs"]
        labels = {r["id"]: r["label"] for r in runs}
        self.assertIn("3 stocks: ALFA, CHRL, THIN", labels[rid])
        other = [r for r in runs if r["id"] != rid][0]
        self.assertIn(" · all 4 · ", other["label"])
        da = DASH.api_backtest({"id": [other["id"]]})
        self.assertEqual([c["key"] for c in da["cards"]], ["strategy", "SHARIABEES.NS", "^NSEI"])
        self.assertIsNone(da["stocks"])
        md = _doc(self.dir, "backtest", rid + ".md")
        self.assertIn("## Your stocks: strategy vs holding", md)
        self.assertIn("| Buy and hold these stocks (3 stocks) |", md)

    def test_page(self):
        html = _doc("tayyib-dashboard", "index.html")
        for s in ("function btUniverse", "/api/backtest/choices", "All halal stocks (what the daily list does)",
                  "\"My stocks\"", "\"Stocks I hold\"", "ch.fair_note", "stocks:function", "s-basket", "req.symbols",
                  "req.holdings = true", "\"Remove \" + sym", "e.key !== \"Enter\"", "e.preventDefault()"):
            self.assertIn(s, html)
        self.assertNotIn("innerHTML", html)


# --- MCP ------------------------------------------------------------------------------------------------------

def _mcp():
    spec = importlib.util.spec_from_file_location("tayyib_mcp_v028", os.path.join(ROOT, "mcp", "server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Mcp(Base):
    def test_backtest_run_symbols_checked_the_same_way(self):
        M = _mcp()
        build = M.TOOLS["backtest_run"][3]
        args, err = M.check_backtest({"symbols": "CHRL, ALFA", "_symbols": ["ECHO"]})
        self.assertIsNone(err)
        argv = build(args)
        self.assertIn("--symbols=ALFA,CHRL", argv)
        self.assertNotIn("--write", argv)                                      # MCP still saves nothing
        for bad, text in (({"symbols": "ECHO"}, "ECHO is review"), ({"symbols": "ALFA;calc"}, "not an NSE symbol"),
                          ({"symbols": "ALFA", "holdings": True}, "can't be combined"),
                          ({"holdings": True}, "no open trades"), ({"symbols": ["ALFA"]}, "comma-separated")):
            _, err = M.check_backtest(bad)
            self.assertIn(text, err or "", bad)
            self.assertTrue(M.run_tool("backtest_run", bad)[0])                 # an error, nothing started
        self.write("positions.json", POSITIONS)
        args, err = M.check_backtest({"holdings": True})
        self.assertIsNone(err)
        self.assertIn("--holdings", build(args))
        self.assertIn("symbols", M.TOOLS["backtest_run"][1]["properties"])
        self.assertEqual(M.VERSION, tc.VERSION)


# --- C / E: docs and release ----------------------------------------------------------------------------------

def _doc(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class Docs(unittest.TestCase):
    def test_v027_leftovers(self):
        faq, readme = _doc("docs", "FAQ.md"), _doc("README.md")
        self.assertNotIn("looser with a note", faq)
        self.assertNotIn("or you approved it", faq)
        self.assertNotIn("approve that one", faq)
        self.assertIn("| compliant | passed every test | yes |", faq)
        self.assertNotIn("override", readme.lower())
        self.assertNotIn("loosen", readme.lower())
        self.assertIn("### Why is pullback on?", faq)
        self.assertIn("-0.21R over 46 trades", faq)
        doc = tc.DEFAULT_CONFIG_DOCS["scanner.setups.pullback.enabled"]
        self.assertNotIn("note", doc)                                           # one short line, like the others
        self.assertEqual(doc["hint"], "In an uptrend and dipped to its 20-day average: buy the bounce.")
        for s in ("trend", "breakout", "oversold", "squeeze"):
            self.assertNotIn("note", tc.DEFAULT_CONFIG_DOCS["scanner.setups.%s.enabled" % s])

    def test_new_docs(self):
        guide, faq = _doc("docs", "USER_GUIDE.md"), _doc("docs", "FAQ.md")
        self.assertIn("Test on your own stocks", guide)
        self.assertIn("hindsight", guide.lower())
        self.assertIn("at least 10", guide)
        self.assertIn("Why did buying and holding beat the strategy on my stocks?", faq)
        tech = _doc("docs", "TECHNICAL.md")
        for s in ("--symbols", "--holdings", "basket", "check_backtest_symbols"):
            self.assertIn(s, tech)
        self.assertIn("two options", _doc("docs", "PROJECT_BRIEF.md"))
        self.assertIn("--symbols", _doc("tayyib-backtest", "SKILL.md"))

    def test_release(self):
        self.assertTrue(tc.VERSION >= "0.2.8")              # pinned exactly by the newest test file (test_v029)
        self.assertEqual(tc.DEFAULTS_VERSION, 5)                               # no decision changes: still default@5
        for f in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
            self.assertIn('"%s"' % tc.VERSION, _doc(f))
        top = _doc("CHANGELOG.md").split("## v0.2.7")[0]
        self.assertIn("## v0.2.8", top)
        self.assertIn("--symbols", top)


if __name__ == "__main__":
    unittest.main()
