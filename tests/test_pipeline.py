"""One trade, end to end, offline: halal -> scan -> news -> entry -> exit ->
timemachine -> budget -> risk -> ticket -> placed -> alerts -> close -> purify."""
import unittest

from _util import OfflineCase

H, SC, NW, EN, EX = ("tayyib-halal/halal.py", "tayyib-scanner/scan.py", "tayyib-news/news.py",
                     "tayyib-entry/entry.py", "tayyib-exit/exit.py")
TM, BU, RI, BR, AL, PU = ("tayyib-timemachine/timemachine.py", "tayyib-budget/size.py", "tayyib-risk/check.py",
                          "tayyib-broker/ticket.py", "tayyib-alerts/alerts.py", "tayyib-purify/purify.py")
ALFA = "ALFA-2026-10-30-breakout"


class HalalUniverse(OfflineCase):
    def test_self_screen(self):
        out = self.build_universe()
        self.assertEqual(out["counts"], {"compliant": 4, "review": 1, "excluded": 3, "unknown": 1})
        st = {r["symbol"]: r["status"] for r in self.run_script(H, "list")["stocks"]}
        self.assertEqual(st["ALFA"], "compliant")
        self.assertEqual(st["DLTA"], "excluded")      # debt 40% of assets
        self.assertEqual(st["EXBANK"], "excluded")    # financial services
        self.assertEqual(st["ITC"], "excluded")       # tobacco
        self.assertEqual(st["ECHO"], "review")        # media
        self.assertEqual(st["GOLF"], "unknown")       # no financials

    def test_official_list_still_drops_known_exclusions(self):
        out = self.run_script(H, "build", "--official", "index/official.csv")
        self.assertEqual(out["counts"]["compliant"], 2)
        self.assertEqual(out["counts"]["excluded"], 1)

    def test_old_overrides_file_is_ignored(self):
        """v0.2.7: no overrides; the screen decides even with an old halal_overrides.json."""
        self.build_universe()
        self.write("halal_overrides.json", {"ALFA": {"status": "excluded", "note": "my scholar"}})
        self.assertEqual(self.run_script(H, "check", "ALFA")["stocks"][0]["status"], "compliant")
        p = self.run_script(H, "override", "ALFA", "--status", "excluded", ok=False)
        self.assertEqual(p.returncode, 2)


