#!/usr/bin/env python3
"""tayyib-exit: set the stop, the target and the time stop before you buy.

Swing: stop at the setup's invalidation, kept between 0.75 and 3 x ATR and
never more than 10% below entry;
target 2R; out after 20 sessions; breakeven at +1R, trail under the 20 EMA.
Delivery: stop at the invalidation (just under the 200-day average), never
wider than 15%; review at 3R; exit on a weekly close under the 200-day.
Writes trader/plan.json, which tayyib-timemachine and tayyib-budget read.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def signal_for(sym, setup, cfg, mode=None):
    scan = tc.read_json("scan.json", {}) or {}
    if not mode and scan.get("mode") in ("swing", "delivery"):
        mode = scan["mode"]
    ent = (tc.read_json("entries.json", {}) or {}).get(sym)
    hits = [c for c in scan.get("candidates", [])
            if c["symbol"] == sym and (not setup or c["setup"] == setup) and (not mode or c["mode"] == mode)]
    if ent and ent.get("signal") and (not setup or ent["setup"] == setup) and (not mode or ent.get("mode") == mode):
        # An entry record wins when the setup has already triggered (plan from that fill), or when the scan
        # has nothing newer. A WAITING record from an earlier day must not replace today's scan: that kept
        # yesterday's trigger and ticket id (e.g. WELSPUNLIV-2026-11-04-trend on the 2026-11-05 list).
        newer = [c for c in hits if c.get("date", "") > (ent.get("signal_date") or ent["signal"].get("date") or "")]
        if ent.get("status") in ("TRIGGERED", "TRIGGERING", "EXTENDED") or not newer:
            return ent["signal"], ent
    if hits:
        best = dict(max(hits, key=lambda c: c["score"]))
        best["other_setups"] = sorted({c["setup"] for c in hits} - {best["setup"]})
        return best, None
    bars, _ = tc.get_daily_bars(sym, use_cache=False)
    sigs = tc.detect_all(bars, mode or "all", setups=[setup] if setup else None, tick=cfg["tick_size"], cfg=cfg)
    if sigs:
        sigs[0]["symbol"] = sym
        return sigs[0], None
    return None, None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("symbols")
    pl.add_argument("--setup")
    pl.add_argument("--mode", choices=("swing", "delivery"), help="only setups of this style")
    pl.add_argument("--entry", type=float, help="planned entry (default: the trigger, or the fill if triggered)")
    pl.add_argument("--stop", type=float, help="your own stop (overrides the rule)")
    pl.add_argument("--target", type=float, help="your own target (overrides the rule)")
    pl.add_argument("--write", action="store_true", help="save to trader/plan.json")
    pl.add_argument("--json", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("--json", action="store_true")
    rm = sub.add_parser("remove")
    rm.add_argument("symbol")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    store = tc.read_json("plan.json", {"plans": {}}) or {"plans": {}}

    if a.cmd == "show":
        if a.json:
            return tc.print_json(store)
        for s, pln in store["plans"].items():
            print("%-12s %s %s entry %.2f stop %.2f target %.2f (%.1fR) until %s"
                  % (s, pln["mode"], pln["setup"], pln["entry"], pln["stop"], pln["target"],
                     (pln["target"] - pln["entry"]) / pln["risk_per_share"], pln["valid_until"]))
        return
    if a.cmd == "remove":
        store["plans"].pop(tc.normalize_symbol(a.symbol), None)
        tc.write_json("plan.json", store)
        print("removed")
        return

    out = []
    for sym in tc.parse_symbols(a.symbols):
        st = tc.halal_status(sym)["status"]
        if not (st == "compliant" or (st == "review" and cfg["halal"]["allow_review"])):
            out.append({"symbol": sym, "error": "not halal-compliant"})
            continue
        sig, ent = signal_for(sym, a.setup, cfg, a.mode)
        if not sig:
            out.append({"symbol": sym, "error": "no armed setup; pass --setup or run the scanner"})
            continue
        sig = dict(sig, symbol=sym)
        entry = a.entry or (ent.get("fill") if ent and ent.get("fill") else None)
        try:
            pln = tc.plan_trade(sig, cfg, entry)
        except ValueError as e:
            out.append({"symbol": sym, "error": str(e)})
            continue
        if a.stop:
            if a.stop >= pln["entry"]:
                out.append({"symbol": sym, "error": "stop must be under the entry"})
                continue
            pln["stop"], pln["stop_method"] = round(a.stop, 2), "manual"
            pln["risk_per_share"] = round(pln["entry"] - pln["stop"], 2)
            pln["target"] = tc.round_tick(pln["entry"] + pln["target_r"] * pln["risk_per_share"],
                                          cfg["tick_size"], "up")
        if a.target:
            if a.target <= pln["entry"]:
                out.append({"symbol": sym, "error": "target must be above the entry"})
                continue
            pln["target"] = round(a.target, 2)
        pln["reward_risk"] = round((pln["target"] - pln["entry"]) / pln["risk_per_share"], 2)
        pln["time_stop_date"] = tc.add_trading_days(tc.parse_date(sig["date"]), pln["max_hold_days"],
                                                    cfg).isoformat()
        if ent and ent.get("status") in ("TRIGGERED",):
            pln["entry_type"] = "already triggered (filled %s)" % ent.get("date")
        pln["created"] = tc.now_ist().isoformat(timespec="minutes")
        if sig.get("other_setups") and not a.setup:
            pln["other_setups"] = sig["other_setups"]
        out.append(pln)
        if a.write:
            store["plans"][sym] = pln
    if a.write:
        tc.write_json("plan.json", store)
    if a.json:
        return tc.print_json(out)
    for pln in out:
        if "error" in pln:
            print("%-12s %s" % (pln["symbol"], pln["error"]))
            continue
        print("%s  %s (%s)" % (pln["symbol"], pln["setup"], pln["mode"]))
        if pln.get("other_setups"):
            print("  note: also armed as %s; this plan uses %s (choose with --setup or --mode swing|delivery)"
                  % (", ".join(pln["other_setups"]), pln["setup"]))
        print("  entry   %9.2f  %s, valid until %s" % (pln["entry"], pln["entry_type"], pln["valid_until"]))
        print("  stop    %9.2f  %s  (risk %.2f a share)" % (pln["stop"], pln["stop_method"], pln["risk_per_share"]))
        print("  target  %9.2f  %.1fR" % (pln["target"], pln["reward_risk"]))
        print("  time    out by %s (%s)" % (pln["time_stop_date"], tc.plural(pln["max_hold_days"], "session")))
        for t in pln["trail"]:
            print("  - %s" % t)
    if a.write:
        print("-> trader/plan.json. Next: tayyib-timemachine run, then tayyib-budget.")


if __name__ == "__main__":
    main()
