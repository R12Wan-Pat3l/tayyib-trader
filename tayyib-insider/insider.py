#!/usr/bin/env python3
"""tayyib-insider: what promoters and insiders did, and who traded in bulk.

Reads NSE's public disclosures: insider trading under SEBI (PIT)
Regulations 2015, and bulk / block deals. Promoter buying with their own
money is often watched; pledges, sales and "off-market" transfers are
shown as they are. Public filings, not inside information.
Writes trader/insider.json.
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def g(r, *keys):
    for k in keys:
        if r.get(k) not in (None, "", "-"):
            return r[k]
    return None


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def pit(sess, sym, frm, to):
    obj = sess.get_json("/api/corporates-pit", {"index": "equities", "symbol": sym,
                                               "from_date": frm.strftime("%d-%m-%Y"),
                                               "to_date": to.strftime("%d-%m-%Y")},
                        fixture="nse/pit_%s.json" % sym)
    rows = obj.get("data", []) if isinstance(obj, dict) else obj
    out = []
    for r in rows:
        side = (g(r, "tdpTransactionType", "acqMode") or "").lower()
        out.append({
            "person": g(r, "acqName", "personName"), "category": g(r, "personCategory"),
            "side": "PLEDGE" if "pledge" in side else "BUY" if "buy" in side or "purchase" in side or "acqui" in side
            else "SELL" if "sell" in side or "sale" in side or "dispos" in side
            else (g(r, "tdpTransactionType") or "OTHER"),
            "mode": g(r, "acqMode"), "shares": num(g(r, "secAcq")), "value_rs": num(g(r, "secVal")),
            "from": g(r, "acqfromDt"), "to": g(r, "acqtoDt"), "filed": g(r, "intimDt", "date"),
        })
    return out


def deals(sess, sym, frm, to, kind):
    obj = sess.get_json("/api/historical/%s-deals" % kind,
                        {"symbol": sym, "from": frm.strftime("%d-%m-%Y"), "to": to.strftime("%d-%m-%Y")},
                        fixture="nse/%s_%s.json" % (kind, sym))
    rows = obj.get("data", []) if isinstance(obj, dict) else obj
    out = []
    for r in rows:
        qty, px = num(g(r, "BD_QTY_TRD", "qty")), num(g(r, "BD_TP_WATP", "watp", "price"))
        out.append({"kind": kind, "date": g(r, "BD_DT_DATE", "date"), "client": g(r, "BD_CLIENT_NAME", "clientName"),
                    "side": (g(r, "BD_BUY_SELL", "buySell") or "").upper(), "qty": qty, "price": px,
                    "value_rs": qty * px if qty and px else None})
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbols")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    to = tc.today_ist()
    frm = to - dt.timedelta(days=a.days)
    sess = tc.NSESession()
    result = {}
    for s in tc.parse_symbols(a.symbols):
        rec, errors = {"pit": None, "deals": None}, []
        try:
            rec["pit"] = pit(sess, s, frm, to)
        except (tc.FetchError, ValueError) as e:
            errors.append("pit: %s" % e)
        got_deals = []
        for kind in ("bulk", "block"):
            try:
                got_deals.append(deals(sess, s, frm, to, kind))
            except (tc.FetchError, ValueError) as e:
                errors.append("%s deals: %s" % (kind, e))
        rec["deals"] = sum(got_deals, []) if got_deals else None
        if rec["pit"] is None:            # source failed: unknown, never "zero"
            rec["promoter_net_rs"], rec["pledges"] = None, None
        else:
            promo = [x for x in rec["pit"] if "promoter" in (x["category"] or "").lower()]
            rec["promoter_net_rs"] = round(sum((x["value_rs"] or 0) * (1 if x["side"] == "BUY" else -1 if x["side"] == "SELL" else 0)
                                               for x in promo), 2)
            rec["pledges"] = [x for x in rec["pit"] if "pledge" in (x["mode"] or "").lower()]
        rec["errors"] = errors
        result[s] = rec
    out = {"asof": tc.now_ist().isoformat(timespec="minutes"), "days": a.days, "symbols": result}
    tc.write_json("insider.json", out)
    if a.json:
        return tc.print_json(out)
    for s, rec in result.items():
        print("%s, last %d days" % (s, a.days))
        if rec["pit"] is None:
            print("  insider filings: UNKNOWN (NSE did not answer; this is not the same as none)")
        else:
            print("  insider filings: %d; promoter net %s; pledge events %d"
                  % (len(rec["pit"]), tc.fmt_rs(rec["promoter_net_rs"], 0), len(rec["pledges"])))
        for x in (rec["pit"] or [])[:10]:
            print("    %-10s %-4s %-28s %-22s %10s sh %14s  %s" % (
                (x["filed"] or "")[:11], x["side"], (x["person"] or "")[:28], (x["category"] or "")[:22],
                "-" if x["shares"] is None else "%.0f" % x["shares"], tc.fmt_rs(x["value_rs"], 0), x["mode"] or ""))
        print("  bulk/block deals: %s" % ("UNKNOWN (NSE did not answer)" if rec["deals"] is None else len(rec["deals"])))
        for x in (rec["deals"] or [])[:10]:
            print("    %-11s %-5s %-4s %-30s %10s @ %s" % (x["date"], x["kind"], x["side"], (x["client"] or "")[:30],
                                                         "-" if x["qty"] is None else "%.0f" % x["qty"], x["price"]))
        for e in rec["errors"]:
            print("  (%s)" % e)
        if any("403" in e for e in rec["errors"]):
            print("  NSE blocks some networks and scripts (HTTP 403). Try later, another network, or check nseindia.com in a browser.")


if __name__ == "__main__":
    main()
