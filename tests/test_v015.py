"""v0.1.5: thresholds in config, validate_config, halal loosening policy, why[], settings snapshot,
risk_preview. All offline, on the fixtures."""
import copy
import json
import os
import sys
import unittest
import zipfile

from _util import OfflineCase, ROOT, tc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tayyib-tracker"))
import baseline  # noqa: E402

DAILY, H, SC, RI, TR = ("tayyib-daily/daily.py", "tayyib-halal/halal.py", "tayyib-scanner/scan.py",
                        "tayyib-risk/check.py", "tayyib-tracker/tracker.py")


def V(user):
    return tc.validate_config(user)


def clean(cfg):
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


class BaselineIdentical(unittest.TestCase):
    """Default config: the same decisions as v0.1.4, field for field (tests/baseline.py)."""

    @classmethod
    def setUpClass(cls):
        cls.base = baseline.load_baseline()

    def test_sweep_identical(self):
        cur = baseline.sweep()
        self.assertEqual(sum(len(v["signals"]) for v in cur.values()), 2986)
        self.assertEqual(baseline.diff(self.base["sweep"], cur), [])

    def test_pipeline_identical(self):
        self.assertEqual(baseline.diff(self.base["pipeline"], baseline.pipeline()), [])

    def test_diff_catches_changes(self):
        b = {"a": [{"x": 1.0, "y": "s"}]}
        self.assertEqual(baseline.diff(b, {"a": [{"x": 1.0, "y": "s", "why": []}]}), [])
        self.assertTrue(baseline.diff(b, {"a": [{"x": 1.05, "y": "s"}]}))
        self.assertTrue(baseline.diff(b, {"a": [{"x": 1, "y": "s"}]}))              # type change counts
        self.assertTrue(baseline.diff(b, {"a": [{"y": "s"}]}))
        self.assertTrue(baseline.diff(b, {"a": [{"x": 1.0, "y": "s", "extra": 1}]}))


class Docs(unittest.TestCase):
    def test_every_setting_documented(self):
        leaves = tc._leaves(clean(tc.validate_config({})[0]))
        for k in leaves:
            if k.startswith("news.feeds."):
                continue
            self.assertIn(k, tc.DEFAULT_CONFIG_DOCS, k)
        for k, d in tc.DEFAULT_CONFIG_DOCS.items():
            self.assertTrue(d["description"], k)
            for f in ("description", "min", "max", "unit"):
                self.assertIn(f, d, k)
            self.assertTrue(k in leaves or k == "news.feeds", "documented but not a setting: %s" % k)

    def test_defaults_pass_their_own_ranges(self):
        cfg, notes = V(copy.deepcopy(clean(tc.DEFAULT_CONFIG)))
        self.assertEqual(notes, [])
        self.assertEqual(clean(cfg), clean(V({})[0]))

    def test_threshold_defaults_are_the_v014_values(self):
        st = tc.DEFAULT_CONFIG["scanner"]["setups"]
        self.assertEqual(st["breakout"]["max_distance_to_high_pct"], 3.0)
        self.assertEqual((st["pullback"]["rsi_min"], st["pullback"]["rsi_max"]), (35, 58))
        self.assertEqual(st["oversold"]["rsi_below"], 35)
        self.assertEqual(st["squeeze"]["max_range_ratio"], 0.5)
        self.assertEqual(st["trend"]["min_pct_of_high"], 85.0)
        # min_past_trades_for_rank is the one default@2 behaviour change (v0.1.7); 0 is the v0.1.4 order
        self.assertEqual(tc.DEFAULT_CONFIG["daily"], {"top": 10, "picks": 3, "min_expectancy_r": None,
                                                      "min_past_trades_for_rank": 8})


