#!/usr/bin/env python3
"""tayyib-alerts: rings when a price or a date is hit. Each alert rings once.

  add SYM --above P | --below P [--note]
  add --from-plan        entry trigger (above) for every plan
  add --from-positions   stop (below), target (above), time stop (date) for open positions
  check                  fetch prices, ring what hit (schedule it: every 15 min in market hours)
  list / clear
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def load():
    return tc.read_json("alerts.json", {"alerts": []}) or {"alerts": []}


def add(store, sym, kind, level, note):
    sym = tc.normalize_symbol(sym)
    for x in store["alerts"]:
        if x["symbol"] == sym and x["kind"] == kind and x["level"] == level and not x["fired"]:
            return None
    n = 1 + max([x["n"] for x in store["alerts"]] or [0])
    al = {"n": n, "symbol": sym, "kind": kind, "level": level, "note": note, "fired": None,
          "created": tc.now_ist().isoformat(timespec="minutes")}
    store["alerts"].append(al)
    return al


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add")
    ad.add_argument("symbol", nargs="?")
    ad.add_argument("--above", type=float)
    ad.add_argument("--below", type=float)
    ad.add_argument("--on", help="date YYYY-MM-DD")
    ad.add_argument("--note", default="")
    ad.add_argument("--from-plan", action="store_true")
    ad.add_argument("--from-positions", action="store_true")
    ad.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ck = sub.add_parser("check")
    ck.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    cl = sub.add_parser("clear")
    cl.add_argument("--fired", action="store_true", help="only the ones that already rang")
    cl.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    store = load()

    if a.cmd == "add":
        added = []
        if a.from_plan:
            for s, pl in ((tc.read_json("plan.json", {}) or {}).get("plans", {})).items():
                added.append(add(store, s, "above", pl["entry"], "entry trigger (%s)" % pl["setup"]))
        if a.from_positions:
            for x in (tc.read_json("positions.json", {}) or {}).get("positions", []):
                if x["status"] != "open":
                    continue
                added.append(add(store, x["symbol"], "below", x["stop"], "STOP: sell %d" % x["qty"]))
                added.append(add(store, x["symbol"], "above", x["target"], "TARGET: sell %d" % x["qty"]))
                if x.get("time_stop_date"):
                    added.append(add(store, x["symbol"], "date", x["time_stop_date"], "TIME STOP: exit"))
        if a.symbol:
            if a.above is not None:
                added.append(add(store, a.symbol, "above", a.above, a.note))
            if a.below is not None:
                added.append(add(store, a.symbol, "below", a.below, a.note))
            if a.on:
                added.append(add(store, a.symbol, "date", a.on, a.note))
        added = [x for x in added if x]
        tc.write_json("alerts.json", store)
        if a.json:
            return tc.print_json(added)
        for x in added:
            print("added #%d %s %s %s %s" % (x["n"], x["symbol"], x["kind"], x["level"], x["note"]))
        if not added:
            print("nothing new to add")
        return

    if a.cmd == "check":
        live = [x for x in store["alerts"] if not x["fired"]]
        prices, rang, errors = {}, [], []
        today = tc.today_ist().isoformat()
        for x in live:
            if x["kind"] == "date":
                if today >= x["level"]:
                    x["fired"] = tc.now_ist().isoformat(timespec="minutes")
                    rang.append(dict(x, price=None))
                continue
            if x["symbol"] not in prices:
                try:
                    prices[x["symbol"]] = tc.last_price(x["symbol"])
                except tc.FetchError as e:
                    errors.append("%s: %s" % (x["symbol"], e))
                    prices[x["symbol"]] = None
            px = prices[x["symbol"]]
            if px is None:
                continue
            if (x["kind"] == "above" and px >= x["level"]) or (x["kind"] == "below" and px <= x["level"]):
                x["fired"] = tc.now_ist().isoformat(timespec="minutes")
                rang.append(dict(x, price=px))
        tc.write_json("alerts.json", store)
        if a.json:
            return tc.print_json({"rang": rang, "prices": prices, "errors": errors})
        for x in rang:
            if x["kind"] == "date":
                print("RING  %s  date %s reached  %s" % (x["symbol"], x["level"], x["note"]))
            else:
                print("RING  %s  %.2f is %s %.2f  %s" % (x["symbol"], x["price"], x["kind"], x["level"], x["note"]))
        if not rang:
            print("nothing hit (%d live alerts, market %s)" % (len(live), tc.market_status()))
        for e in errors:
            print("  price error %s" % e)
        return

    if a.cmd == "list":
        if a.json:
            return tc.print_json(store)
        for x in store["alerts"]:
            print("#%-3d %-12s %-6s %-10s %-6s %s" % (x["n"], x["symbol"], x["kind"], x["level"],
                                                   "rang" if x["fired"] else "live", x["note"]))
        return

    if a.cmd == "clear":
        store["alerts"] = [x for x in store["alerts"] if not x["fired"]] if a.fired else []
        tc.write_json("alerts.json", store)
        print("cleared")


if __name__ == "__main__":
    main()
