"""v0.2.1: the backtest replays the risk check, lets recent listings join, and settles sales a day later."""
import copy
import json
import os
import sys
import unittest

from _util import OfflineCase, ROOT, tc
from test_v020 import CFG, Patched, flat, plan_for

sys.path.insert(0, os.path.join(ROOT, "tayyib-backtest"))
sys.path.insert(0, os.path.join(ROOT, "tayyib-risk"))
import backtest as bt  # noqa: E402
import check as check_mod  # noqa: E402


def filling(n=40, fill_at=11, exit_at=None, price=100.0):
    """Bars rising into the signal (so the time machine sees an uptrend), trading up through 101 on bar fill_at,
    then drifting; with exit_at, running to a 113 target there."""
    bars = flat(n, price=price)
    for k in range(fill_at):
        p = price - 2 * (fill_at - 1 - k)                                   # ... 98, 100 on the signal day
        bars[k].update(open=p - 1, high=p + 0.5, low=p - 1.5, close=p)
    bars[fill_at].update(open=100, high=102, low=99.5, close=101.8)
    for k in range(fill_at + 1, n):
        bars[k].update(open=102, high=103, low=101.5, close=102.5)
    if exit_at:
        bars[exit_at].update(open=103, high=114, low=102, close=113)
    return bars


def uni_of(spec):
    return {"updated": "2026-01-01", "stocks": {s: {"status": st, "industry": ind} for s, (st, ind) in spec.items()}}


class RiskInCore(unittest.TestCase):
    def test_check_py_calls_core(self):
        self.assertIs(check_mod.check_order, tc.risk_check_order)
        self.assertIs(check_mod.news_why, tc.risk_news_why)
        self.assertIs(check_mod.REQUIRED, tc.RISK_REQUIRED)

    def order(self, **kw):
        o = {"id": "AAA-x", "symbol": "AAA", "side": "BUY", "product": "CNC", "instrument": "EQ", "qty": 100,
             "trigger_price": 101.0, "stop": 95.0, "target": 113.0, "setup": "breakout", "mode": "swing",
             "valid_until": "2026-01-20", "loss_at_stop_rs": 700.0, "buy_charges_rs": 12.0, "reward_risk_net": 1.8}
        o.update(kw)
        return o

    def test_replay_only_drops_news_and_list_age(self):
        uni = uni_of({"AAA": ("compliant", "X")})
        live = tc.risk_check_order(self.order(), CFG, [], uni, {})
        rep = tc.risk_check_order(self.order(), CFG, [], uni, {}, today=tc.parse_date("2026-01-10"), replay=True)
        groups = lambda r: [(x["group"], x["check"]) for x in r["why"]]
        self.assertIn(("RISK", "halal list age"), groups(live))
        self.assertTrue([g for g in groups(live) if g[0] == "NEWS"])
        self.assertNotIn(("RISK", "halal list age"), groups(rep))
        self.assertFalse([g for g in groups(rep) if g[0] == "NEWS"])
        same = lambda r: [x for x in groups(r) if x[0] != "NEWS" and x[1] not in ("halal list age", "plan valid until")]
        self.assertEqual(same(live), same(rep))
        # live (today 2026-10-30) the plan has expired; on its own day in the replay it has not
        self.assertIn("plan expired on 2026-01-20: re-scan", live["block"])
        self.assertEqual(rep["status"], "PASS")


