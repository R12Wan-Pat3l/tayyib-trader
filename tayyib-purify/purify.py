#!/usr/bin/env python3
"""tayyib-purify: how much to give away to purify dividends (and, if you
choose, gains) from the non-compliant part of a company's income.

Even a compliant company earns a little interest or other non-compliant
income (under 3% on TASIS-style screens). Many scholars hold that this
share of the dividend is not yours: give it to charity, without counting
it as zakat or sadaqah for reward. Some also advise purifying the same
share of capital gains as a precaution. This tool does the arithmetic;
the ruling is your scholar's.

  add-dividend SYM AMOUNT [--date] [--ratio PCT]
  report [--year YYYY] [--include-gains]
  estimate SYM --since DATE   a held stock that stopped passing the screen (v0.2.4): the non-compliant share
                              of the dividends received while holding it, plus any gain since DATE (the status
                              change). An estimate: confirm with your scholar.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def ratio_for(sym, override=None):
    if override is not None:
        return float(override), "given"
    rec = tc.halal_status(sym)
    r = (rec.get("ratios") or {}).get("noncompliant_income_pct")
    if r is not None:
        return float(r), "halal universe (%s)" % rec.get("as_of", "latest")
    return None, "unknown: pass --ratio or rebuild the halal universe with financials"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add-dividend")
    ad.add_argument("symbol")
    ad.add_argument("amount", type=float, help="rupees received (before or after TDS: be consistent)")
    ad.add_argument("--date")
    ad.add_argument("--ratio", type=float, help="non-compliant income %% to use instead of the screen's")
    rp = sub.add_parser("report")
    rp.add_argument("--year", type=int, help="calendar year (default: all)")
    rp.add_argument("--include-gains", action="store_true", help="also purify realised gains")
    rp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    es = sub.add_parser("estimate", help="purification estimate for a held stock that stopped passing")
    es.add_argument("symbol")
    es.add_argument("--since", required=True, help="the status-change date (from the alert)")
    es.add_argument("--ratio", type=float, help="non-compliant income %% to use instead of the screen's")
    es.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    store = tc.read_json("purification.json", {"dividends": []}) or {"dividends": []}

    if a.cmd == "add-dividend":
        d = {"symbol": tc.normalize_symbol(a.symbol), "amount_rs": a.amount,
             "date": a.date or tc.today_ist().isoformat(), "ratio_pct": a.ratio}
        store["dividends"].append(d)
        tc.write_json("purification.json", store)
        print("recorded %s dividend of %s on %s" % (d["symbol"], tc.fmt_rs(a.amount), d["date"]))
        return

    if a.cmd == "estimate":
        return estimate(a, store)

    lines, total, unknown = [], 0.0, []
    yr = (lambda d: d is None or a.year is None or str(d).startswith(str(a.year)))
    for d in store["dividends"]:
        if not yr(d["date"]):
            continue
        r, src = ratio_for(d["symbol"], d.get("ratio_pct"))
        if r is None:
            unknown.append(d["symbol"])
            continue
        amt = d["amount_rs"] * r / 100
        total += amt
        lines.append({"kind": "dividend", "symbol": d["symbol"], "date": d["date"], "base_rs": d["amount_rs"],
                      "ratio_pct": r, "ratio_source": src, "purify_rs": round(amt, 2)})
    if a.include_gains:
        for x in (tc.read_json("positions.json", {}) or {}).get("positions", []):
            if x.get("status") != "closed" or x.get("pnl_rs", 0) <= 0 or not yr(x.get("closed")):
                continue
            r, src = ratio_for(x["symbol"])
            if r is None:
                unknown.append(x["symbol"])
                continue
            amt = x["pnl_rs"] * r / 100
            total += amt
            lines.append({"kind": "gain", "symbol": x["symbol"], "date": x["closed"], "base_rs": x["pnl_rs"],
                          "ratio_pct": r, "ratio_source": src, "purify_rs": round(amt, 2)})
    out = {"year": a.year, "include_gains": a.include_gains, "lines": lines,
           "total_rs": round(total, 2), "unknown_ratio": sorted(set(unknown))}
    if getattr(a, "json", False):
        return tc.print_json(out)
    print("Purification %s%s" % ("for %d" % a.year if a.year else "(all years)",
                                 ", dividends + gains" if a.include_gains else ", dividends"))
    for l in lines:
        print("  %-10s %-8s %-12s %14s x %.2f%% = %s" % (l["date"], l["kind"], l["symbol"], tc.fmt_rs(l["base_rs"]),
                                                       l["ratio_pct"], tc.fmt_rs(l["purify_rs"])))
    print("  total to give in charity: %s" % tc.fmt_rs(total))
    if unknown:
        print("  ratio unknown for: %s (use --ratio when recording)" % ", ".join(sorted(set(unknown))))
    print("Arithmetic only. Ask your scholar which income to purify and how.")


def estimate(a, store):
    sym = tc.normalize_symbol(a.symbol)
    held = [x for x in (tc.read_json("positions.json", {}) or {}).get("positions", [])
            if x.get("status") == "open" and x["symbol"] == sym]
    if not held:
        tc.die("%s is not an open position in positions.json" % sym)
    qty = sum(int(x["qty"]) for x in held)
    opened = min(x.get("opened") or x.get("imported") or "" for x in held)   # a holding: held since its import
    r, src = ratio_for(sym, a.ratio)
    try:
        bars, _ = tc.get_daily_bars(sym)
    except tc.FetchError:
        bars = []
    on = [b for b in bars if b["date"] <= a.since]
    since_px = on[-1]["close"] if on else None
    last = bars[-1]["close"] if bars else None
    out = tc.purify_estimate(sym, qty, opened, a.since, since_px, last, r, store.get("dividends", []))
    out["ratio_source"] = src
    if getattr(a, "json", False):
        return tc.print_json(out)
    f = lambda v: "UNKNOWN" if v is None else tc.fmt_rs(v)
    print("Purification estimate for %s (%s)" % (sym, out["label"]))
    print("  dividends while holding (since %s): %s x %s = %s" % (opened, f(out["dividends_rs"]),
          "UNKNOWN" if r is None else "%.2f%%" % r, f(out["dividend_part_rs"])))
    print("  gain since %s: (%s - %s) x %d = %s, counted if positive: %s" % (
        a.since, "UNKNOWN" if last is None else "%.2f" % last, "UNKNOWN" if since_px is None else "%.2f" % since_px,
        qty, f(out["gain_since_rs"]), f(out["gain_part_rs"])))
    print("  total: %s" % f(out["total_rs"]))
    for u in out["unknown"]:
        print("  UNKNOWN: " + u)
    print("Arithmetic only. Ask your scholar which income and which gain to purify, and how.")


if __name__ == "__main__":
    main()
