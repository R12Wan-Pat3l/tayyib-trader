"""v0.2.4: held-stock halal alerts (tayyib-halal held), the market-regime filter (OFF by default; live and in the
backtest, causal; --regime-compare), and three fixes: Why ordering, the time-machine label and the market-closed
check. Offline: fixtures only, the clock fixed at 2026-10-30 18:00 IST (a Friday). Nothing is placed anywhere."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _util import FIX, NOW, ROOT, OfflineCase, tc
from test_v018 import ServerCase

for d in ("tayyib-backtest", "tayyib-daily", "tayyib-email", "tayyib-dashboard"):
    sys.path.insert(0, os.path.join(ROOT, d))
import backtest as bt  # noqa: E402
import daily as DAILY  # noqa: E402
import email_report as ER  # noqa: E402
import dashboard as DASH  # noqa: E402

HALAL = "tayyib-halal/halal.py"
DAY = tc.parse_date("2026-10-30")


def position(sym, qty=10, pid=None, opened="2026-10-01", at_buy="compliant", ratios=None):
    p = {"id": pid or sym + "-2026-10-01-trend", "symbol": sym, "mode": "delivery", "setup": "trend", "qty": qty,
         "entry": 100.0, "stop": 90.0, "initial_stop": 90.0, "target": 130.0, "opened": opened, "status": "open",
         "buy_charges_rs": 12.0, "product": "CNC"}
    if at_buy:
        p["halal_at_buy"] = {"status": at_buy, "ratios": ratios or {"debt_to_assets_pct": 10.0}, "as_of": "2025-03-31",
                             "date": opened, "source": "halal list built 2026-10-01", "backfilled": False}
    return p


def index_fixture(fixdir, closes):
    """chart/^NSEI.json from a fixture chart's timestamps with these closes (oldest first, same length)."""
    src = json.load(open(os.path.join(FIX, "chart", "CHRL.json")))
    r = src["chart"]["result"][0]
    n = len(r["timestamp"])
    cl = list(closes)[-n:]
    q = r["indicators"]["quote"][0]
    for k in ("open", "high", "low", "close"):
        q[k] = list(cl)
    q["volume"] = [0] * n
    if "adjclose" in r["indicators"]:
        r["indicators"]["adjclose"] = [{"adjclose": list(cl)}]
    with open(os.path.join(fixdir, "chart", "^NSEI.json"), "w") as f:
        json.dump(src, f)


