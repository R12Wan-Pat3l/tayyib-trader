#!/usr/bin/env python3
"""tayyib-broker: the order ticket you place yourself, and your trade journal.

This version connects to no broker and can place no order. It prints each
risk-approved order in plain words with the exact steps for Zerodha Kite
and Groww, then records what you actually did:

  show                         tickets for PASS/WARN orders
  placed ID --price P          you bought: opens a position in trader/positions.json
  stop ID --stop P             raise a stop (trailing); a stop can never be lowered
  close ID --price P           you sold: closes it, P&L after charges and in R
  positions                    open and closed trades with totals
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

# The Kite / Groww steps live in the core (tc.BROKER_STEPS) so the dashboard shows the same text.
STEPS = tc.BROKER_STEPS


def load():
    orders = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    pos = tc.read_json("positions.json", {"positions": []}) or {"positions": []}
    return orders, pos


def find(items, key):
    key = key.upper()
    hits = [x for x in items if x["id"].upper() == key] or \
           [x for x in items if x["symbol"] == tc.normalize_symbol(key)]
    if not hits:
        tc.die("no order/position %s" % key)
    return hits[-1]


def ticket_text(o):
    s = ["TICKET %s  [%s]" % (o["id"], o["status"]),
         "  BUY %d %s on %s, product CNC (delivery), %s %s" % (o["qty"], o["symbol"], o["exchange"],
                                                             o["mode"], o["setup"]),
         "  buy only if price trades at or above %.2f (stop-limit, limit %.2f), valid until %s"
         % (o["trigger_price"], o["limit_price"], o["valid_until"]),
         "  costs about %s + %s charges" % (tc.fmt_rs(o["position_value_rs"]), tc.fmt_rs(o["buy_charges_rs"])),
         "  stop %.2f -> you lose about %s;  target %.2f -> you gain about %s"
         % (o["stop"], tc.fmt_rs(o["loss_at_stop_rs"]), o["target"], tc.fmt_rs(o["gain_at_target_rs"])),
         "  time stop: sell by %s if neither hits" % (o.get("time_stop_date") or "-"),
         "  How to place it yourself (%s):" % o.get("broker", "zerodha")]
    for k, step in enumerate(tc.broker_steps(o), 1):
        s.append("    %d. %s" % (k, step))
    s.append("  Then tell me: ticket.py placed %s --price <your fill>" % o["id"])
    return "\n".join(s)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("id", nargs="?")
    pl = sub.add_parser("placed")
    pl.add_argument("id", help="order id from 'show', or the symbol")
    pl.add_argument("--price", type=float, required=True)
    pl.add_argument("--qty", type=int)
    pl.add_argument("--date")
    st = sub.add_parser("stop")
    st.add_argument("id", help="position id, or the symbol")
    st.add_argument("--stop", type=float, required=True)
    cl = sub.add_parser("close")
    cl.add_argument("id", help="position id, or the symbol")
    cl.add_argument("--price", type=float, required=True)
    cl.add_argument("--qty", type=int, help="partial sell")
    cl.add_argument("--date")
    cl.add_argument("--reason", choices=("stop", "target", "time", "trail", "manual", "halal"), default="manual")
    ps = sub.add_parser("positions")
    for sp in (sh, pl, st, cl, ps):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    orders, pos = load()

    if a.cmd == "show":
        ready = [o for o in orders["orders"] if o.get("status") in ("PASS", "WARN")]
        if a.id:
            ready = [find(orders["orders"], a.id)]
        if a.json:
            return tc.print_json(ready)
        if not ready:
            print("no approved orders: run tayyib-risk check first (only PASS/WARN become tickets)")
        for o in ready:
            if o["status"] not in ("PASS", "WARN"):
                print("%s is %s: not a ticket" % (o["id"], o["status"]))
                continue
            print(ticket_text(o))
            print()
        print("Nothing here places an order. You place it in your broker app, after you have said yes.")
        return

    if a.cmd == "placed":
        o = find(orders["orders"], a.id)
        if o["status"] not in ("PASS", "WARN"):
            tc.die("%s is %s: only risk-approved orders can be recorded as placed" % (o["id"], o["status"]))
        v = tc.guard_order(dict(o, qty=a.qty or o["qty"]))
        if v:
            tc.die("; ".join(v))
        qty = a.qty or o["qty"]
        fill = a.price
        if fill <= o["stop"]:
            tc.die("fill %.2f is at or under the stop %.2f: do not take this trade" % (fill, o["stop"]))
        position = {"id": o["id"], "symbol": o["symbol"], "mode": o["mode"], "setup": o["setup"],
                    "qty": qty, "entry": fill, "stop": o["stop"], "initial_stop": o["stop"],
                    "target": o["target"], "time_stop_date": o.get("time_stop_date"),
                    "opened": a.date or tc.today_ist().isoformat(), "status": "open",
                    "buy_charges_rs": tc.order_charges("BUY", fill, qty, cfg)["total"], "product": "CNC"}
        pos["positions"].append(position)
        o["status"] = "PLACED"
        tc.write_json("positions.json", pos)
        tc.write_json("orders.json", orders)
        if a.json:
            return tc.print_json(position)
        print("opened %s: %d @ %.2f, stop %.2f, target %.2f. Set the stop/target GTT in your app now."
              % (o["symbol"], qty, fill, o["stop"], o["target"]))
        return

    open_pos = [x for x in pos["positions"] if x["status"] == "open"]
    if a.cmd == "stop":
        x = find(open_pos, a.id)
        if a.stop < x["stop"]:
            tc.die("a stop can only move up (%.2f -> %.2f refused)" % (x["stop"], a.stop))
        x["stop"] = round(a.stop, 2)
        tc.write_json("positions.json", pos)
        print("%s stop raised to %.2f. Update the GTT in your app." % (x["symbol"], x["stop"]))
        return

    if a.cmd == "close":
        x = find(open_pos, a.id)
        qty = a.qty or x["qty"]
        if qty > x["qty"]:
            tc.die("you hold %d; selling %d would be a short sale" % (x["qty"], qty))
        sell = tc.order_charges("SELL", a.price, qty, cfg)["total"]
        buy = x["buy_charges_rs"] * qty / x["qty"]
        pnl = (a.price - x["entry"]) * qty - sell - buy
        risk = (x["entry"] - x["initial_stop"]) * qty
        closed = dict(x, qty=qty, exit=a.price, closed=a.date or tc.today_ist().isoformat(),
                      reason=a.reason, status="closed", pnl_rs=round(pnl, 2),
                      r=round(pnl / risk, 2) if risk > 0 else None, sell_charges_rs=sell,
                      buy_charges_rs=round(buy, 2))
        full = qty == x["qty"]
        if full:
            pos["positions"].remove(x)
        else:
            x["buy_charges_rs"] = round(x["buy_charges_rs"] - buy, 2)
            x["qty"] -= qty
            closed["id"] = x["id"] + "-part"
        pos["positions"].append(closed)
        tc.write_json("positions.json", pos)
        if full:
            al = tc.read_json("alerts.json", {"alerts": []}) or {"alerts": []}
            for z in al["alerts"]:
                if z["symbol"] == x["symbol"] and not z["fired"] and z["note"].split(":")[0] in ("STOP", "TARGET", "TIME STOP"):
                    z["fired"] = "cancelled: position closed"
            tc.write_json("alerts.json", al)
        if a.json:
            return tc.print_json(closed)
        print("closed %d %s @ %.2f (%s): %s after charges, %+.2fR"
              % (qty, x["symbol"], a.price, a.reason, tc.fmt_rs(pnl), closed["r"] or 0))
        return

    if a.cmd == "positions":
        if a.json:
            return tc.print_json(pos)
        print("Open:")
        for x in open_pos:
            print("  %-12s %4d @ %9.2f  stop %9.2f  target %9.2f  since %s  out by %s"
                  % (x["symbol"], x["qty"], x["entry"], x["stop"], x["target"], x["opened"], x["time_stop_date"]))
        done = [x for x in pos["positions"] if x["status"] == "closed"]
        print("Closed: %d" % len(done))
        for x in done:
            print("  %-12s %4d  %9.2f -> %9.2f  %-7s %s  %+.2fR" % (x["symbol"], x["qty"], x["entry"], x["exit"],
                                                               x["reason"], tc.fmt_rs(x["pnl_rs"]), x["r"] or 0))
        if done:
            tot = sum(x["pnl_rs"] for x in done)
            wins = sum(1 for x in done if x["pnl_rs"] > 0)
            print("  total %s, %d of %d winners, avg %+.2fR" % (tc.fmt_rs(tot), wins, len(done),
                                                              sum((x["r"] or 0) for x in done) / len(done)))


if __name__ == "__main__":
    main()
