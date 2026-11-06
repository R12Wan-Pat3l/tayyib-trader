#!/usr/bin/env python3
"""tayyib-risk: PASS / WARN / BLOCK every sized order before it can become a ticket.

Hard rules (cannot be configured away): CNC delivery only, BUY to open,
no short selling, no F&O, no margin, halal-compliant stocks only.
Limits from config: loss at stop, position size, cash, open positions,
portfolio heat (total open risk), positions per industry, net reward:risk,
plan still valid, halal list freshness, HALAL-WATCH news.
Updates trader/orders.json statuses and writes trader/risk.json.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


# The check itself lives in core (v0.2.1) so tayyib-backtest replays the same one; same code, same results.
REQUIRED = tc.RISK_REQUIRED
news_why = tc.risk_news_why
check_order = tc.risk_check_order


def result_why(r):
    """The final RISK item: the status and the first reason, the same one tayyib-daily shows."""
    first = (r.get("block") or [None])[0] or \
        (sorted(r.get("warn") or [], key=lambda w: "HALAL-WATCH" not in w) or [None])[0]
    return tc.why_item("RISK", "result", r["status"], None, None, r["status"] == "PASS", None,
                       first or "every check passed")


def base_id(oid):
    """SANSERA-2026-11-04-breakout-2 -> SANSERA-2026-11-04-breakout (the signal)."""
    import re as _re
    return _re.sub(r"-\d+$", "", oid or "")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="?", help="order ids or symbols (default: all SIZED orders)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    store = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    # v0.2.5: imported holdings have no stop: they count in no trade limit (the daily list skips stocks you hold)
    positions = tc.trade_positions((tc.read_json("positions.json", {}) or {}).get("positions", []))
    uni = tc.load_universe()
    news = tc.read_json("news.json", {}) or {}
    sim = tc.read_json("sim.json", {}) or {}
    want = set(tc.parse_symbols(a.ids)) if a.ids else None
    results, heat, count, inds, value = [], 0.0, 0, {}, 0.0
    placed_signals = {base_id(o["id"]) for o in store["orders"] if o.get("status") == "PLACED"}
    for o in store["orders"]:
        if o.get("status") == "PLACED":
            continue
        # Every unplaced order is evaluated in file order, so limits always count all of them;
        # only the requested ones are reported and saved.
        r = check_order(o, cfg, positions, uni, news, heat, count, inds, value, sim)
        if base_id(o.get("id", "")) in placed_signals and o.get("id") not in placed_signals:
            r["block"].append("this signal (%s) is already placed: a second ticket would double the risk "
                              "on one trade" % base_id(o["id"]))
            r["status"] = "BLOCK"
            r.setdefault("why", []).append(tc.why_item("RISK", "second ticket for a placed signal", base_id(o["id"]),
                                                       None, None, False, None, "BLOCK"))
        r.setdefault("why", []).append(result_why(r))
        requested = not want or o.get("symbol") in want or str(o.get("id", "")).upper() in want
        if requested:
            o["status"] = r["status"]
            o["risk_checked"] = tc.now_ist().isoformat(timespec="minutes")
            results.append(r)
        if r["status"] != "BLOCK":   # later orders count earlier approved ones
            heat += o.get("loss_at_stop_rs", 0)
            value += o["qty"] * o["trigger_price"] + o.get("buy_charges_rs", 0)
            count += 1
            ind = tc.halal_status(o["symbol"], uni).get("industry") or ""
            if ind:
                inds[ind] = inds.get(ind, 0) + 1
    tc.write_json("orders.json", store)
    tc.write_json("risk.json", {"asof": tc.now_ist().isoformat(timespec="minutes"), "results": results})
    if a.json:
        return tc.print_json(results)
    if not results:
        print("no sized orders to check: run tayyib-budget --write first")
    for r in results:
        print("%-5s %s" % (r["status"], r["id"]))
        for x in r["block"]:
            print("   BLOCK  %s" % x)
        for x in r["warn"]:
            print("   warn   %s" % x)
        for x in r["ok"]:
            print("   ok     %s" % x)
    print("Hard rules: " + "; ".join(tc.HARD_RULES))


if __name__ == "__main__":
    main()