class Held(OfflineCase):
    def setUp(self):
        super().setUp()
        self.build_universe()

    def uni_age(self, updated="2026-10-01"):
        u = self.read("halal_universe.json")
        u["updated"] = updated
        self.write("halal_universe.json", u)

    def held(self, *extra):
        return self.run_script(HALAL, "held", *extra)

    def test_turning_non_compliant_one_alert_ticket_purify(self):
        self.uni_age()                                         # older than held_recheck_days: re-screened live
        self.write("positions.json", {"positions": [position("ECHO")]})
        self.write("purification.json", {"dividends": [{"symbol": "ECHO", "amount_rs": 200.0, "date": "2026-10-10",
                                                        "ratio_pct": None}]})
        out = self.held("--write")
        x = out["alerts"][0]
        self.assertEqual((x["symbol"], x["level"], x["title"]), ("ECHO", "BLOCK", "No longer compliant"))
        self.assertTrue(x["rechecked"])
        self.assertEqual((x["status_at_buy"], x["status_now"]), ("compliant", "review"))
        self.assertTrue(x["alert"]["new"])
        self.assertTrue(x["failed"])                           # which test failed
        self.assertTrue(x["data_date"] and x["source"].startswith("re-screened"))
        self.assertTrue(any(r["new"] is not None for r in x["ratios"]))
        t = x["sell_ticket"]
        self.assertEqual((t["side"], t["product"], t["qty"], t["manual"]), ("SELL", "CNC", 10, True))
        self.assertEqual(tc.guard_order(t, {"ECHO": 10}), [])
        self.assertIn("ticket.py close ECHO-2026-10-01-trend --price <your fill> --reason halal", t["steps"][-1])
        self.assertEqual(x["wording"], tc.HELD_WORDING)
        self.assertEqual(x["sell_by"], "as soon as reasonable")
        p = x["purify"]
        self.assertEqual(p["label"], "estimate: confirm with your scholar")
        self.assertEqual(p["dividends"], 1)
        self.assertEqual(p["command"], "purify.py estimate ECHO --since 2026-10-30")
        al = [a for a in self.read("alerts.json")["alerts"] if a["kind"] == "halal"]
        self.assertEqual(len(al), 1)
        # the next run: the same status, no new alert, shown as open
        again = self.held("--write")["alerts"][0]
        self.assertFalse(again["alert"]["new"])
        self.assertTrue(again["alert"]["open"])
        self.assertEqual(len([a for a in self.read("alerts.json")["alerts"] if a["kind"] == "halal"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "orders.json")))     # never a buy ticket

    def test_resolved_after_close(self):
        self.write("positions.json", {"positions": [position("ECHO")]})
        self.held("--write")
        self.run_script("tayyib-broker/ticket.py", "close", "ECHO-2026-10-01-trend", "--price", "101", "--reason", "halal")
        z = [a for a in self.read("alerts.json")["alerts"] if a["kind"] == "halal"][0]
        self.assertEqual(z["status"], "resolved")
        self.assertIn("you sold it", z["resolution"])
        self.assertEqual(self.read("held_halal.json")["view"]["alerts"], [])
        self.assertEqual(self.held("--write")["alerts"], [])
        self.assertEqual(DASH.held_alerts_now(), [])

    def test_near_limit_is_warn(self):
        u = self.read("halal_universe.json")
        u["stocks"]["ALFA"]["ratios"]["debt_to_assets_pct"] = 24.0       # 96% of the 25% limit, still under it
        self.write("halal_universe.json", u)
        self.write("positions.json", {"positions": [position("ALFA")]})
        x = self.held()["alerts"][0]
        self.assertEqual((x["level"], x["title"], x["status_now"]), ("WARN", "Near a limit", "compliant"))
        self.assertNotIn("sell_ticket", x)
        self.assertEqual(x["near"], ["debt_to_assets_pct"])

    def test_screen_failure_could_not_verify(self):
        self.uni_age()
        self.write("positions.json", {"positions": [position("GOLF")]})       # no fundamentals fixture: fails
        x = self.held("--write")["alerts"][0]
        self.assertEqual((x["level"], x["title"], x["status_now"]), ("UNKNOWN", "Could not verify", "UNKNOWN"))
        self.assertIn("financials unavailable", x["reason"])
        self.assertNotIn("sell_ticket", x)                     # never read as non-compliant...
        self.assertIsNone(self.read("held_halal.json")["symbols"]["GOLF"].get("last_status"))   # ...nor compliant

    def test_overrides_win(self):
        self.uni_age()
        self.write("positions.json", {"positions": [position("ECHO"), position("ALFA")]})
        self.write("halal_overrides.json", {"ECHO": {"status": "compliant", "note": "my scholar", "date": "2026-10-20"},
                                            "ALFA": {"status": "excluded", "note": "my scholar", "date": "2026-10-20"}})
        out = self.held()
        lv = {x["symbol"]: x["level"] for x in out["held"]}
        self.assertEqual(lv, {"ALFA": "BLOCK", "ECHO": None})
        self.assertIn("override", [x for x in out["held"] if x["symbol"] == "ALFA"][0]["source"])

    def test_backfill_and_no_write_without_flag(self):
        self.write("positions.json", {"positions": [position("ALFA", at_buy=None)]})
        out = self.held()
        self.assertEqual(out["held"][0]["status_at_buy"], "compliant")
        self.assertTrue(out["held"][0]["backfilled"])
        self.assertNotIn("halal_at_buy", self.read("positions.json")["positions"][0])   # nothing saved
        self.held("--write")
        self.assertTrue(self.read("positions.json")["positions"][0]["halal_at_buy"]["backfilled"])

    def test_grace_days_wording_only(self):
        self.assertEqual(tc.grace_text("2026-10-30", 0), "as soon as reasonable")
        self.assertEqual(tc.grace_text("2026-10-30", 7, DAY), "by 2026-11-06 (7 days after the change; 7 days left)")

    def test_sell_ticket_never_a_short_or_a_buy(self):
        t = tc.sell_ticket("ALFA", 5, "ALFA-1", "groww", 101.0, "2026-10-30")
        self.assertEqual((t["side"], t["product"]), ("SELL", "CNC"))
        self.assertIn("Groww -> Holdings -> ALFA -> Sell -> Delivery", t["steps"][1])
        self.assertEqual(tc.guard_order(t, {"ALFA": 4})[0][:6], "SELL 5")          # more than held: refused
        src = open(os.path.join(ROOT, "tayyib-halal", "halal.py"), encoding="utf-8").read()
        for word in ("orders.json", "place_order", "kiteconnect", '"BUY"'):
            self.assertNotIn(word, src)

    def test_purify_estimate_unknown_never_zero(self):
        p = tc.purify_estimate("ALFA", 10, "2026-10-01", "2026-10-20", None, 120.0, None,
                               [{"symbol": "ALFA", "amount_rs": 50.0, "date": "2026-10-05"}])
        self.assertIsNone(p["total_rs"])
        self.assertEqual(len(p["unknown"]), 2)
        p = tc.purify_estimate("ALFA", 10, "2026-10-01", "2026-10-20", 100.0, 120.0, 2.0,
                               [{"symbol": "ALFA", "amount_rs": 50.0, "date": "2026-10-05"},
                                {"symbol": "ALFA", "amount_rs": 99.0, "date": "2026-09-05"}])    # before buying
        self.assertEqual((p["dividend_part_rs"], p["gain_part_rs"], p["total_rs"]), (1.0, 200.0, 201.0))

    def test_alerts_check_skips_and_clear_keeps_open(self):
        self.write("positions.json", {"positions": [position("ECHO")]})
        self.held("--write")
        out = self.run_script("tayyib-alerts/alerts.py", "check")
        self.assertEqual(out["rang"], [])
        self.run_script("tayyib-alerts/alerts.py", "clear", "--fired", as_json=False)
        self.assertEqual(len(self.read("alerts.json")["alerts"]), 1)