class Scanner(OfflineCase):
    def test_only_halal_and_liquid(self):
        self.build_universe()
        self.write("config.json", {"scanner": {"setups": {"pullback": {"enabled": True}}}})   # off by default (v0.2.5)
        out = self.run_script(SC)
        syms = {c["symbol"] for c in out["candidates"]}
        self.assertEqual(syms, {"ALFA", "CHRL"})
        self.assertEqual(out["scanned"], 4)                         # ALFA, BRVO, CHRL, THIN
        self.assertIn("THIN", [s["symbol"] for s in out["skipped"]])  # illiquid
        setups = {(c["symbol"], c["setup"]) for c in out["candidates"]}
        self.assertIn(("ALFA", "breakout"), setups)
        self.assertIn(("CHRL", "pullback"), setups)

    def test_requested_non_halal_symbols_are_skipped(self):
        self.build_universe()
        out = self.run_script(SC, "--symbols", "ITC,DLTA,ALFA")
        self.assertEqual({c["symbol"] for c in out["candidates"]}, {"ALFA"})
        self.assertEqual({s["symbol"] for s in out["skipped"]}, {"ITC", "DLTA"})

    def test_no_universe_is_an_error(self):
        p = self.run_script(SC, ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("halal", p.stderr)


class News(OfflineCase):
    def test_tags_and_halal_watch(self):
        self.build_universe()
        out = self.run_script(NW, "--symbols", "ALFA,CHRL", "--market")
        alfa = out["symbols"]["ALFA"]
        titles = [i["title"] for i in alfa]
        self.assertFalse(any("Old News" in t for t in titles))       # outside 72h
        ncd = [i for i in alfa if "NCDs" in i["title"]][0]
        self.assertIn("new debt", ncd["halal_watch"])
        self.assertTrue(any("results" in i["tags"] for i in alfa))
        self.assertTrue(any(i["source"] == "NSE announcement" for i in alfa))
        self.assertTrue(any(i["source"] == "moneycontrol_markets" for i in alfa))   # mention in a general feed
        self.assertEqual(len(out["symbols"]["CHRL"]), 1)
        self.assertTrue(out["errors"])                                # missing feeds reported, not fatal


class FullTrade(OfflineCase):
    def test_one_trade(self):
        self.build_universe()
        self.run_script(SC)
        self.run_script(NW, "--symbols", "ALFA")
        ev = self.run_script(EN, "check", "ALFA", "--setup", "breakout")[0]
        self.assertEqual(ev["status"], "WAITING")
        self.assertEqual(self.run_script(EN, "check", "ITC")[0]["status"], "BLOCKED")

        plan = self.run_script(EX, "plan", "ALFA", "--setup", "breakout", "--write")[0]
        self.assertEqual(plan["entry"], ev["trigger"])
        self.assertLess(plan["stop"], plan["entry"])
        self.assertEqual(plan["product"], "CNC")

        sim = self.run_script(TM, "run", "--runs", "3000", "--write")["results"]["ALFA"]
        pr = sim["monte_carlo"]["probabilities_pct"]
        self.assertAlmostEqual(sum(pr.values()), 100.0, delta=0.5)
        again = self.run_script(TM, "run", "--runs", "3000")["results"]["ALFA"]
        self.assertEqual(sim["monte_carlo"], again["monte_carlo"])      # same seed, same answer
        self.assertIn("verdict", sim)

        order = self.run_script(BU, "--write")[0]
        self.assertEqual((order["side"], order["product"]), ("BUY", "CNC"))
        self.assertLessEqual(order["loss_at_stop_rs"], 1000.0)          # 1% of Rs 1,00,000
        self.assertLessEqual(order["position_value_rs"], 20000.0)       # 20% cap

        risk = self.run_script(RI)[0]
        self.assertEqual(risk["status"], "WARN")                        # NCD + results news
        self.assertTrue(any("HALAL-WATCH" in w for w in risk["warn"]))
        self.assertFalse(risk["block"])

        ticket = self.run_script(BR, "show", as_json=False)
        self.assertIn("CNC", ticket)
        self.assertIn("never MIS", ticket)
        self.assertIn("Nothing here places an order", ticket)

        pos = self.run_script(BR, "placed", ALFA, "--price", plan["entry"] + 1)
        self.assertEqual(pos["status"], "open")
        added = self.run_script(AL, "add", "--from-positions")
        self.assertEqual({a["kind"] for a in added}, {"below", "above", "date"})
        rang = self.run_script(AL, "check")["rang"]
        self.assertEqual(rang, [])                                       # price is between stop and target

        closed = self.run_script(BR, "close", "ALFA", "--price", plan["target"], "--reason", "target")
        self.assertGreater(closed["pnl_rs"], 0)
        self.assertGreater(closed["r"], 1.5)
        live = [a for a in self.read("alerts.json")["alerts"] if not a["fired"]]
        self.assertEqual(live, [])                                       # closing cancels its alerts

        self.run_script(PU, "add-dividend", "ALFA", "1000", "--date", "2026-08-20", as_json=False)
        rep = self.run_script(PU, "report", "--include-gains")
        div = [l for l in rep["lines"] if l["kind"] == "dividend"][0]
        self.assertAlmostEqual(div["purify_rs"], 1000 * div["ratio_pct"] / 100, places=2)
        self.assertEqual(len(rep["lines"]), 2)


class Research(OfflineCase):
    def test_results_and_drift(self):
        self.build_universe()
        r = self.run_script("tayyib-results/results.py", "ALFA")
        last = r["quarters"][-1]
        self.assertEqual(last["quarter"], "2026-09-30")
        self.assertAlmostEqual(last["TotalRevenue_yoy"], round((372 - 320) / 320 * 100, 1))
        self.assertEqual(r["halal_now"]["status"], "compliant")
        c = self.run_script("tayyib-results/results.py", "CHRL")
        self.assertTrue(any("debt_to_assets_pct rose" in f for f in c["halal_flags"]))

    def test_insider(self):
        out = self.run_script("tayyib-insider/insider.py", "ALFA")["symbols"]["ALFA"]
        self.assertEqual(len(out["pit"]), 3)
        self.assertEqual(out["promoter_net_rs"], 18500000.0)    # promoter buy; director sale is not promoter
        self.assertEqual(len(out["pledges"]), 1)
        self.assertEqual(out["deals"][0]["side"], "BUY")


if __name__ == "__main__":
    unittest.main()