class RiskInReplay(Patched):
    def test_block_never_taken_warn_only_with_take_warn(self):
        bars = {s: filling(exit_at=15) for s in ("AAA", "BBB", "CCC")}
        d = [b["date"] for b in bars["AAA"]]
        picks = {d[10]: [(plan_for("AAA", d[10], 101.0, 95.0, 113.0, d[13]), 70),
                         (plan_for("BBB", d[10], 101.0, 95.0, 103.0, d[13]), 60),     # net R:R under 1.5: BLOCK
                         (plan_for("CCC", d[10], 101.0, 95.0, 113.0, d[13]), 50)]}    # a WARN (below)
        # v0.2.7: "review" can no longer be allowed, so CCC gets its WARN from a wrapped risk check (as news would)
        uni = uni_of({"AAA": ("compliant", "A"), "BBB": ("compliant", "B"), "CCC": ("compliant", "C")})
        cfg = tc.validate_config({})[0]
        real = tc.risk_check_order

        def with_warn(o, *a, **k):
            r = real(o, *a, **k)
            if o["symbol"] == "CCC" and r["status"] == "PASS":
                r = dict(r, status="WARN", warn=r["warn"] + ["test warning"])
            return r
        from unittest import mock
        patch = mock.patch.object(bt.tc, "risk_check_order", with_warn)
        patch.start()
        self.addCleanup(patch.stop)
        res = self.sim(bars, picks, d[5], d[-1], cfg=cfg, uni=uni, take_warn=True)
        self.assertEqual(sorted(t["symbol"] for t in res["trades"]), ["AAA", "CCC"])
        self.assertEqual({t["symbol"]: t["risk"] for t in res["trades"]}, {"AAA": "PASS", "CCC": "WARN"})
        c = res["counts"]
        self.assertEqual((c["risk_blocked_plans"], c["risk_blocked"]), (1, {"min net reward:risk": 1}))
        self.assertEqual((c["warn_taken"], c["warn_skipped"]), (1, 0))
        self.assertEqual(c["not_replayed"], {"news / HALAL-WATCH": 3, "halal list age": 3})
        res = self.sim(bars, picks, d[5], d[-1], cfg=cfg, uni=uni, take_warn=False)
        self.assertEqual([t["symbol"] for t in res["trades"]], ["AAA"])
        self.assertEqual((res["counts"]["warn_taken"], res["counts"]["warn_skipped"]), (0, 1))

    def test_industry_cap_with_three_signals_in_one_industry(self):
        bars = {s: filling() for s in ("AAA", "BBB", "CCC")}
        d = [b["date"] for b in bars["AAA"]]
        picks = {d[10]: [(plan_for(s, d[10], 101.0, 95.0, 113.0, d[13]), sc) for s, sc in
                         (("AAA", 70), ("BBB", 60), ("CCC", 50))]}
        uni = uni_of({s: ("compliant", "Pharma") for s in bars})
        res = self.sim(bars, picks, d[5], d[-1], uni=uni)
        c = res["counts"]
        self.assertEqual(c["plans"], 2)
        self.assertEqual(c["risk_blocked"], {"positions per industry": 1})
        self.assertEqual(sorted(t["symbol"] for t in res["trades"]), ["AAA", "BBB"])    # best scores first
        self.assertEqual(max(x["waiting_plans"] + x["open_positions"] for x in res["curve"]), 2)

    def test_heat_cap(self):
        bars = {s: filling() for s in ("AAA", "BBB", "CCC")}
        d = [b["date"] for b in bars["AAA"]]
        picks = {d[10]: [(plan_for(s, d[10], 101.0, 95.0, 113.0, d[13]), sc) for s, sc in
                         (("AAA", 70), ("BBB", 60), ("CCC", 50))]}
        uni = uni_of({"AAA": ("compliant", "A"), "BBB": ("compliant", "B"), "CCC": ("compliant", "C")})
        cfg = tc.validate_config({"max_portfolio_heat_pct": 2.5})[0]       # room for two 1% losses, not three
        res = self.sim(bars, picks, d[5], d[-1], cfg=cfg, uni=uni)
        self.assertEqual(res["counts"]["plans"], 2)
        self.assertEqual(res["counts"]["risk_blocked"], {"portfolio heat": 1})
        self.assertNotIn("CCC", [t["symbol"] for t in res["trades"]])