class HeldEverywhere(ServerCase):
    """The same alert at the top of the daily .md / .json, the email, the dashboard Today banner and Tickets."""

    def test_sections(self):
        self.build_universe()
        self.write("positions.json", {"positions": [position("ECHO")]})
        out = self.run_script("tayyib-daily/daily.py", "--no-news", "--runs", "200")
        self.assertEqual([x["symbol"] for x in out["held_alerts"]], ["ECHO"])
        md = open(os.path.join(self.dir, "daily", "2026-10-30.md"), encoding="utf-8").read()
        self.assertLess(md.index("No longer compliant: ECHO"), md.index("# Halal trade list"))
        self.assertIn("SELL ticket SELL-ECHO-2026-10-30", md)
        self.assertIn("estimate: confirm with your scholar", md)
        rep = ER.build(DAY, tc.load_config())
        self.assertEqual([h["symbol"] for h in rep["held_alerts"]], ["ECHO"])
        for txt in (ER.render_text(rep), ER.render_html(rep)):
            self.assertIn("no longer compliant", txt[:txt.lower().index("paper tracker")].lower())
            self.assertIn("SELL ticket SELL-ECHO-2026-10-30", txt)
            self.assertIn("Not a fatwa.", txt)
        today = self.get("/api/today")
        self.assertEqual([(h["symbol"], h["kind"]) for h in today["held_alerts"]], [("ECHO", "block")])
        tk = self.get("/api/tickets")
        h = tk["held_alerts"][0]
        self.assertEqual(sorted(h["ticket"]["steps"]), ["groww", "zerodha"])
        self.assertEqual((h["ticket"]["side"], h["ticket"]["product"]), ("SELL", "CNC"))
        self.assertIn("purify.py estimate ECHO", h["purify"]["command"])
        self.assertFalse([t for t in tk["tickets"] if t.get("symbol") == "ECHO"])    # no buy ticket for it
        # the second run: still one alert
        self.run_script("tayyib-daily/daily.py", "--no-news", "--runs", "200")
        self.assertEqual(len([a for a in self.read("alerts.json")["alerts"] if a["kind"] == "halal"]), 1)


