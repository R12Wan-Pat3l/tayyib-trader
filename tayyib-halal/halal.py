#!/usr/bin/env python3
"""tayyib-halal: build and query the halal (Shariah-screened) stock universe.

Every other skill reads trader/halal_universe.json and refuses anything
that is not 'compliant'. Two ways to build it:

  1. --official FILE|URL  an official Shariah list (e.g. Nifty 500 Shariah
     constituents, or an export from a TASIS / Islamicly / Musaffa screener).
     Trusted as compliant, minus the known-excluded businesses.
  2. self-screen (default) the Nifty 500 list -> business screen (industry,
     name, known exclusions) -> TASIS-style financial ratios from Yahoo.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def load_rows(src, fixture):
    if src and os.path.exists(src):
        with open(src, "r", encoding="utf-8-sig") as f:
            return tc.read_index_csv(f.read())
    body = tc.fetch(src, fixture=fixture, headers={"User-Agent": tc.BROWSER_UA})
    return tc.read_index_csv(body.decode("utf-8-sig", "replace"))


def cmd_build(a, cfg):
    stocks, errors = {}, []
    if a.official:
        rows = load_rows(a.official, "index/official.csv")
        source = "official list: %s" % os.path.basename(a.official)
        for r in rows[: a.limit or None]:
            st, why = tc.business_screen(r["symbol"], r["name"], r["industry"])
            status = "excluded" if st == "excluded" else "compliant"
            reasons = why if st == "excluded" else ["on the official Shariah list"] + (why if st == "review" else [])
            stocks[r["symbol"]] = dict(r, status=status, reasons=reasons, source=source)
    else:
        src = a.parent or cfg["halal"]["parent_list_url"]
        rows = load_rows(src, "index/nifty500.csv")
        source = "self-screened (TASIS-style) from %s" % os.path.basename(src)
        for n, r in enumerate(rows[: a.limit or None]):
            st, why = tc.business_screen(r["symbol"], r["name"], r["industry"])
            rec = dict(r, source=source, reasons=list(why))
            if st == "excluded":
                rec["status"] = "excluded"
            elif a.no_financials:
                rec["status"] = "review" if st == "review" else "unknown"
                rec["reasons"].append("financial ratios not checked (--no-financials)")
            else:
                try:
                    fs = tc.financial_screen(tc.fetch_fundamentals(r["symbol"]), cfg)
                    rec["ratios"], rec["as_of"] = fs["ratios"], fs["as_of"]
                    rec["reasons"] += fs["reasons"]
                    rec["status"] = fs["status"] if fs["status"] != "compliant" or st == "pass" else "review"
                except tc.FetchError as e:
                    rec["status"] = "unknown"
                    rec["reasons"].append("financials unavailable: %s" % e)
                    errors.append(r["symbol"])
                if not tc.fixtures_dir():
                    time.sleep(a.sleep)
            stocks[r["symbol"]] = rec
            if not a.json and (n + 1) % 50 == 0:
                sys.stderr.write("  screened %d/%d\n" % (n + 1, len(rows)))
    h = cfg["halal"]
    uni = {"updated": tc.today_ist().isoformat(), "source": source, "method": "TASIS-style",
           "thresholds": {k: h[k] for k in ("max_debt_to_assets_pct", "max_noncompliant_income_pct",
                                            "max_cash_receivables_to_assets_pct")},
           "stocks": stocks}
    tc.write_json("halal_universe.json", uni)
    counts = {s: sum(1 for x in stocks.values() if x["status"] == s) for s in tc.STATUSES}
    out = {"written": "trader/halal_universe.json", "source": source, "counts": counts,
           "fetch_errors": errors}
    if a.json:
        return tc.print_json(out)
    print("Halal universe built: %d stocks from %s" % (len(stocks), source))
    for s in tc.STATUSES:
        print("  %-10s %d" % (s, counts[s]))
    if errors:
        print("  financials unavailable for %d (marked unknown): %s" % (len(errors), ", ".join(errors[:15])))
    print("Only 'compliant' stocks reach the scanner. " + tc.DISCLAIMER)


def show(rec):
    line = "%-12s %-10s %s" % (rec["symbol"], rec["status"].upper(), rec.get("name", ""))
    print(line)
    for r in rec.get("reasons", []):
        print("    - %s" % r)
    for k, v in (rec.get("ratios") or {}).items():
        print("    %s: %s%%" % (k, v))


def cmd_check(a, cfg):
    uni = tc.load_universe()
    out = []
    for sym in tc.parse_symbols(a.symbols):
        rec = tc.halal_status(sym, uni)
        if rec["status"] == "unknown" and a.live:
            st, why = tc.business_screen(sym, rec.get("name", ""), rec.get("industry", ""))
            rec["reasons"] = why
            if st != "excluded":
                try:
                    fs = tc.financial_screen(tc.fetch_fundamentals(sym), cfg)
                    rec.update(ratios=fs["ratios"], as_of=fs["as_of"])
                    rec["reasons"] += fs["reasons"]
                    rec["status"] = fs["status"] if st == "pass" or fs["status"] != "compliant" else "review"
                except tc.FetchError as e:
                    rec["reasons"].append("financials unavailable: %s" % e)
            else:
                rec["status"] = "excluded"
            rec["source"] = "live check (not saved)"
        out.append(rec)
    if a.json:
        return tc.print_json(out)
    for rec in out:
        show(rec)
    age = tc.universe_age_days(uni)
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        print("warning: the halal universe is %d days old; rebuild it" % age)


def cmd_list(a, cfg):
    uni = tc.load_universe()
    rows = [tc.halal_status(s, uni) for s in sorted(uni.get("stocks", {}))]
    if a.status:
        rows = [r for r in rows if r["status"] == a.status]
    if a.json:
        return tc.print_json(rows)
    print("%d stocks (%s), updated %s, source: %s" % (len(rows), a.status or "all",
                                                     uni.get("updated"), uni.get("source")))
    for r in rows:
        print("  %-12s %-10s %s" % (r["symbol"], r["status"], r.get("name", "")))


def cmd_override(a, cfg):
    if a.status not in tc.STATUSES:
        tc.die("status must be one of %s" % ", ".join(tc.STATUSES))
    ov = tc.read_json("halal_overrides.json", {}) or {}
    sym = tc.normalize_symbol(a.symbol)
    if a.clear:
        ov.pop(sym, None)
    else:
        ov[sym] = {"status": a.status, "note": a.note or "", "date": tc.today_ist().isoformat()}
    tc.write_json("halal_overrides.json", ov)
    print("%s override for %s" % ("cleared" if a.clear else "set %s" % a.status, sym))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build trader/halal_universe.json")
    b.add_argument("--official", help="CSV file or URL of an official Shariah list (Symbol column)")
    b.add_argument("--parent", help="CSV file or URL of the list to self-screen (default Nifty 500)")
    b.add_argument("--no-financials", action="store_true", help="business screen only (fast)")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--sleep", type=float, default=0.4, help="seconds between Yahoo requests")
    c = sub.add_parser("check", help="halal status of symbols")
    c.add_argument("symbols")
    c.add_argument("--live", action="store_true", help="screen symbols not in the universe now")
    l_ = sub.add_parser("list")
    l_.add_argument("--status", choices=tc.STATUSES)
    o = sub.add_parser("override", help="your own (or your scholar's) ruling on one stock")
    o.add_argument("symbol")
    o.add_argument("--status", default="excluded")
    o.add_argument("--note")
    o.add_argument("--clear", action="store_true")
    for sp in (b, c, l_, o):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    cfg = tc.load_config()
    {"build": cmd_build, "check": cmd_check, "list": cmd_list, "override": cmd_override}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