class Setups(OfflineCase):
    def sigs(self, cfg, sym="ALFA", setup=None):
        bars, _ = tc.get_daily_bars(sym)
        ind = tc.indicators(bars)
        names = [setup] if setup else list(tc.SWING_SETUPS + tc.DELIVERY_SETUPS)
        return {(n, i) for i in range(200, len(bars)) for n in tc.enabled_setups(cfg, names)
                if tc.detect(n, bars, ind, i, 0.05, cfg)}

    def test_each_setup_can_be_disabled(self):
        bars, _ = tc.get_daily_bars("ALFA")
        for setup, i in (("pullback", 200), ("squeeze", 236), ("breakout", 221), ("trend", 251),
                         ("oversold", 287)):
            on = [s["setup"] for s in tc.detect_all(bars[:i + 1], "all", cfg=V({})[0])]
            self.assertIn(setup, on)
            cfg, notes = V({"scanner": {"setups": {setup: {"enabled": False}}}})
            self.assertEqual(notes, [])
            off = [s["setup"] for s in tc.detect_all(bars[:i + 1], "all", cfg=cfg)]
            self.assertNotIn(setup, off, setup)
            self.assertEqual(sorted(set(on) - {setup}), sorted(off))           # the others are untouched

    def test_disabled_setup_in_the_scanner(self):
        self.build_universe()
        self.assertIn("breakout", {c["setup"] for c in self.run_script(SC)["candidates"]})
        self.write("config.json", {"scanner": {"setups": {"breakout": {"enabled": False}}}})
        out = self.run_script(SC)
        self.assertNotIn("breakout", {c["setup"] for c in out["candidates"]})
        self.assertEqual(out["setups_disabled"], ["breakout"])

    def test_thresholds_change_results_as_expected(self):
        d = V({})[0]
        # (setup, a stricter value, a looser value): stricter arms a strict subset, looser a strict superset
        cases = (("breakout", {"max_distance_to_high_pct": 1.0}, {"max_distance_to_high_pct": 6.0}),
                 ("pullback", {"rsi_max": 48}, {"rsi_max": 70}),
                 ("oversold", {"rsi_below": 30}, {"rsi_below": 45}),
                 ("squeeze", {"max_range_ratio": 0.35}, {"max_range_ratio": 0.7}),
                 ("trend", {"min_pct_of_high": 95.0}, {"min_return_pct": -20.0}))
        for setup, strict, loose in cases:
            base = self.sigs(d, "ALFA", setup) | self.sigs(d, "CHRL", setup)
            s_cfg = V({"scanner": {"setups": {setup: strict}}})[0]
            l_cfg = V({"scanner": {"setups": {setup: loose}}})[0]
            st = self.sigs(s_cfg, "ALFA", setup) | self.sigs(s_cfg, "CHRL", setup)
            lo = self.sigs(l_cfg, "ALFA", setup) | self.sigs(l_cfg, "CHRL", setup)
            self.assertTrue(st < base, "%s %s should arm fewer" % (setup, strict))
            self.assertTrue(base < lo, "%s %s should arm more" % (setup, loose))

    def test_why_records_the_threshold_used(self):
        bars, _ = tc.get_daily_bars("ALFA")
        cfg = V({"scanner": {"setups": {"breakout": {"max_distance_to_high_pct": 4.5}}}})[0]
        sig = [s for s in tc.detect_all(bars[:222], "swing", cfg=cfg) if s["setup"] == "breakout"][0]
        item = [w for w in sig["why"] if w["check"].startswith("distance under")][0]
        self.assertEqual(item["limit"], 4.5)
        h20 = max(b["high"] for b in bars[221 - 19:222])
        self.assertAlmostEqual(item["value"], (h20 - bars[221]["close"]) / bars[221]["close"] * 100, places=9)
        self.assertTrue(item["value"] <= 4.5 and item["ok"] is True)

    def test_min_score(self):
        bars, _ = tc.get_daily_bars("ALFA")
        best = max(s["score"] for s in tc.detect_all(bars, "all"))
        cfg = V({"scanner": {"setups": {n: {"min_score": best + 1} for n in tc.SWING_SETUPS + tc.DELIVERY_SETUPS}}})[0]
        self.assertEqual(tc.detect_all(bars, "all", cfg=cfg), [])


class Validate(unittest.TestCase):
    RANGES = (("max_risk_per_trade_pct", 0.25, 3), ("max_position_pct", 5, 40), ("max_open_positions", 1, 20),
              ("max_portfolio_heat_pct", 1, 15), ("min_reward_risk", 1, 5),
              ("modes.swing.max_stop_pct", 2, 10), ("modes.delivery.max_stop_pct", 3, 15))

    def nest(self, dotted, v):
        out = {}
        ks = dotted.split(".")
        cur = out
        for k in ks[:-1]:
            cur = cur.setdefault(k, {})
        cur[ks[-1]] = v
        return out

    def get(self, cfg, dotted):
        for k in dotted.split("."):
            cfg = cfg[k]
        return cfg

    def test_ranges_and_fallbacks(self):
        d = V({})[0]
        for key, lo, hi in self.RANGES:
            for ok in (lo, hi):
                cfg, notes = V(self.nest(key, ok))
                self.assertEqual(notes, [], key)
                self.assertEqual(self.get(cfg, key), ok)
            for bad in (lo - 0.01 if isinstance(lo, float) else lo - 1, hi + 1):
                cfg, notes = V(self.nest(key, bad))
                self.assertEqual(self.get(cfg, key), self.get(d, key), key)
                self.assertEqual(len(notes), 1, notes)
                self.assertTrue(notes[0].startswith("CONFIG: %s = " % key), notes)
                self.assertIn("invalid (range %s–%s), using default %s"
                              % (tc._fmt_val(lo), tc._fmt_val(hi), tc._fmt_val(self.get(d, key))), notes[0])

    def test_exact_message(self):
        _, notes = V({"max_position_pct": 50})
        self.assertEqual(notes, ["CONFIG: max_position_pct = 50 invalid (range 5–40), using default 20"])
        _, notes = V({"min_turnover_rs": 4000000})                   # under 50 lakh
        self.assertEqual(notes, ["CONFIG: min_turnover_rs = 4000000 invalid (range 5000000–100000000000), "
                                 "using default 20000000"])
        self.assertEqual(V({"min_turnover_rs": 5000000})[1], [])

    def test_one_bad_key_keeps_the_others(self):
        cfg, notes = V({"max_risk_per_trade_pct": 9, "max_position_pct": 15, "capital": 250000})
        self.assertEqual((cfg["max_risk_per_trade_pct"], cfg["max_position_pct"], cfg["capital"]), (1.0, 15, 250000))
        self.assertEqual(len(notes), 1)

    def test_types(self):
        for user in ({"max_open_positions": 2.5}, {"max_open_positions": True}, {"capital": "lots"},
                     {"broker": "robinhood"}, {"halal": {"allow_review": "yes"}}, {"holidays": ["31-12-2026"]},
                     {"modes": "fast"}, {"daily": {"top": 0}}):
            cfg, notes = V(user)
            self.assertEqual(len(notes), 1, (user, notes))
            self.assertEqual(clean(cfg), clean(V({})[0]), user)
        self.assertEqual(V({"daily": {"min_expectancy_r": None}})[1], [])
        self.assertEqual(V({"holidays": ["2026-12-25"]})[0]["holidays"], ["2026-12-25"])

    def test_unknown_keys_warned_and_ignored(self):
        cfg, notes = V({"colour": "green", "scanner": {"setups": {"breakout": {"magic": 1}}}})
        self.assertEqual(notes, ["CONFIG: unknown key colour ignored",
                                 "CONFIG: unknown key scanner.setups.breakout.magic ignored"])
        self.assertEqual(clean(cfg), clean(V({})[0]))

    def test_does_not_touch_the_defaults(self):
        before = json.dumps(tc.DEFAULT_CONFIG, sort_keys=True)
        V({"halal": {"max_debt_to_assets_pct": 40, "allow_review": True}, "max_position_pct": 99})
        V({"halal": {"max_debt_to_assets_pct": 20}})
        self.assertEqual(json.dumps(tc.DEFAULT_CONFIG, sort_keys=True), before)