# --- B. regime -------------------------------------------------------------------------------------------

def bars_from(closes, start="2025-01-01"):
    d0 = tc.parse_date(start)
    return [{"date": (d0 + tc.dt.timedelta(days=i)).isoformat(), "open": c, "high": c, "low": c, "close": c, "volume": 0}
            for i, c in enumerate(closes)]


class Regime(unittest.TestCase):
    def test_off_by_default_and_baseline_label(self):
        c = tc.validate_config({})[0]
        self.assertEqual(c["regime"], {"enabled": False, "index": "^NSEI", "rule": "close_below_200dma",
                                       "action": "no_new_swing"})
        snap = tc.settings_snapshot(c)
        self.assertEqual((snap["label"], snap["hash"]), ("default@2", "a28d32c9"))
        off = tc.regime_state(bars_from([300 - i * 0.5 for i in range(260)]), bars_from([0] * 260)[-1]["date"])
        self.assertEqual(off["state"], "risk-off")
        self.assertFalse(tc.regime_effect(off, c["regime"])["active"])               # off: never acts

    def test_states_and_actions(self):
        down = bars_from([300 - i * 0.5 for i in range(260)])
        up = bars_from([100 + i * 0.5 for i in range(260)])
        d = down[-1]["date"]
        self.assertEqual(tc.regime_state(up, d)["state"], "risk-on")
        st = tc.regime_state(down, d)
        self.assertEqual(st["state"], "risk-off")
        self.assertLess(st["close"], st["sma200"])
        self.assertEqual(tc.regime_state(down, d, "sma50_below_sma200")["state"], "risk-off")
        on = lambda a: tc.regime_effect(st, {"enabled": True, "action": a})
        self.assertEqual(on("no_new_swing")["block_modes"], ["swing"])
        self.assertEqual(on("no_new_trades")["block_modes"], ["swing", "delivery"])
        self.assertEqual((on("half_risk")["block_modes"], on("half_risk")["risk_factor"]), ([], 0.5))
        self.assertEqual(on("no_new_swing")["text"], "MARKET: Nifty 50 below its 200-day average → no new swing trades")

    def test_unknown_does_nothing(self):
        short = bars_from([100] * 150)
        st = tc.regime_state(short, short[-1]["date"])
        self.assertEqual(st["state"], "UNKNOWN")
        self.assertIn("needs 200", st["reason"])
        self.assertEqual(tc.regime_state(short, "2030-01-01")["state"], "UNKNOWN")   # no bar that day
        e = tc.regime_effect(st, {"enabled": True, "action": "no_new_trades"})
        self.assertEqual((e["active"], e["block_modes"], e["risk_factor"]), (False, [], 1.0))