class Settlement(Patched):
    def test_stop_proceeds_cannot_pay_a_fill_the_same_day(self):
        n = 30
        a, b = flat(n, price=95.0), flat(n, price=95.0)
        d = [x["date"] for x in a]
        a[11].update(open=99, high=100.9, low=99.6, close=100.5)            # AAA fills at 100
        for k in range(12, n):                                              # under +1R: no breakeven move
            a[k].update(open=100.5, high=100.9, low=99.6, close=100.5)
        a[20].update(open=98, high=98.5, low=97, close=97.5)                # AAA gaps through its 99 stop
        b[20].update(open=160, high=161, low=159, close=160)                # BBB gaps up through 100 the same day
        for k in range(21, n):
            b[k].update(open=160, high=161, low=159, close=160)
        cfg = tc.validate_config({"max_position_pct": 40})[0]
        pa = plan_for("AAA", d[10], 100.0, 99.0, 200.0, d[13])
        pb = plan_for("BBB", d[10], 100.0, 99.0, 200.0, d[25])
        res = self.sim({"AAA": a, "BBB": b}, {d[10]: [(pa, 70), (pb, 60)]}, d[5], d[-1], cfg=cfg)
        t = {x["symbol"]: x for x in res["trades"]}
        self.assertEqual((t["AAA"]["exit_date"], t["AAA"]["exit_reason"]), (d[20], "STOP"))
        self.assertEqual(t["BBB"]["entry_date"], d[20])
        full = tc.size_trade(pb, cfg, 1e9)["qty"]
        self.assertEqual(full, 400)
        self.assertTrue(t["BBB"]["qty_cut_at_fill"])
        cash_free = next(x for x in res["curve"] if x["date"] == d[19])["cash"]   # what was free before the day
        self.assertLessEqual(t["BBB"]["qty"] * 160, cash_free)
        self.assertLess(t["BBB"]["qty"], full)
        # with AAA's proceeds (about Rs 39,000 more) all 400 shares would have fitted
        self.assertGreater(cash_free + t["AAA"]["qty"] * 98 - t["AAA"]["charges"], full * 160 * 1.002)
        for x in res["curve"]:
            self.assertGreaterEqual(x["cash"], 0)


class LateListing(OfflineCase):
    def test_joins_on_its_250th_bar(self):
        alfa = tc.get_daily_bars("ALFA")[0]
        late = alfa[100:]                                                  # as if listed 100 sessions later
        join = bt.join_date(late)
        self.assertEqual(join, late[bt.WARMUP_BARS - 1]["date"])
        books = {"ALFA": bt.Book(late)}
        signals_before, after = 0, 0
        for b in late:
            n = len(bt.scan_day(books, b["date"], CFG, "all", None, set()))
            if b["date"] < join:
                signals_before += n
            else:
                after += n
        self.assertEqual(signals_before, 0)
        self.assertGreater(after, 0)
        full = {"ALFA": bt.Book(alfa)}                                      # the same days with full history do signal
        self.assertTrue(any(bt.scan_day(full, b["date"], CFG, "all", None, set())
                            for b in late if b["date"] < join))
        uni = uni_of({"ALFA": ("compliant", "X")})
        res = bt.simulate({"ALFA": late}, CFG, late[0]["date"], late[-1]["date"], "all", None, 5, uni=uni)
        self.assertTrue(res["trades"])
        self.assertTrue(all(t["signal_date"] >= join for t in res["trades"]))

    def test_load_bars_lists_late_joiners(self):
        data, skipped, late = bt.load_bars(["ALFA", "NODATA"], "2y", "2025-06-01", "2026-10-30", sleep=0)
        self.assertIn("ALFA", data)
        self.assertEqual([x["symbol"] for x in late], ["ALFA"])
        self.assertEqual(late[0]["join_date"], bt.join_date(data["ALFA"]))
        self.assertEqual([x["symbol"] for x in skipped], ["NODATA"])


