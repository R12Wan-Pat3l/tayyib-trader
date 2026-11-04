#!/usr/bin/env python3
"""tayyib-budget: size every planned trade to your capital and your max loss.

qty = the most whole shares such that (entry - stop) x qty + all charges
for buying at the entry and selling at the stop stays within your risk per
trade, then capped by max position size and cash. Charges are Indian
equity delivery (CNC): STT, exchange, SEBI, stamp duty, GST, DP charge and
brokerage for the broker in config. Writes trader/orders.json.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def unique_id(base, used):
    """A placed order keeps its id; a new ticket for the same stock and day gets -2, -3, ..."""
    if base not in used:
        return base
    n = 2
    while "%s-%d" % (base, n) in used:
        n += 1
    return "%s-%d" % (base, n)


def open_value(positions):
    return sum(p["qty"] * p["entry"] for p in positions if p.get("status") == "open")


def size(plan, cfg, cash):
    budget = cfg["capital"] * cfg["max_risk_per_trade_pct"] / 100.0
    if cfg.get("max_risk_per_trade_rs"):
        budget = min(budget, float(cfg["max_risk_per_trade_rs"]))
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    risk = entry - stop
    limits = {"risk": int(budget // risk)}
    limits["position"] = int((cfg["capital"] * cfg["max_position_pct"] / 100.0) // entry)
    limits["cash"] = int(cash // (entry * 1.002))
    qty = max(0, min(limits.values()))
    while qty > 0 and qty * risk + tc.round_trip(entry, stop, qty, cfg) > budget:
        qty -= 1
    binding = min(limits, key=limits.get)
    if qty == 0:
        return {"qty": 0, "why": "one share risks %s > budget %s or no cash"
                % (tc.fmt_rs(risk + tc.round_trip(entry, stop, 1, cfg)), tc.fmt_rs(budget))}
    loss = qty * risk + tc.round_trip(entry, stop, qty, cfg)
    gain = qty * (target - entry) - tc.round_trip(entry, target, qty, cfg)
    tick = cfg["tick_size"]
    return {
        "qty": qty, "budget_rs": round(budget, 2), "binding_limit": binding,
        "position_value_rs": round(qty * entry, 2),
        "position_pct": round(qty * entry / cfg["capital"] * 100, 2),
        "buy_charges_rs": tc.order_charges("BUY", entry, qty, cfg)["total"],
        "loss_at_stop_rs": round(loss, 2), "gain_at_target_rs": round(gain, 2),
        "reward_risk_net": round(gain / loss, 2) if loss > 0 else None,
        "limit_price": tc.round_tick(entry * 1.005, tick, "up"),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbols", nargs="?", help="default: every plan")
    p.add_argument("--capital", type=float)
    p.add_argument("--risk-pct", type=float)
    p.add_argument("--risk-rs", type=float)
    p.add_argument("--broker", choices=("zerodha", "groww", "custom"))
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    if a.capital:
        cfg["capital"] = a.capital
    if a.risk_pct:
        cfg["max_risk_per_trade_pct"] = a.risk_pct
    if a.risk_rs:
        cfg["max_risk_per_trade_rs"] = a.risk_rs
    if a.broker:
        cfg["broker"] = a.broker
    plans = (tc.read_json("plan.json", {}) or {}).get("plans", {})
    syms = tc.parse_symbols(a.symbols) if a.symbols else list(plans)
    if not syms:
        tc.die("no plans: run tayyib-exit plan SYMBOL --write first")
    positions = (tc.read_json("positions.json", {}) or {}).get("positions", [])
    cash = cfg["cash_available"] if cfg.get("cash_available") is not None else cfg["capital"] - open_value(positions)
    store = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    keep = [o for o in store["orders"] if o["symbol"] not in syms or o.get("status") == "PLACED"]
    replaced = {o["symbol"]: o["id"] for o in store["orders"] if o not in keep}
    used_ids = {o["id"] for o in keep}
    new = []
    for s in syms:
        pl = plans.get(s)
        if not pl:
            new.append({"symbol": s, "error": "no plan"})
            continue
        sz = size(pl, cfg, cash)
        if not sz["qty"]:
            new.append({"symbol": s, "error": sz["why"]})
            continue
        o = {
            "id": unique_id("%s-%s-%s" % (s, pl["signal_date"], pl["setup"]), used_ids),
            "symbol": s, "exchange": cfg["exchange"],
            "side": "BUY", "product": "CNC", "instrument": "EQ", "qty": sz["qty"],
            "order_type": "SL", "trigger_price": pl["entry"], "limit_price": sz["limit_price"],
            "stop": pl["stop"], "target": pl["target"], "mode": pl["mode"], "setup": pl["setup"],
            "valid_until": pl["valid_until"], "time_stop_date": pl.get("time_stop_date"),
            "risk_per_share": pl["risk_per_share"], "broker": cfg["broker"], "status": "SIZED",
            "created": tc.now_ist().isoformat(timespec="minutes"),
        }
        o.update({k: v for k, v in sz.items() if k not in ("qty", "limit_price")})
        if s in replaced:
            o["replaced"] = replaced[s]
        used_ids.add(o["id"])
        new.append(o)
        cash -= o["position_value_rs"]
    if a.write:
        store["orders"] = keep + [o for o in new if "error" not in o]
        tc.write_json("orders.json", store)
    if a.json:
        return tc.print_json(new)
    print("Capital %s, risk per trade %s%% (%s), broker %s"
          % (tc.fmt_rs(cfg["capital"], 0), cfg["max_risk_per_trade_pct"],
             tc.fmt_rs(cfg["capital"] * cfg["max_risk_per_trade_pct"] / 100, 0), cfg["broker"]))
    for o in new:
        if "error" in o:
            print("  %-12s %s" % (o["symbol"], o["error"]))
            continue
        print("  %-12s BUY %d (CNC) trigger %.2f limit %.2f = %s (%.1f%% of capital, %s limit)"
              % (o["symbol"], o["qty"], o["trigger_price"], o["limit_price"], tc.fmt_rs(o["position_value_rs"]),
                 o["position_pct"], o["binding_limit"]))
        print("               stop %.2f -> lose %s incl. charges; target %.2f -> gain %s; %.2f : 1 net"
              % (o["stop"], tc.fmt_rs(o["loss_at_stop_rs"]), o["target"], tc.fmt_rs(o["gain_at_target_rs"]),
                 o["reward_risk_net"]))
        if o.get("replaced"):
            print("               (replaces the earlier unplaced ticket %s)" % o["replaced"])
    if a.write:
        print("-> trader/orders.json. Next: tayyib-risk check.")


if __name__ == "__main__":
    main()