HARD_RULE_TRIES = [
    {"product": "MIS"}, {"allow_intraday": True}, {"intraday": True}, {"allow_short": True},
    {"short_selling": True}, {"allow_fno": True}, {"fno": True}, {"options": True}, {"futures": True},
    {"allow_margin": True}, {"margin": True}, {"mtf": True}, {"leverage": 5},
    {"halal": {"require_compliant": False}}, {"halal": {"require_compliant": "no"}},
    {"halal": {"allow_excluded": True}}, {"halal": {"allow_unknown": True}}, {"halal": {"statuses": ["excluded"]}},
    {"modes": {"intraday": {"max_stop_pct": 1}}}, {"modes": {"swing": {"product": "MIS"}}},
    {"brokers": {"zerodha": {"product": "MIS", "margin": True}}}, {"scanner": {"setups": {"short_breakdown": {}}}},
    {"place_orders": True}, {"auto_trade": True}, {"_halal_loosened": "x"}, {"_notes": []},
]


class HardRules(OfflineCase):
    def test_no_key_changes_anything(self):
        default = clean(V({})[0])
        h = tc.settings_snapshot(V({})[0])["hash"]
        for user in HARD_RULE_TRIES:
            cfg, notes = V(user)
            self.assertEqual(clean(cfg), default, user)
            self.assertTrue(notes and all(n.startswith("CONFIG") for n in notes), user)
            self.assertEqual(tc.settings_snapshot(cfg)["hash"], h, user)
            self.assertIsNone(cfg["_halal_loosened"], user)

    def test_risk_check_still_blocks_with_them(self):
        self.build_universe()
        everything = {}
        for u in HARD_RULE_TRIES:
            everything = tc.deep_merge(everything, u)
        self.write("config.json", everything)
        self.run_script(SC)
        self.run_script("tayyib-exit/exit.py", "plan", "ALFA,CHRL", "--write")
        self.run_script("tayyib-budget/size.py", "--write")
        o = self.read("orders.json")
        for x in o["orders"]:
            x["product"] = "MIS"
        self.write("orders.json", o)
        self.assertTrue(all(r["status"] == "BLOCK" for r in self.run_script(RI)))
        # a stock that is not compliant stays blocked whatever the config says
        self.run_script(H, "override", "CHRL", "--status", "unknown", "--note", "t", as_json=False)
        for x in o["orders"]:
            x["product"] = "CNC"
        self.write("orders.json", o)
        res = {r["symbol"]: r for r in self.run_script(RI)}
        self.assertEqual(res["CHRL"]["status"], "BLOCK")
        self.assertTrue(any(b.startswith("halal: unknown") for b in res["CHRL"]["block"]))

    def test_exit_planner_refuses_non_compliant_even_with_allow_review(self):
        self.build_universe()
        self.write("config.json", {"halal": {"allow_review": True, "loosen_note": "test"}})
        out = self.run_script("tayyib-exit/exit.py", "plan", "DLTA,ITC")
        self.assertEqual([x.get("error") for x in out], ["not halal-compliant"] * 2)


class HalalLoosening(OfflineCase):
    def test_refused_without_a_note(self):
        for k, v in (("max_debt_to_assets_pct", 30), ("max_noncompliant_income_pct", 5),
                     ("max_cash_receivables_to_assets_pct", 95), ("noncompliant_investment_return_pct", 5),
                     ("allow_review", True)):
            cfg, notes = V({"halal": {k: v, "loosen_note": "  "}})
            self.assertEqual(cfg["halal"][k], tc.DEFAULT_CONFIG["halal"][k], k)
            self.assertTrue(any(n.startswith("CONFIG ERROR: halal.%s" % k) and "loosen_note" in n for n in notes), k)
            self.assertIsNone(cfg["_halal_loosened"])

    def test_stricter_needs_no_note(self):
        cfg, notes = V({"halal": {"max_debt_to_assets_pct": 20, "max_noncompliant_income_pct": 2,
                                  "max_cash_receivables_to_assets_pct": 70, "noncompliant_investment_return_pct": 10}})
        self.assertFalse([n for n in notes if "ERROR" in n])
        self.assertEqual(cfg["halal"]["max_debt_to_assets_pct"], 20)
        self.assertEqual(cfg["halal"]["method"], "custom")
        self.assertIsNone(cfg["_halal_loosened"])
        self.assertIsNone(tc.halal_banner(cfg))

    def test_stricter_screen_excludes_more(self):
        out = self.build_universe()
        self.write("config.json", {"halal": {"method": "custom", "max_debt_to_assets_pct": 5}})
        strict = self.build_universe()
        self.assertLess(strict["counts"]["compliant"], out["counts"]["compliant"])
        self.assertNotIn("banner", strict)
        self.assertEqual(self.read("halal_universe.json")["method"], "custom")

    def test_with_a_note_it_applies_and_the_banner_shows(self):
        note = "Mufti X, fatwa 12/2026"
        self.write("config.json", {"halal": {"method": "custom", "max_debt_to_assets_pct": 45,
                                             "loosen_note": note}})
        b = self.build_universe()
        banner = "Halal thresholds are looser than TASIS (your setting): " + note
        self.assertEqual(list(b)[0], "banner")
        self.assertEqual(b["banner"], banner)
        st = {r["symbol"]: r["status"] for r in self.run_script(H, "list")["stocks"]}
        self.assertEqual(st["DLTA"], "compliant")                       # debt 40% passes a 45% limit
        self.assertEqual(self.run_script(H, "list")["banner"], banner)
        self.assertEqual(self.run_script(H, "check", "DLTA")["banner"], banner)
        self.assertTrue(self.run_script(H, "list", as_json=False).startswith(banner))
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.assertEqual(list(out)[0], "banner")
        self.assertEqual(out["banner"], banner)
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertTrue(md.startswith(banner + "\n"))
        saved = self.read(os.path.join("daily", "2026-10-30.json"))
        self.assertEqual(list(saved)[0], "banner")
        # the list was built loosened: the banner stays until it is rebuilt, even if the config is reset
        self.write("config.json", {})
        self.assertIn("rebuild it", self.run_script(H, "list")["banner"])
        self.build_universe()
        self.assertIsNone(self.run_script(H, "list")["banner"])

    def test_allow_review_with_note(self):
        self.build_universe()
        self.write("config.json", {"halal": {"allow_review": True, "loosen_note": "my scholar"}})
        self.assertTrue(V({"halal": {"allow_review": True, "loosen_note": "my scholar"}})[0]["_halal_loosened"])
        self.assertTrue(self.run_script(DAILY, "--no-news", "--no-rebuild")["banner"].endswith("my scholar"))

    def test_no_banner_by_default(self):
        self.build_universe()
        for args in (("list",), ("list", "--status", "compliant"), ("check", "ALFA,ITC")):
            got = self.run_script(H, *args)
            self.assertEqual(list(got), ["banner", "stocks"], args)           # always the same shape
            self.assertIsNone(got["banner"])
            self.assertIsInstance(got["stocks"], list)
        self.assertEqual(len(self.run_script(H, "check", "ALFA,ITC")["stocks"]), 2)
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.assertNotIn("banner", out)