class Labels(unittest.TestCase):
    def test_too_few_at_30(self):
        self.assertTrue(bt.flag_few({"trades": 29})["too_few"])
        self.assertFalse(bt.flag_few({"trades": 30})["too_few"])
        t = {"symbol": "A", "setup": "breakout", "mode": "swing", "signal_date": "2026-01-02", "entry_date": "2026-01-05",
             "exit_date": "2026-01-09", "r": 1.0, "pnl_rs": 100.0, "charges": 10.0}
        days = ["2026-01-02", "2026-01-05", "2026-01-09"]
        g = bt.group_metrics([t], days, 100000, "setup")
        self.assertTrue(g["breakout"]["too_few"])
        curve = [{"date": d, "equity": 100000.0, "open_positions": 0} for d in days]
        s = bt.split_metrics([t], curve, "2026-01-05")
        self.assertTrue(s["in_sample"]["too_few"] and s["out_of_sample"]["too_few"])
        md = "\n".join(bt.table([("breakout", g["breakout"])]))
        self.assertIn("breakout (too few to judge)", md)

    def test_nifty_banner(self):
        sp = {"in_sample": {"expectancy_r": 0.2}, "out_of_sample": {"expectancy_r": 0.2}}
        etf = {"status": "OK", "cagr_pct": 1.0}
        mk = lambda c: {bt.SHARIAH_BENCH: etf, bt.NIFTY: {"status": "OK", "cagr_pct": c}}
        self.assertIn(bt.BANNER_NIFTY, bt.banners({"trades": 40, "cagr_pct": 5.0}, sp, mk(5.01)))
        self.assertNotIn(bt.BANNER_NIFTY, bt.banners({"trades": 40, "cagr_pct": 5.0}, sp, mk(5.0)))
        b = bt.banners({"trades": 40, "cagr_pct": 5.0}, sp, {bt.SHARIAH_BENCH: etf, bt.NIFTY: {"status": "UNKNOWN"}})
        self.assertNotIn(bt.BANNER_NIFTY, b)
        self.assertIn(bt.BANNER_NEWS, b)                                  # always there
        self.assertNotIn(bt.BANNER_ETF, b)                                # the ETF banner is unchanged


class CompareAndDeterminism(OfflineCase):
    def test_compare_reuses_the_bars_and_is_deterministic(self):
        self.build_universe()
        calls = []

        def data_fn(*a, **kw):
            calls.append(1)
            return bt.load_bars(*a, sleep=0, **kw)

        cfg = tc.load_config()
        params = {"mode": "all", "setups": None, "from": "2025-10-30", "to": "2026-10-30", "split": "2026-06-30",
                  "max_positions": 5, "top": 10, "warmup_bars": 250, "tm_runs": 3000, "tm_seed": 7,
                  "take_warn": True, "compare": True}
        r1 = bt.run(params, cfg, tc.load_universe(), data_fn=data_fn)
        self.assertEqual(len(calls), 1)                                   # one download for both runs
        r2 = bt.run(copy.deepcopy(params), cfg, tc.load_universe(), data_fn=data_fn)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))
        cp = r1["compare"]
        self.assertEqual(cp["as_run"]["trades"], r1["metrics"]["overall"]["trades"])
        self.assertIn("score_only", cp)
        self.assertIn("## Compare: (a) as run, (b) score only", bt.render_md(r1))

    def test_cli_compare_and_params(self):
        self.build_universe()
        out = [self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", "--compare", "--no-take-warn",
                               as_json=False) for _ in range(2)]
        self.assertEqual(out[0], out[1])
        r = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1", "--no-take-warn")
        self.assertFalse(r["params"]["take_warn"])
        r = self.run_script("tayyib-backtest/backtest.py", "run", "--years", "1")
        self.assertTrue(r["params"]["take_warn"])
        self.assertIn(bt.BANNER_NEWS, r["banners"])
        self.assertIn("risk_blocked", r["counts"])
        self.assertIn("joined_late", r)

    def test_mcp_passes_the_new_flags(self):
        sys.path.insert(0, os.path.join(ROOT, "mcp"))
        import server
        argv = server.TOOLS["backtest_run"][3]({"compare": True, "take_warn": False})
        self.assertIn("--compare", argv)
        self.assertIn("--no-take-warn", argv)
        self.assertNotIn("--write", argv)
        self.assertNotIn("--compare", server.TOOLS["backtest_run"][3]({}))


class Version(unittest.TestCase):
    def test_version_and_defaults(self):
        self.assertGreaterEqual(tc.DEFAULTS_VERSION, 2)   # pinned exactly by the newest test file (v0.2.5: 3)


if __name__ == "__main__":
    unittest.main()