class RegimeDaily(OfflineCase):
    """The filter live, in tayyib-daily, on a fixture index."""

    def setUp(self):
        super().setUp()
        self.fix = tempfile.mkdtemp(prefix="tayyib-fix-")
        shutil.copytree(FIX, os.path.join(self.fix, "f"))
        self.fixdir = os.path.join(self.fix, "f")

    def tearDown(self):
        shutil.rmtree(self.fix, ignore_errors=True)
        super().tearDown()

    def daily(self, fixdir=None, *args):
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=fixdir or self.fixdir, TAYYIB_NOW=NOW)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tayyib-daily", "daily.py"), "--no-news", "--runs", "200",
                            "--json"] + list(args), capture_output=True, encoding="utf-8", env=env, cwd=self.dir)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_actions(self):
        self.build_universe()
        base = self.daily()
        self.assertEqual(base["regime"]["state"], "UNKNOWN")            # no index fixture: shown, no effect
        self.assertFalse(base["regime"]["applied"])
        self.assertFalse(any("MARKET" in b for b in base["banners"]))   # off: no banner
        index_fixture(self.fixdir, [3000 - i for i in range(600)])      # falling: risk-off
        off = self.daily()
        self.assertEqual((off["regime"]["state"], off["regime"]["enabled"]), ("risk-off", False))
        self.assertEqual([r["risk"] for r in off["rows"]], [r["risk"] for r in base["rows"]])   # off: no change
        self.write("config.json", {"regime": {"enabled": True, "action": "no_new_trades"}})
        on = self.daily()
        self.assertTrue(on["rows"])
        self.assertEqual({r["risk"] for r in on["rows"]}, {"FILTERED"})
        self.assertEqual(on["rows"][0]["reason"], "FILTERED: MARKET: Nifty 50 below its 200-day average → no new trades")
        self.assertTrue(any(x["check"] == "MARKET" and x["ok"] is False for x in on["rows"][0]["why"]))
        self.write("config.json", {"regime": {"enabled": True, "action": "no_new_swing"}})
        sw = self.daily()
        self.assertTrue(all(r["risk"] == "FILTERED" for r in sw["rows"] if r["mode"] == "swing"))
        self.assertFalse(any(r["risk"] == "FILTERED" for r in sw["rows"] if r["mode"] == "delivery"))
        self.write("config.json", {"regime": {"enabled": True, "action": "half_risk"}})
        hr = self.daily()
        q0 = {r["symbol"]: r["loss_at_stop_rs"] for r in base["rows"] if r.get("loss_at_stop_rs")}
        q1 = {r["symbol"]: r["loss_at_stop_rs"] for r in hr["rows"] if r.get("loss_at_stop_rs")}
        self.assertTrue(q1)
        for s in q1:
            if s in q0:
                self.assertLessEqual(q1[s], 100000 * 0.01 * 0.5)          # half the 1% budget

    def test_index_failure_unknown_and_no_effect(self):
        self.build_universe()
        base = self.daily()
        self.write("config.json", {"regime": {"enabled": True, "action": "no_new_trades"}})
        on = self.daily()                                            # no index fixture: UNKNOWN
        self.assertEqual(on["regime"]["state"], "UNKNOWN")
        self.assertTrue(any(b.startswith("Market regime UNKNOWN today") for b in on["banners"]))
        strip = lambda rows: [(r["symbol"], r["risk"], r["qty"]) for r in rows]
        self.assertEqual(strip(on["rows"]), strip(base["rows"]))


