import datetime as dt
import unittest

from _util import tc, OfflineCase


class Indicators(unittest.TestCase):
    def test_sma_ema(self):
        v = [1, 2, 3, 4, 5, 6]
        self.assertEqual(tc.sma(v, 3), [None, None, 2.0, 3.0, 4.0, 5.0])
        e = tc.ema(v, 3)
        self.assertEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 3.0)
        self.assertAlmostEqual(e[5], 5.0)

    def test_rsi_bounds(self):
        up = [float(x) for x in range(1, 40)]
        self.assertEqual(tc.rsi(up)[-1], 100.0)
        zig = [10, 11] * 20
        r = tc.rsi(zig)[-1]
        self.assertTrue(40 < r < 60)

    def test_atr_constant_range(self):
        bars = [{"open": 10, "high": 11, "low": 9, "close": 10, "volume": 1} for _ in range(30)]
        self.assertAlmostEqual(tc.atr(bars)[-1], 2.0)


class Formatting(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(tc.fmt_rs(1234567.8), "Rs 12,34,567.80")
        self.assertEqual(tc.fmt_rs(999), "Rs 999.00")
        self.assertEqual(tc.fmt_rs(-100000, 0), "-Rs 1,00,000")
        self.assertEqual(tc.fmt_rs(123456789, 0), "Rs 12,34,56,789")

    def test_round_tick(self):
        self.assertEqual(tc.round_tick(100.02, 0.05, "up"), 100.05)
        self.assertEqual(tc.round_tick(100.07, 0.05, "down"), 100.05)
        self.assertEqual(tc.round_tick(100.05, 0.05, "up"), 100.05)


class Symbols(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(tc.normalize_symbol(" tcs.ns "), "TCS")
        self.assertEqual(tc.normalize_symbol("NSE:INFY"), "INFY")
        self.assertEqual(tc.parse_symbols("tcs, infy  wipro"), ["TCS", "INFY", "WIPRO"])

    def test_derivatives(self):
        self.assertTrue(tc.is_derivative("NIFTY26NOV24000CE"))
        self.assertTrue(tc.is_derivative("RELIANCE26DECFUT"))
        self.assertTrue(tc.is_derivative("BANKNIFTY26NOV52000PE"))
        self.assertFalse(tc.is_derivative("TCS"))
        self.assertFalse(tc.is_derivative("M&M"))


class Time(unittest.TestCase):
    def test_trading_days_skip_weekend_and_holidays(self):
        cfg = tc.deep_merge(tc.DEFAULT_CONFIG, {"holidays": ["2026-11-02"]})
        self.assertEqual(tc.add_trading_days(dt.date(2026, 10, 30), 1, cfg), dt.date(2026, 11, 3))

    def test_market_status(self):
        cfg = tc.DEFAULT_CONFIG
        at = lambda h, m: dt.datetime(2026, 11, 3, h, m, tzinfo=tc.IST)
        self.assertEqual(tc.market_status(at(9, 5), cfg), "pre-open")
        self.assertEqual(tc.market_status(at(10, 0), cfg), "open")
        self.assertEqual(tc.market_status(at(15, 30), cfg), "closed")
        self.assertEqual(tc.market_status(dt.datetime(2026, 11, 1, 11, 0, tzinfo=tc.IST), cfg), "closed")


class Charges(unittest.TestCase):
    def test_zerodha_delivery_buy(self):
        c = tc.order_charges("BUY", 1000, 100, tc.DEFAULT_CONFIG)
        # turnover 1,00,000: STT 100, exchange 2.97, SEBI 0.10, IPFT 0.10, stamp 15, GST 18% of 3.07
        self.assertEqual(c["stt"], 100.0)
        self.assertEqual(c["exchange"], 2.97)
        self.assertEqual(c["stamp_duty"], 15.0)
        self.assertEqual(c["gst"], 0.55)
        self.assertEqual(c["dp_charge"], 0.0)
        self.assertEqual(c["total"], 118.72)

    def test_sell_has_dp_no_stamp(self):
        c = tc.order_charges("SELL", 1000, 100, tc.DEFAULT_CONFIG)
        self.assertEqual(c["stamp_duty"], 0.0)
        self.assertEqual(c["dp_charge"], 15.34)

    def test_groww_brokerage_capped(self):
        cfg = tc.deep_merge(tc.DEFAULT_CONFIG, {"broker": "groww"})
        self.assertEqual(tc.order_charges("BUY", 1000, 100, cfg)["brokerage"], 20.0)    # 0.1% = 100, cap 20
        self.assertEqual(tc.order_charges("BUY", 100, 10, cfg)["brokerage"], 5.0)       # 0.1% = 1, min 5


class Halal(unittest.TestCase):
    def test_business_screen(self):
        self.assertEqual(tc.business_screen("ITC", "ITC Ltd", "FMCG")[0], "excluded")
        self.assertEqual(tc.business_screen("XBANK", "X Bank Ltd", "Financial Services")[0], "excluded")
        self.assertEqual(tc.business_screen("ABC", "ABC Breweries Ltd", "Beverages")[0], "excluded")
        self.assertEqual(tc.business_screen("PVR", "Some Films Ltd", "Media, Entertainment & Publication")[0], "review")
        self.assertEqual(tc.business_screen("TCS", "Tata Consultancy Services", "Information Technology")[0], "pass")
        # 'Capital Goods' is an industry, not a word in the name: no false positive
        self.assertEqual(tc.business_screen("ALFA", "Alfa Industries Ltd", "Capital Goods")[0], "pass")

    def _f(self, debt, assets, cash, recv, interest, rev):
        d = "2026-03-31"
        return {"TotalDebt": [(d, debt)], "TotalAssets": [(d, assets)], "CashAndCashEquivalents": [(d, cash)],
                "AccountsReceivable": [(d, recv)], "InterestIncome": [(d, interest)], "TotalRevenue": [(d, rev)]}

    def test_financial_limits(self):
        cfg = tc.DEFAULT_CONFIG
        self.assertEqual(tc.financial_screen(self._f(10, 100, 10, 10, 1, 100), cfg)["status"], "compliant")
        self.assertEqual(tc.financial_screen(self._f(25, 100, 10, 10, 1, 100), cfg)["status"], "excluded")
        # income test alone, under 2x the limit -> review (still blocked by default); far over -> excluded
        self.assertEqual(tc.financial_screen(self._f(10, 100, 10, 10, 4, 100), cfg)["status"], "review")
        self.assertEqual(tc.financial_screen(self._f(10, 100, 10, 10, 8, 100), cfg)["status"], "excluded")
        self.assertEqual(tc.financial_screen(self._f(30, 100, 10, 10, 4, 100), cfg)["status"], "excluded")
        self.assertEqual(tc.financial_screen(self._f(10, 100, 50, 41, 1, 100), cfg)["status"], "excluded")
        f = self._f(10, 100, 10, 10, 1, 100)
        del f["TotalDebt"]
        self.assertEqual(tc.financial_screen(f, cfg)["status"], "unknown")

    def test_parse_fundamentals_fixture(self):
        import json, os
        from _util import FIX
        with open(os.path.join(FIX, "fundamentals", "ALFA_annual.json")) as fh:
            obj = json.load(fh)
        f = tc.parse_fundamentals(obj)
        self.assertEqual(tc.latest(f, "TotalDebt"), 120e7)
        self.assertEqual(f["TotalAssets"][0][0], "2025-03-31")


class Guard(unittest.TestCase):
    base = {"symbol": "TCS", "side": "BUY", "product": "CNC", "qty": 5}

    def test_clean_order(self):
        self.assertEqual(tc.guard_order(dict(self.base)), [])

    def test_each_hard_rule(self):
        self.assertTrue(tc.guard_order(dict(self.base, product="MIS")))
        self.assertTrue(tc.guard_order(dict(self.base, product="NRML")))
        self.assertTrue(tc.guard_order(dict(self.base, symbol="NIFTY26NOV24000CE")))
        self.assertTrue(tc.guard_order(dict(self.base, side="SELL")))          # nothing held = short
        self.assertEqual(tc.guard_order(dict(self.base, side="SELL"), {"TCS": 5}), [])
        self.assertTrue(tc.guard_order(dict(self.base, side="SELL", qty=6), {"TCS": 5}))
        self.assertTrue(tc.guard_order(dict(self.base, mtf=True)))
        self.assertTrue(tc.guard_order(dict(self.base, qty=0)))


class Feeds(unittest.TestCase):
    def test_rss_and_atom(self):
        rss = b"""<rss><channel><item><title>A &amp; B</title><link>http://x</link>
        <pubDate>Fri, 30 Oct 2026 08:30:00 GMT</pubDate><description>&lt;b&gt;bold&lt;/b&gt;</description></item></channel></rss>"""
        it = tc.parse_feed(rss, "s")[0]
        self.assertEqual(it["title"], "A & B")
        self.assertEqual(it["published"], "2026-10-30T14:00:00+05:30")
        self.assertEqual(it["summary"], "bold")
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>
        <link href="http://y"/><updated>2026-10-30T12:00:00Z</updated></entry></feed>"""
        it = tc.parse_feed(atom)[0]
        self.assertEqual(it["link"], "http://y")
        self.assertEqual(it["published"], "2026-10-30T17:30:00+05:30")
        self.assertEqual(tc.parse_feed(b"not xml"), [])


class Charts(OfflineCase):
    def test_bars_and_setups(self):
        bars, meta = tc.get_daily_bars("ALFA")
        self.assertEqual(len(bars), 520)
        self.assertEqual(bars[-1]["date"], "2026-10-30")
        self.assertEqual(meta["currency"], "INR")
        names = [s["setup"] for s in tc.detect_all(bars, "all")]
        self.assertIn("breakout", names)
        self.assertIn("trend", names)
        self.assertEqual(tc.detect_all(tc.get_daily_bars("BRVO")[0], "all"), [])   # downtrend

    def test_signal_levels_sane(self):
        bars, _ = tc.get_daily_bars("CHRL")
        for s in tc.detect_all(bars, "all"):
            self.assertLess(s["invalidation"], s["close"])
            self.assertGreater(s["trigger"], s["invalidation"])

    def test_plan_rules(self):
        cfg = tc.DEFAULT_CONFIG
        bars, _ = tc.get_daily_bars("ALFA")
        sig = [s for s in tc.detect_all(bars, "swing") if s["setup"] == "breakout"][0]
        p = tc.plan_trade(sig, cfg)
        risk = p["entry"] - p["stop"]
        self.assertTrue(0.75 * sig["atr"] - 0.06 <= risk <= 3 * sig["atr"] + 0.06)
        self.assertAlmostEqual(p["target"], p["entry"] + 2 * p["risk_per_share"], delta=0.06)
        self.assertEqual(p["product"], "CNC")
        trend = [s for s in tc.detect_all(bars, "delivery")][0]
        d = tc.plan_trade(trend, cfg)
        self.assertGreaterEqual(d["stop"], round(d["entry"] * 0.85, 2) - 0.05)
        self.assertEqual(d["max_hold_days"], 250)


if __name__ == "__main__":
    unittest.main()