class Why(OfflineCase):
    def daily(self, *args):
        self.build_universe()
        return self.run_script(DAILY, *args)

    def test_every_row_has_every_group(self):
        out = self.daily("--no-news")
        self.assertTrue(out["rows"])
        for r in out["rows"]:
            groups = [w["group"] for w in r["why"]]
            self.assertEqual(sorted(set(groups), key=tc.WHY_GROUPS.index), list(tc.WHY_GROUPS), r["symbol"])
            self.assertEqual(groups, sorted(groups, key=tc.WHY_GROUPS.index))           # in group order
            for w in r["why"]:
                base = {"group", "check", "value", "limit", "op", "ok", "unit", "note"}
                self.assertTrue(base <= set(w) <= base | {"near_limit", "over_limit", "stop_capped"}, w)   # v0.1.7 flags
                self.assertIn(w["ok"], (True, False, None))
                if w["value"] is None:
                    self.assertIsNone(w["ok"], w)

    def test_missing_news_is_unknown_not_zero(self):
        out = self.daily("--no-news")                                 # fresh folder: no news.json at all
        for r in out["rows"]:
            news = [w for w in r["why"] if w["group"] == "NEWS"]
            self.assertTrue(news)
            for w in news:
                self.assertIsNone(w["ok"])
                self.assertIsNone(w["value"])
                self.assertIn("UNKNOWN", w["note"])

    def test_news_items_when_fetched(self):
        out = self.daily()
        alfa = [r for r in out["rows"] if r["symbol"] == "ALFA"][0]
        news = [w for w in alfa["why"] if w["group"] == "NEWS"]
        # v0.1.10: two lines, Media news and Exchange filings (NSE); a flagged headline is ok=False
        self.assertTrue(all(w["check"] in (tc.NEWS_MEDIA, tc.NEWS_FILINGS) for w in news))
        self.assertTrue(any(w["ok"] is False and "HALAL-WATCH" in w["note"] for w in news))
        res = [w for w in news if w["ok"] is False and "results news in the window" in w["note"]]
        self.assertTrue(res)                                               # the same headline as the WARN
        self.assertTrue(any("results news in the window" in x for x in alfa["reasons"]))
        self.assertFalse(any("due date" in w["check"] for w in news))
        chrl = [r for r in out["rows"] if r["symbol"] == "CHRL"][0]
        cn = {w["check"]: w for w in chrl["why"] if w["group"] == "NEWS"}
        self.assertEqual((cn[tc.NEWS_MEDIA]["value"], cn[tc.NEWS_MEDIA]["ok"]), ("none flagged", True))
        self.assertIn("72 hours", cn[tc.NEWS_MEDIA]["note"])

    def test_news_source_failed_is_unknown(self):
        import check
        news = {"asof": "2026-10-30T18:00", "hours": 72, "symbols": {"CHRL": []},
                "errors": ["nse CHRL: HTTP 403", "moneycontrol_markets: timeout"]}
        w = {x["check"]: x for x in check.news_why("CHRL", news, "2026-10-30")}
        self.assertIsNone(w[tc.NEWS_FILINGS]["ok"])                    # NSE refused: not available, never a pass
        self.assertEqual(w[tc.NEWS_FILINGS]["value"], tc.NOT_AVAILABLE)
        self.assertIn("NSE refused automated access", w[tc.NEWS_FILINGS]["note"])
        news["errors"] = ["nse CHRL: https://www.nseindia.com/api/x -> HTTP 503"]   # a real failure: UNKNOWN
        w = {x["check"]: x for x in check.news_why("CHRL", news, "2026-10-30")}
        self.assertIsNone(w[tc.NEWS_FILINGS]["ok"])
        self.assertIsNone(w[tc.NEWS_FILINGS]["value"])
        self.assertTrue(w[tc.NEWS_FILINGS]["note"].startswith("UNKNOWN: NSE announcements failed"))
        news["errors"] = ["google CHRL: timed out"]                     # Google News failed: media UNKNOWN
        w = {x["check"]: x for x in check.news_why("CHRL", news, "2026-10-30")}
        self.assertIsNone(w[tc.NEWS_MEDIA]["ok"])
        self.assertIn("UNKNOWN", w[tc.NEWS_MEDIA]["note"])
        news["errors"] = ["moneycontrol_markets: timeout"]               # a general feed only: still checked
        w = {x["check"]: x for x in check.news_why("CHRL", news, "2026-10-30")}
        self.assertIs(w[tc.NEWS_MEDIA]["ok"], True)
        self.assertIs(w[tc.NEWS_FILINGS]["ok"], True)

    def test_values_equal_those_used(self):
        out = self.daily("--no-news")
        uni = self.read("halal_universe.json")
        plans = self.read("plan.json")["plans"]
        orders = {o["id"]: o for o in self.read("orders.json")["orders"]}
        cfg = V({})[0]
        for r in out["rows"]:
            w = {(x["group"], x["check"]): x for x in r["why"]}
            o = orders[r["order_id"]]
            self.assertEqual(w[("RISK", "loss at the stop incl. charges")]["value"], r["loss_at_stop_rs"])
            self.assertEqual(w[("RISK", "loss at the stop incl. charges")]["limit"], 1000.0)
            self.assertEqual(w[("RISK", "position size")]["value"], o["qty"] * o["trigger_price"])
            self.assertEqual(w[("PLAN", "net reward:risk after charges")]["value"], r["rr_net"])
            self.assertEqual(w[("PLAN", "net reward:risk after charges")]["limit"], cfg["min_reward_risk"])
            pl = plans[r["symbol"]]
            self.assertAlmostEqual(w[("PLAN", "stop distance under the entry")]["value"],
                                   (pl["entry"] - pl["stop"]) / pl["entry"] * 100, places=9)
            self.assertEqual(round(w[("PLAN", "stop distance under the entry")]["value"], 1), r["stop_pct"])
            self.assertEqual(w[("PLAN", "stop distance under the entry")]["limit"],
                             cfg["modes"][r["mode"]]["max_stop_pct"])
            self.assertEqual(w[("HISTORY", "time-machine expectancy after charges")]["value"], r["expectancy_r"])
            self.assertEqual(w[("HISTORY", "past trades of this setup on this stock")]["value"], r["past_trades"])
            ratios = uni["stocks"][r["symbol"]]["ratios"]
            self.assertEqual(w[("HALAL", "debt / total assets")]["value"], ratios["debt_to_assets_pct"])
            self.assertEqual(w[("HALAL", "debt / total assets")]["limit"], 25.0)
            self.assertEqual(w[("HALAL", "reported interest / total income")]["value"], ratios["interest_income_pct"])
            self.assertEqual(w[("HALAL", "non-compliant income (reported + assumed return)")]["value"],
                             ratios["noncompliant_income_pct"])
            self.assertEqual(w[("RISK", "result")]["value"], r["risk"])
            bars, _ = tc.get_daily_bars(r["symbol"])
            liq = [x for x in r["why"] if x["group"] == "LIQUIDITY"]
            vol20 = sum(b["volume"] for b in bars[-20:]) / 20.0
            self.assertAlmostEqual(liq[1]["value"], vol20 * bars[-1]["close"], delta=1e-3)
            self.assertEqual(liq[0]["value"], bars[-1]["close"])
            if r["setup"] == "trend":
                c, h52 = bars[-1]["close"], max(b["high"] for b in bars[-252:])
                self.assertAlmostEqual(w[("SETUP", "close as % of the 252-day high")]["value"], c / h52 * 100, places=9)
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertIn("  - Why:", md)
        self.assertIn("    - HALAL:", md)
        self.assertIn("    - NEWS:", md)
        self.assertIn("UNKNOWN", md)

    def test_missing_ratio_is_none(self):
        rec = {"status": "compliant", "ratios": {"interest_income_pct": 1.0, "noncompliant_income_pct": 1.0,
                                                 "assumed_return_pct": 0.0}, "as_of": None}
        w = {x["check"]: x for x in tc.halal_why(rec, {"thresholds": tc.TASIS_HALAL})}
        self.assertIsNone(w["debt / total assets"]["value"])
        self.assertIsNone(w["debt / total assets"]["ok"])
        self.assertIsNone(w["cash + receivables / total assets"]["ok"])
        self.assertIs(w["reported interest / total income"]["ok"], True)
        self.assertIsNone(w["figures as of"]["ok"])
        fs = tc.financial_screen({"TotalAssets": [("2026-03-31", 100.0)], "TotalRevenue": [("2026-03-31", 100.0)]},
                                 tc.DEFAULT_CONFIG)
        debt = [x for x in fs["why"] if x["check"] == "debt / total assets"][0]
        self.assertEqual((debt["value"], debt["ok"]), (None, None))
        self.assertIn("UNKNOWN", debt["note"])
        none = tc.halal_why({"status": "compliant", "source": "official list: x.csv"}, {})
        self.assertTrue(any(x["check"] == "financial ratios" and x["ok"] is None for x in none))

    def test_override_shown(self):
        self.build_universe()
        self.run_script(H, "override", "ALFA", "--status", "compliant", "--note", "annual report FY26",
                        as_json=False)
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        alfa = [r for r in out["rows"] if r["symbol"] == "ALFA"][0]
        ov = [w for w in alfa["why"] if w["check"] == "your override"][0]
        self.assertEqual(ov["value"], "compliant")
        self.assertIn("annual report FY26", ov["note"])

    def test_filtered_and_not_sized_rows_have_every_group(self):
        self.build_universe()
        self.write("config.json", {"daily": {"min_expectancy_r": 2}})
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.assertTrue(out["rows"])
        for r in out["rows"]:
            groups = {w["group"] for w in r["why"]}
            self.assertEqual(groups, set(tc.WHY_GROUPS))
            if r["risk"] == "FILTERED":
                self.assertIsNone(r["order_id"])
                h = [w for w in r["why"] if w["group"] == "HISTORY"][0]
                self.assertEqual((h["limit"], h["ok"]), (2, False))