class RegimeBacktest(OfflineCase):
    def setUp(self):
        super().setUp()
        self.build_universe()
        self.loader = lambda *a, **k: bt.load_bars(*a, sleep=0, **k)

    def test_causal(self):
        data, _, _ = self.loader(sorted(bt.halal_universe(tc.load_universe())[0]), "2y", "2025-10-30", "2026-10-30")
        days = sorted({b["date"] for bs in data.values() for b in bs if "2025-10-30" <= b["date"] <= "2026-10-30"})
        idx = [{"date": d, "close": 1000 + 300 * ((k // 40) % 2) - k * 0.3} for k, d in
               enumerate(sorted({b["date"] for bs in data.values() for b in bs}))]
        cut = days[len(days) // 2]
        idx2 = [dict(b, close=b["close"] * (3 if b["date"] > cut else 1)) for b in idx]
        s1, s2 = bt.regime_states(idx, days, "close_below_200dma", "^NSEI"), bt.regime_states(idx2, days, "close_below_200dma", "^NSEI")
        self.assertEqual([s1[d] for d in days if d <= cut], [s2[d] for d in days if d <= cut])
        self.assertTrue(any(s1[d]["state"] == "risk-off" for d in days))
        cfg = tc.load_config()
        sims = [bt.simulate(data, cfg, "2025-10-30", "2026-10-30", uni=tc.load_universe(),
                            regime={"rule": "close_below_200dma", "action": "no_new_trades", "states": s})
                for s in (s1, s2)]
        early = lambda sim: [t for t in sim["trades"] if t["signal_date"] <= cut]
        self.assertEqual(early(sims[0]), early(sims[1]))
        self.assertGreater(sims[0]["counts"]["regime_risk_off_days"], 0)

    def test_compare_deterministic_and_off_is_the_plain_run(self):
        p = {"mode": "all", "setups": None, "from": "2025-10-30", "to": "2026-10-30", "split": "2026-06-30",
             "max_positions": 5, "top": 10, "warmup_bars": 250, "tm_runs": 3000, "tm_seed": 7, "take_warn": True,
             "compare": False, "late": True, "end_rule": "--to 2026-10-30"}
        idx_fn = lambda sym, range_="2y": (bars_from([3000 - i * 2 for i in range(1100)], "2024-01-01"), {})
        plain = bt.run(dict(p), tc.load_config(), tc.load_universe(), data_fn=self.loader, bench_fn=lambda *a, **k: ([], {}))
        a = bt.run(dict(p, regime="off", regime_compare=True), tc.load_config(), tc.load_universe(), data_fn=self.loader,
                   bench_fn=lambda *a, **k: ([], {}), index_fn=idx_fn)
        b = bt.run(dict(p, regime="off", regime_compare=True), tc.load_config(), tc.load_universe(), data_fn=self.loader,
                   bench_fn=lambda *a, **k: ([], {}), index_fn=idx_fn)
        self.assertEqual(a["regime_compare"], b["regime_compare"])
        cols = a["regime_compare"]["columns"]
        self.assertEqual([c["variant"] for c in cols], list(bt.REGIME_VARIANTS))
        for k in ("trades", "win_rate_pct", "expectancy_r", "cagr_pct", "max_drawdown_pct", "worst_year",
                  "swing_expectancy_r", "pullback_expectancy_r"):
            self.assertIn(k, cols[0])
        self.assertEqual(cols[0]["trades"], plain["metrics"]["overall"]["trades"])
        self.assertEqual(a["metrics"], plain["metrics"])
        nt = [c for c in cols if c["variant"] == "close_below_200dma:no_new_trades"][0]
        self.assertEqual(nt["trades"], 0)                       # the index falls all the way: never risk-on
        self.assertIn("## Market regime compare", bt.render_md(a))
        self.assertEqual(DASH.bt_regime(a)["columns"], list(bt.REGIME_VARIANTS))
        self.assertIsNone(DASH.bt_regime(plain))

    def test_parse(self):
        self.assertIsNone(bt.parse_regime("off"))
        self.assertEqual(bt.parse_regime("sma50_below_sma200:half_risk"), {"rule": "sma50_below_sma200", "action": "half_risk"})
        with self.assertRaises(ValueError):
            bt.parse_regime("close_below_200dma:sell_everything")


# --- C. fixes --------------------------------------------------------------------------------------------

WHY = [tc.why_item("NEWS", tc.NEWS_FILINGS, None, None, None, None, None, "UNKNOWN: NSE did not answer"),
       tc.why_item("HISTORY", "past trades of this setup on this stock", 1, 8, ">=", False, "trades",
                   "too few to rank by (under 8): information only, ranked by setup score"),
       tc.why_item("SETUP", "context: 126-day return", 12.0, None, "info", True, "%", "information only, not a condition"),
       tc.why_item("RISK", "result", "PASS", None, None, True, None, "every check passed"),
       tc.why_item("SETUP", "close above the 50-day average", 120.0, 100.0, ">", True, "Rs"),
       tc.why_item("PLAN", "net reward:risk", 1.2, 1.5, ">=", False, "R")]


class Fixes(OfflineCase):
    def test_why_order_everywhere(self):
        o = tc.order_why(WHY)
        self.assertEqual([tc.why_tier(x) for x in o], [0, 0, 0, 1, 1, 2])
        self.assertEqual([x["group"] for x in o[:3]], ["SETUP", "PLAN", "RISK"])
        md = "\n".join(DAILY.why_md(WHY, "Check announcements yourself: [NSE](x)"))
        self.assertLess(md.index("SETUP:"), md.index("info (information only"))
        self.assertLess(md.index("info (information only"), md.index("Exchange filings"))
        self.assertLess(md.index("Exchange filings"), md.index("Check announcements yourself"))
        lines = ER.why_lines({"why": WHY})
        self.assertEqual([w["tier"] for w in lines], sorted(w["tier"] for w in lines))
        self.assertEqual([w["mark"] for w in lines if w["tier"] == 1], ["i", "i"])   # grey info, not a red cross
        self.assertTrue(lines[-1]["text"].endswith("check yourself"))
        view = {i["check"]: i for g in DASH.why_view(WHY) for i in g["items"]}
        self.assertEqual(view["past trades of this setup on this stock"]["mark"], "info")
        self.assertEqual(view["net reward:risk"]["mark"], "failed")
        self.assertEqual(view[tc.NEWS_FILINGS]["tier"], 2)
        page = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()
        self.assertIn('"UNKNOWN: check yourself"', page)
        self.assertIn('"Information only"', page)

    def test_tm_label(self):
        self.assertEqual(tc.tm_label(0.81, 1, 8), "+0.81R (1 past trade: too few to judge)")
        self.assertEqual(tc.tm_label(0.41, 9, 8), "+0.41R (9 past trades)")
        self.assertEqual(tc.tm_label(None, 3, 8), "UNKNOWN")
        c = ER.card({"symbol": "ALFA", "expectancy_r": 0.81, "past_trades": 1, "why": []}, 8)
        self.assertEqual(c["time_machine"], "+0.81R (1 past trade: too few to judge)")
        self.assertIn("+0.81R (1 past trade: too few to judge)", ER.render_html(
            dict(ER.build(DAY, tc.load_config()), kind="picks", picks=[c], problem=None)))
        v = DASH.row_view({"symbol": "ALFA", "expectancy_r": 0.81, "past_trades": 1, "why": []}, 8)
        self.assertEqual(v["display"]["time_machine"], "+0.81R (1 past trade: too few to judge)")

    def test_market_closed_detection(self):
        cfg = tc.load_config()
        at = lambda s: tc.dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tc.IST)
        scan = {"latest_bar": "2026-10-29"}
        self.assertIn("no scanned stock has a bar for 2026-10-30", DAILY.market_closed(scan, cfg, at("2026-10-30 16:20")))
        self.assertIsNone(DAILY.market_closed(scan, cfg, at("2026-10-30 15:00")))        # before the close
        self.assertIsNone(DAILY.market_closed({"latest_bar": "2026-10-30"}, cfg, at("2026-10-30 16:20")))
        self.assertIsNone(DAILY.market_closed({"latest_bar": None}, cfg, at("2026-10-30 16:20")))   # a failure

    def test_market_closed_run_and_force_and_email(self):
        self.build_universe()
        env = dict(os.environ, TAYYIB_DIR=self.dir, TAYYIB_FIXTURES=FIX, TAYYIB_NOW="2026-11-02 18:00")   # Monday
        run = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "tayyib-daily", "daily.py"), "--no-news",
                                         "--runs", "200"] + list(a), capture_output=True, encoding="utf-8", env=env,
                                        cwd=self.dir)
        p = run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("market closed (no bars for today)", p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "daily", "2026-11-02.json")))
        self.assertIn("2026-11-02", self.read(os.path.join("daily", "closed.json"))["days"])
        os.environ["TAYYIB_NOW"] = "2026-11-02 18:00"
        try:
            cfg = tc.load_config()
            r = ER.do_send(cfg, tc.parse_date("2026-11-02"), scheduled=False, dry_run=True)
            self.assertEqual(r["status"], "market_closed")                       # not a "stale" email
            self.assertFalse(os.path.exists(os.path.join(self.dir, "email", "2026-11-02.eml")))
            self.assertEqual(ER.build(tc.parse_date("2026-11-03"), cfg)["kind"], "failed")   # a real failure still is
        finally:
            os.environ["TAYYIB_NOW"] = NOW
        p = run("--force")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "daily", "2026-11-02.json")))


class Docs(unittest.TestCase):
    def test_version_and_docs(self):
        self.assertEqual(tc.VERSION, "0.2.4")
        guide = open(os.path.join(ROOT, "docs", "USER_GUIDE.md"), encoding="utf-8").read()
        faq = open(os.path.join(ROOT, "docs", "FAQ.md"), encoding="utf-8").read()
        self.assertIn("When a stock you hold stops being halal", guide)
        self.assertIn("Market regime filter (optional)", guide)
        self.assertIn("Why is the regime filter off by default?", faq)
        for f in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
            self.assertIn('"0.2.4"', open(os.path.join(ROOT, f), encoding="utf-8").read())
        self.assertIn("## v0.2.4", open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
