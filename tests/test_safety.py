"""The rules that must never bend."""
import unittest

from _util import OfflineCase, tc

H, SC, EX, BU, RI, BR = ("tayyib-halal/halal.py", "tayyib-scanner/scan.py", "tayyib-exit/exit.py",
                         "tayyib-budget/size.py", "tayyib-risk/check.py", "tayyib-broker/ticket.py")


class Safety(OfflineCase):
    def setUp(self):
        super().setUp()
        self.build_universe()
        self.run_script(SC)
        self.run_script(EX, "plan", "ALFA,CHRL", "--write")
        self.run_script(BU, "--write")

    def orders(self):
        return self.read("orders.json")

    def tamper(self, **kw):
        o = self.orders()
        for x in o["orders"]:
            x.update(kw)
        self.write("orders.json", o)

    def test_intraday_blocked(self):
        self.tamper(product="MIS")
        for r in self.run_script(RI):
            self.assertEqual(r["status"], "BLOCK")
            self.assertTrue(any("CNC" in b for b in r["block"]))

    def test_short_sell_blocked(self):
        self.tamper(side="SELL")
        for r in self.run_script(RI):
            self.assertEqual(r["status"], "BLOCK")
            self.assertTrue(any("short" in b for b in r["block"]))

    def test_derivative_blocked(self):
        self.tamper(symbol="NIFTY26NOV24000CE")
        for r in self.run_script(RI):
            self.assertEqual(r["status"], "BLOCK")

    def test_halal_override_blocks_order(self):
        self.run_script(H, "override", "CHRL", "--status", "excluded", "--note", "test", as_json=False)
        res = {r["symbol"]: r for r in self.run_script(RI)}
        self.assertEqual(res["CHRL"]["status"], "BLOCK")
        self.assertTrue(any(b.startswith("halal") for b in res["CHRL"]["block"]))

    def test_review_needs_permission(self):
        self.run_script(H, "override", "CHRL", "--status", "review", as_json=False)
        self.assertEqual({r["symbol"]: r["status"] for r in self.run_script(RI)}["CHRL"], "BLOCK")
        self.write("config.json", {"halal": {"allow_review": True}})          # loosening without a note: refused
        self.assertEqual({r["symbol"]: r["status"] for r in self.run_script(RI)}["CHRL"], "BLOCK")
        self.write("config.json", {"halal": {"allow_review": True, "loosen_note": "my scholar, 2026-11"}})
        self.assertNotEqual({r["symbol"]: r["status"] for r in self.run_script(RI)}["CHRL"], "BLOCK")

    def test_expired_plan_blocked(self):
        self.tamper(valid_until="2026-10-01")
        self.assertTrue(all(r["status"] == "BLOCK" for r in self.run_script(RI)))

    def test_risk_limit(self):
        self.write("config.json", {"max_risk_per_trade_rs": 100})
        self.assertTrue(all(r["status"] == "BLOCK" for r in self.run_script(RI)))

    def test_heat_and_cash_count_earlier_orders(self):
        self.write("config.json", {"max_open_positions": 1})
        st = [r["status"] for r in self.run_script(RI)]
        self.assertEqual(st.count("BLOCK"), 1)

    def test_blocked_order_cannot_be_recorded(self):
        self.tamper(product="MIS")
        self.run_script(RI)
        p = self.run_script(BR, "placed", self.orders()["orders"][0]["id"], "--price", 1000, ok=False)
        self.assertNotEqual(p.returncode, 0)

    def test_no_order_placing_code(self):
        import os
        from _util import ROOT
        banned = ("place_order", "kiteconnect", "/orders/regular", "smartapi", "growwapi",
                  "api.kite.trade", "api.groww.in", "groww.in/v1", "groww.in/api")
        for d in os.listdir(ROOT):
            if not d.startswith("tayyib-") and d not in ("core", "mcp"):
                continue
            for f in os.listdir(os.path.join(ROOT, d)):
                if f.endswith((".py", ".html")):                  # incl. the dashboard page
                    src = open(os.path.join(ROOT, d, f), encoding="utf-8").read().lower()
                    for b in banned:
                        self.assertNotIn(b, src, "%s/%s mentions %s" % (d, f, b))

    def test_hard_rules_not_in_config(self):
        for k in ("product", "allow_short", "allow_fno", "allow_margin", "allow_intraday"):
            self.assertNotIn(k, tc.DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main()