class DailyConfig(OfflineCase):
    def test_top_and_picks_from_config_and_flags(self):
        self.build_universe()
        self.write("config.json", {"daily": {"top": 1, "picks": 0}})
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["top_picks"], [])
        self.assertEqual(out["settings"]["values"]["daily"]["top"], 1)
        out = self.run_script(DAILY, "--no-news", "--no-rebuild", "--top", "2", "--picks", "3")
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["settings"]["values"]["daily"]["top"], 2)

    def test_min_expectancy_filter(self):
        self.build_universe()
        base = self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.write("config.json", {"daily": {"min_expectancy_r": 1.0}})
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        exp = {r["symbol"]: r["expectancy_r"] for r in base["rows"]}
        for r in out["rows"]:
            self.assertEqual(r["risk"] == "FILTERED", exp[r["symbol"]] < 1.0, r["symbol"])
        self.assertTrue(any(r["risk"] == "FILTERED" for r in out["rows"]))
        self.assertTrue(any(r["risk"] != "FILTERED" for r in out["rows"]))
        sized = {o["symbol"] for o in self.read("orders.json")["orders"]}
        self.assertEqual(sized, {r["symbol"] for r in out["rows"] if r["risk"] != "FILTERED"})
        self.assertTrue(any("min_expectancy_r" in n for n in out["notes"]))

    def test_config_notes_in_daily(self):
        self.build_universe()
        self.write("config.json", {"max_position_pct": 50, "allow_short": True})
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        self.assertIn("CONFIG: max_position_pct = 50 invalid (range 5–40), using default 20", out["notes"])
        self.assertTrue(any(n.startswith("CONFIG: unknown key allow_short ignored") for n in out["notes"]))
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertIn("Note: CONFIG: max_position_pct = 50 invalid", md)
        p = self.run_script(SC, ok=False)                              # other scripts: on stderr, never stdout
        self.assertIn("CONFIG: max_position_pct", p.stderr)
        self.assertEqual(json.loads(p.stdout)["config_notes"][0][:30], "CONFIG: max_position_pct = 50 "[:30])


