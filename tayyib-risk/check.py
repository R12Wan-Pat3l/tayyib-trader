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


REQUIRED = ("id", "symbol", "side", "product", "qty", "trigger_price", "stop", "target")


def check_order(o, cfg, positions, uni, news, extra_heat=0.0, extra_count=0, extra_ind=None, extra_value=0.0):
    block, warn, ok = [], [], []
    missing = [k for k in REQUIRED if o.get(k) in (None, "")]
    if missing:
        return {"id": o.get("id", "?"), "symbol": o.get("symbol", "?"), "status": "BLOCK",
                "block": ["order is missing %s: re-run tayyib-budget --write" % ", ".join(missing)],
                "warn": [], "ok": []}
    holdings = {}
    for p in positions:
        if p.get("status") == "open":
            holdings[p["symbol"]] = holdings.get(p["symbol"], 0) + p["qty"]
    block += ["hard rule: " + v for v in tc.guard_order(o, holdings)]

    h = tc.halal_status(o["symbol"], uni)
    if not uni.get("stocks"):
        block.append("no halal universe: run tayyib-halal build")
    elif h["status"] == "compliant":
        ok.append("halal: compliant (%s)" % h.get("source", ""))
    elif h["status"] == "review" and cfg["halal"]["allow_review"]:
        warn.append("halal: under review, allowed by config: %s" % "; ".join(h.get("reasons", [])[:2]))
    elif cfg["halal"]["require_compliant"] or h["status"] == "excluded":
        block.append("halal: %s (%s)" % (h["status"], "; ".join(h.get("reasons", [])[:2])))
    age = tc.universe_age_days(uni)
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        warn.append("halal list is %d days old (max %d): rebuild it" % (age, cfg["halal"]["list_max_age_days"]))

    budget = cfg["capital"] * cfg["max_risk_per_trade_pct"] / 100.0
    if cfg.get("max_risk_per_trade_rs"):
        budget = min(budget, float(cfg["max_risk_per_trade_rs"]))
    loss = o.get("loss_at_stop_rs", 0)
    (ok if loss <= budget + 0.01 else block).append(
        "loss at stop %s vs max %s" % (tc.fmt_rs(loss), tc.fmt_rs(budget)))
    pv = o["qty"] * o["trigger_price"]
    maxpv = cfg["capital"] * cfg["max_position_pct"] / 100.0
    (ok if pv <= maxpv + 0.01 else block).append(
        "position %s vs max %s" % (tc.fmt_rs(pv), tc.fmt_rs(maxpv)))
    open_pos = [p for p in positions if p.get("status") == "open"]
    invested = sum(p["qty"] * p["entry"] for p in open_pos)
    cash = cfg["cash_available"] if cfg.get("cash_available") is not None else cfg["capital"] - invested
    cash -= extra_value
    need = pv + o.get("buy_charges_rs", 0)
    (ok if need <= cash + 0.01 else block).append("needs %s, cash %s" % (tc.fmt_rs(need), tc.fmt_rs(cash)))
    n = len(open_pos) + extra_count
    (ok if n < cfg["max_open_positions"] else block).append(
        "open positions %d (max %d)" % (n, cfg["max_open_positions"]))
    heat = sum(max(0.0, (p["entry"] - p["stop"]) * p["qty"]) for p in open_pos) + extra_heat
    heat_new = (heat + loss) / cfg["capital"] * 100
    (ok if heat_new <= cfg["max_portfolio_heat_pct"] + 1e-9 else block).append(
        "portfolio heat %.2f%% after this trade (max %.1f%%)" % (heat_new, cfg["max_portfolio_heat_pct"]))
    ind = h.get("industry") or ""
    if ind:
        same = sum(1 for p in open_pos if tc.halal_status(p["symbol"], uni).get("industry") == ind)
        same += (extra_ind or {}).get(ind, 0)
        (ok if same < cfg["max_positions_per_industry"] else block).append(
            "%d open in %s (max %d)" % (same, ind, cfg["max_positions_per_industry"]))
    rr = o.get("reward_risk_net") or 0
    (ok if rr >= cfg["min_reward_risk"] else block).append(
        "net reward:risk %.2f (min %.1f)" % (rr, cfg["min_reward_risk"]))
    vu = o.get("valid_until")
    if vu and tc.today_ist() > tc.parse_date(vu):
        block.append("plan expired on %s: re-scan" % vu)
    if o["symbol"] in holdings:
        warn.append("already holding %d %s: this adds to it" % (holdings[o["symbol"]], o["symbol"]))
    for it in (news.get("symbols", {}) or {}).get(o["symbol"], []):
        if it.get("halal_watch"):
            warn.append("HALAL-WATCH news: %s (%s)" % (it["title"][:90], ", ".join(it["halal_watch"])))
        if "results" in it.get("tags", []):
            warn.append("results news in the window: gaps are likely (%s)" % it["title"][:70])
    status = "BLOCK" if block else ("WARN" if warn else "PASS")
    return {"id": o["id"], "symbol": o["symbol"], "status": status, "block": block, "warn": warn, "ok": ok}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="?", help="order ids or symbols (default: all SIZED orders)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    store = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    positions = (tc.read_json("positions.json", {}) or {}).get("positions", [])
    uni = tc.load_universe()
    news = tc.read_json("news.json", {}) or {}
    want = set(tc.parse_symbols(a.ids)) if a.ids else None
    results, heat, count, inds, value = [], 0.0, 0, {}, 0.0
    for o in store["orders"]:
        if o.get("status") == "PLACED":
            continue
        if want and o.get("symbol") not in want and str(o.get("id", "")).upper() not in want:
            continue
        r = check_order(o, cfg, positions, uni, news, heat, count, inds, value)
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