class Settings(OfflineCase):
    def test_hash_stable_across_key_order(self):
        a = V({"capital": 200000, "halal": {"auto_rebuild_days": 20, "list_max_age_days": 90}})[0]
        b = V(json.loads('{"halal": {"list_max_age_days": 90, "auto_rebuild_days": 20}, "capital": 200000}'))[0]
        self.assertEqual(tc.settings_snapshot(a)["hash"], tc.settings_snapshot(b)["hash"])
        self.assertEqual(len(tc.settings_snapshot(a)["hash"]), 8)

    def test_default_label(self):
        d = tc.settings_snapshot(V({})[0])
        self.assertEqual(tc.DEFAULTS_VERSION, 2)
        self.assertEqual(d["label"], "default@2")
        self.assertEqual((d["differs_from_default"], d["defaults_version"]), ([], 2))
        # setting a value to its default is still the defaults
        self.assertEqual(tc.settings_snapshot(V({"max_risk_per_trade_pct": 1.0, "broker": "zerodha"})[0])["label"],
                         "default@2")

    def test_hash_is_the_differences_and_the_defaults_version(self):
        import hashlib
        d = tc.settings_snapshot(V({})[0])
        c = tc.settings_snapshot(V({"max_risk_per_trade_pct": 0.5})[0])
        self.assertNotEqual(c["hash"], d["hash"])
        self.assertEqual(c["label"], c["hash"])
        self.assertEqual(c["differs_from_default"], [{"key": "max_risk_per_trade_pct", "value": 0.5, "default": 1.0}])
        canon = json.dumps({"defaults_version": 2, "differs": [["max_risk_per_trade_pct", 0.5]]},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(c["hash"], hashlib.sha1(canon.encode("utf-8")).hexdigest()[:8])
        s = tc.settings_snapshot(V({"scanner": {"setups": {"trend": {"enabled": False}}}})[0])
        self.assertNotEqual(s["hash"], d["hash"])
        self.assertEqual(tc.settings_snapshot(V({"user_agent": "me"})[0])["hash"], d["hash"])   # no decision
        self.assertEqual(tc.settings_snapshot(V({"halal": {"loosen_note": "my scholar"}})[0])["hash"], d["hash"])
        # data sources change which stocks and headlines reach the decisions
        u = tc.settings_snapshot(V({"halal": {"parent_list_url": "https://example.org/nifty200.csv"}})[0])
        self.assertEqual([x["key"] for x in u["differs_from_default"]], ["halal.parent_list_url"])
        f = tc.settings_snapshot(V({"news": {"feeds": {"et_markets": "https://example.org/et.xml"}}})[0])
        self.assertNotEqual(f["hash"], d["hash"])
        self.assertIn("news.feeds.et_markets", [x["key"] for x in f["differs_from_default"]])
        # every documented key is in the snapshot except the three display/transport ones
        snap = set(tc.default_values())
        missing = sorted(k for k in tc.DEFAULT_CONFIG_DOCS if k not in snap and not any(
            s.startswith(k + ".") for s in snap))
        self.assertEqual(missing, sorted(tc.SETTINGS_EXCLUDE))
        # the capital only counts when it differs from the default, like any other key
        self.assertNotEqual(tc.settings_snapshot(V({"capital": 200000})[0])["hash"], d["hash"])

    def test_new_key_with_a_preserving_default_keeps_the_hash(self):
        before = (tc.settings_snapshot(V({})[0])["hash"], tc.settings_snapshot(V({"max_open_positions": 4})[0])["hash"])
        saved = copy.deepcopy(tc.DEFAULT_CONFIG)
        tc.DEFAULT_CONFIG["scanner"]["setups"]["breakout"]["future_filter_pct"] = 0.0
        tc.DEFAULT_CONFIG["future_block"] = {"enabled": False}
        tc.DEFAULT_CONFIG_DOCS["scanner.setups.breakout.future_filter_pct"] = tc._doc("x", 0, 5, "%")
        tc.DEFAULT_CONFIG_DOCS["future_block.enabled"] = tc._doc("x", type="bool")
        try:
            after = (tc.settings_snapshot(V({})[0])["hash"], tc.settings_snapshot(V({"max_open_positions": 4})[0])["hash"])
            self.assertEqual(after, before)
            self.assertEqual(tc.settings_snapshot(V({})[0])["label"], "default@2")
        finally:
            tc.DEFAULT_CONFIG.clear()
            tc.DEFAULT_CONFIG.update(saved)
            del tc.DEFAULT_CONFIG_DOCS["scanner.setups.breakout.future_filter_pct"]
            del tc.DEFAULT_CONFIG_DOCS["future_block.enabled"]

    def test_defaults_version_bumped_when_a_default_changes(self):
        """tests/fixtures/defaults_versions.json holds the defaults of every DEFAULTS_VERSION. If this
        fails, a default changed: bump DEFAULTS_VERSION in core, then `py tests/baseline.py --defaults`."""
        hist = baseline.load_defaults()
        v = str(tc.DEFAULTS_VERSION)
        self.assertEqual(max(int(k) for k in hist), tc.DEFAULTS_VERSION,
                         "DEFAULTS_VERSION is not the newest recorded: run py tests/baseline.py --defaults")
        cur = tc.default_values()
        changed = sorted(k for k, x in hist[v].items() if k not in cur or cur[k] != x)
        self.assertEqual(changed, [], "defaults changed without a DEFAULTS_VERSION bump: %s" % changed)
        # the check itself catches a change
        fake = dict(cur, **{"max_position_pct": 25.0})
        self.assertEqual(sorted(k for k, x in hist[v].items() if fake.get(k) != x), ["max_position_pct"])

    def test_legacy_default_hash_counts_as_default(self):
        import hashlib
        import tracker
        snap = tc.settings_snapshot(V({})[0])
        # the all-defaults hash of v0.1.5 / v0.1.6 (DEFAULTS_VERSION 1), as the live tracker.json has it
        v1 = hashlib.sha1(json.dumps({"defaults_version": 1, "differs": []}, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()[:8]
        self.assertNotEqual(v1, snap["hash"])
        store = {"rows": [{"settings_hash": "cf8b2136", "status": "WAITING"},
                          {"settings_hash": v1, "status": "WAITING"},
                          {"settings_hash": snap["hash"], "status": "WAITING"},
                          {"status": "WAITING"}],
                 "settings": {"cf8b2136": {"first_seen": "2026-11-05", "differs_from_default": []},   # no label
                              v1: {"label": "default@1", "first_seen": "2026-11-05", "differs_from_default": []},
                              snap["hash"]: {"label": snap["label"], "first_seen": "2026-11-06",
                                             "differs_from_default": []}}}
        for r in store["rows"]:
            r.setdefault("settings_hash", tracker.PRE)
        summ = tracker.summary(store["rows"], store)
        self.assertEqual(summ["settings: default@1"]["listed"], 2)
        self.assertEqual(summ["settings: default@2"]["listed"], 1)      # v0.1.7 defaults: a separate group
        self.assertEqual(summ["settings: pre-0.1.5"]["listed"], 1)
        split = tracker.settings_split(store)
        self.assertEqual(split["default@1"]["hashes"], sorted(["cf8b2136", v1]))
        self.assertEqual(split["default@2"]["hashes"], [snap["hash"]])
        self.assertIn("all defaults (defaults version 1)", split["default@1"]["differs"])
        self.assertIn("all defaults (defaults version 2)", split["default@2"]["differs"])
        self.assertEqual(split["default@1"]["first_seen"], "2026-11-05")
        self.assertEqual(store["rows"][0]["settings_hash"], "cf8b2136")          # the row keeps its hash

    def test_tracker_records_and_splits(self):
        self.build_universe()
        old = [{"date": "2026-10-01", "symbol": "OLDX", "name": "", "mode": "swing", "setup": "breakout",
                "check": "PASS", "entry": 100, "stop": 95, "target": 110, "qty": 1, "valid_until": "2026-10-06",
                "max_hold_days": 20, "status": "TARGET", "filled": "2026-10-02", "r": 1.8}]
        self.write("tracker.json", {"rows": old})
        out = self.run_script(DAILY, "--no-news", "--no-rebuild")
        h = out["settings"]["hash"]
        self.assertEqual(out["settings"]["label"], "default@2")
        t = self.read("tracker.json")
        hashes = {r["symbol"]: r["settings_hash"] for r in t["rows"]}
        self.assertEqual(hashes.pop("OLDX"), "pre-0.1.5")
        self.assertEqual(set(hashes.values()), {h})
        self.assertIn("settings: default@2", t["summary"])
        self.assertIn("settings: pre-0.1.5", t["summary"])
        self.assertEqual(t["summary"]["settings: pre-0.1.5"]["target"], 1)
        self.assertIn("all defaults", t["settings_split"]["default@2"]["differs"])
        self.assertIn("before v0.1.5", t["settings_split"]["pre-0.1.5"]["differs"])
        with zipfile.ZipFile(os.path.join(self.dir, "tracker.xlsx")) as z:
            summ = z.read("xl/worksheets/sheet2.xml").decode()
        self.assertIn("settings: pre-0.1.5", summ)
        self.assertIn("settings: default@2", summ)
        self.assertIn("all defaults", summ)
        self.assertIn("Settings vs defaults", summ)
        # a second settings set, the same day: the unfilled default@2 rows are SUPERSEDED (v0.1.8)
        self.write("config.json", {"max_risk_per_trade_pct": 0.5})
        out2 = self.run_script(DAILY, "--no-news", "--no-rebuild", "--mode", "swing")
        h2 = out2["settings"]["hash"]
        self.assertNotEqual(h2, h)
        rows = self.read("tracker.json")["rows"]
        first = [r for r in rows if r["settings_hash"] == h]
        self.assertTrue(first)
        self.assertTrue(all(r["status"] == "SUPERSEDED" for r in first if not r.get("filled")))
        rep = self.run_script(TR, "report")
        split = rep["settings_split"]
        self.assertEqual(set(split), {h2, "pre-0.1.5"})
        self.assertIn("max_risk_per_trade_pct 0.5 (default 1)", split[h2]["differs"])
        txt = self.run_script(TR, "report", as_json=False)
        self.assertIn("By settings:", txt)
        self.assertIn(h2, txt)


class Encoding(OfflineCase):
    """2026-11-05 live run: a headline with a rupee sign crashed check.py when its stdout was a pipe
    in cp1252 (Windows), and tayyib-daily decoded the children's output as cp1252. Forced here on
    every OS with PYTHONIOENCODING=cp1252."""

    def test_rupee_headline_through_a_cp1252_pipe(self):
        self.build_universe()
        self.run_script(DAILY, "--no-news", "--no-rebuild", "--mode", "swing")
        sym = self.read("orders.json")["orders"][0]["symbol"]
        title = "%s Q2 results: profit jumps 32.5%% to \u20b91,124 crore" % sym
        news = {"asof": "2026-10-30T18:00", "hours": 72, "errors": [], "market": [],
                "symbols": {sym: [{"title": title, "link": "", "published": "2026-10-30T09:00:00+05:30",
                                   "source": "test", "summary": "", "tags": ["results"], "halal_watch": []}]}}
        with open(os.path.join(self.dir, "news.json"), "w", encoding="utf-8") as f:
            json.dump(news, f, ensure_ascii=False)
        saved = dict(os.environ)
        os.environ.update(PYTHONIOENCODING="cp1252", TAYYIB_FIXTURES=baseline.FIX, TAYYIB_NOW=baseline.NOW)
        try:
            out = self.run_script(RI)                                  # check.py --json, cp1252 asked for
            mine = [r for r in out if r["symbol"] == sym][0]
            self.assertTrue(any("\u20b9" in w for w in mine["warn"]), mine["warn"])
            sys.path.insert(0, os.path.join(ROOT, "tayyib-daily"))
            import daily
            got = daily.run("tayyib-risk", "check.py")                # how tayyib-daily reads it
            self.assertTrue(any("\u20b91,124" in w for r in got for w in r["warn"]))
        finally:
            os.environ.clear()
            os.environ.update(saved)


class RiskPreview(OfflineCase):
    def test_arithmetic(self):
        rp = tc.risk_preview(V({})[0])
        self.assertEqual(rp["risk_per_trade_rs"], 1000.0)
        dd = {x["losses"]: x for x in rp["losing_streaks"]}
        self.assertEqual(dd[3]["drawdown_pct"], round((1 - 0.99 ** 3) * 100, 2))        # 2.97
        self.assertEqual(dd[5]["drawdown_pct"], 4.9)
        self.assertEqual(dd[10]["drawdown_pct"], 9.56)
        self.assertEqual(dd[10]["capital_left_rs"], round(100000 * 0.99 ** 10, 2))
        self.assertEqual(rp["binding_stop_pct"], 5.0)                                  # 1% / 20%
        s = {x["stop_pct"]: x for x in rp["samples"]}
        self.assertEqual((s[2.0]["qty"], s[2.0]["binding"]), (20, "position"))       # 2% stop: Rs 20,000 cap
        self.assertEqual(s[2.0]["loss_at_stop_rs"], 400.0)
        self.assertEqual((s[10.0]["qty"], s[10.0]["binding"]), (10, "risk"))         # 10% stop: Rs 1,000 / Rs 100
        self.assertEqual(s[10.0]["loss_at_stop_rs"], 1000.0)
        self.assertEqual(s[5.0]["binding"], "both")

    def test_rupee_cap_and_other_settings(self):
        rp = tc.risk_preview(V({"capital": 500000, "max_risk_per_trade_pct": 2, "max_risk_per_trade_rs": 5000,
                                "max_position_pct": 10})[0], stops_pct=(4,), entry=250)
        self.assertEqual(rp["risk_per_trade_rs"], 5000.0)
        self.assertEqual(rp["effective_risk_pct"], 1.0)
        self.assertEqual(rp["binding_stop_pct"], 10.0)
        x = rp["samples"][0]
        self.assertEqual((x["qty_by_risk"], x["qty_by_position"], x["qty"], x["binding"]), (500, 200, 200, "position"))

    def test_flag(self):
        rp = self.run_script(DAILY, "--risk-preview", "--stop-pct", "4")
        self.assertEqual([x["stop_pct"] for x in rp["samples"]], [4.0])
        self.assertEqual(rp["losing_streaks"][0]["losses"], 3)
        txt = self.run_script(DAILY, "--risk-preview", as_json=False)
        self.assertIn("10 losses", txt)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "daily")))           # ran nothing else


if __name__ == "__main__":
    unittest.main()
