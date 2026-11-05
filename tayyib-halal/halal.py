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
                    rec["ratios"], rec["as_of"], rec["why"] = fs["ratios"], fs["as_of"], fs["why"]
                    rec["near_limit"] = fs["near_limit"]          # display only: ratios close under a limit
                    rec["over_limit"] = fs["over_limit"]          # display only: ratios at or over a limit
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
    uni = {"updated": tc.today_ist().isoformat(), "source": source,
           "method": "TASIS-style" if h["method"] == "tasis" else "custom",
           "thresholds": {k: h[k] for k in tc.TASIS_HALAL},
           "loosened": cfg.get("_halal_loosened"), "stocks": stocks}
    tc.write_json("halal_universe.json", uni)
    counts = {s: sum(1 for x in stocks.values() if x["status"] == s) for s in tc.STATUSES}
    eff = {s: 0 for s in tc.STATUSES}                 # what every other skill uses: overrides applied
    for sym in stocks:
        eff[tc.halal_status(sym, uni)["status"]] += 1
    n_ov = len([k for k in (tc.read_json("halal_overrides.json", {}) or {}) if k in stocks])
    out = {"written": "trader/halal_universe.json", "source": source, "counts": counts,
           "counts_with_overrides": eff, "overrides": n_ov, "fetch_errors": errors}
    banner = tc.halal_banner(cfg, uni)
    if banner:
        out = dict({"banner": banner}, **out)
    if cfg.get("_notes"):
        out["config_notes"] = tc.config_notes(cfg)
    if a.json:
        return tc.print_json(out)
    if banner:
        print(banner)
    print("Halal universe built: %d stocks from %s" % (len(stocks), source))
    print("  %-10s %8s %18s" % ("", "screen", "after overrides"))
    for s in tc.STATUSES:
        print("  %-10s %8d %18d" % (s, counts[s], eff[s]))
    if n_ov:
        print("  (%d of your overrides applied; they are kept across rebuilds in trader/halal_overrides.json)" % n_ov)
    if errors:
        print("  financials unavailable for %d (marked unknown): %s" % (len(errors), ", ".join(errors[:15])))
    print("Only 'compliant' stocks reach the scanner. " + tc.DISCLAIMER)


LABELS = (("debt_to_assets_pct", "debt / total assets", "max_debt_to_assets_pct"),
          ("interest_income_pct", "reported interest / total income", "max_noncompliant_income_pct"),
          ("noncompliant_income_pct", "  + assumed 8% on short-term investments", "max_noncompliant_income_pct"),
          ("cash_receivables_to_assets_pct", "cash + receivables / total assets", "max_cash_receivables_to_assets_pct"))


def show(rec, cfg=None):
    cfg = cfg or tc.load_config()
    print("%-12s %-10s %s" % (rec["symbol"], rec["status"].upper(), rec.get("name", "")))
    for r in rec.get("reasons", []):
        print("    - %s" % r)
    ratios = rec.get("ratios") or {}
    for key, label, lim in LABELS:
        if key in ratios:
            v, L = ratios[key], cfg["halal"][lim]
            print("    %-44s %6.2f%%  (limit %.0f%%) %s" % (label, v, L, "ok" if v < L else "OVER"))
    if ratios.get("total_income_basis"):
        print("    (total income = %s)" % ratios["total_income_basis"])


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
                    rec.update(ratios=fs["ratios"], as_of=fs["as_of"], near_limit=fs["near_limit"], over_limit=fs["over_limit"])
                    rec["reasons"] += fs["reasons"]
                    rec["status"] = fs["status"] if st == "pass" or fs["status"] != "compliant" else "review"
                except tc.FetchError as e:
                    rec["reasons"].append("financials unavailable: %s" % e)
            else:
                rec["status"] = "excluded"
            rec["source"] = "live check (not saved)"
        out.append(rec)
    banner = tc.halal_banner(cfg, uni)
    if a.json:
        return tc.print_json({"banner": banner, "stocks": out})          # banner is null unless loosened
    if banner:
        print(banner)
    for rec in out:
        show(rec, cfg)
    age = tc.universe_age_days(uni)
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        print("warning: the halal universe is %d days old; rebuild it" % age)


def cmd_list(a, cfg):
    uni = tc.load_universe()
    rows = [tc.halal_status(s, uni) for s in sorted(uni.get("stocks", {}))]
    if a.status:
        rows = [r for r in rows if r["status"] == a.status]
    banner = tc.halal_banner(cfg, uni)
    if a.json:
        return tc.print_json({"banner": banner, "stocks": rows})         # banner is null unless loosened
    if banner:
        print(banner)
    print("%d stocks (%s), updated %s, source: %s" % (len(rows), a.status or "all",
                                                     uni.get("updated"), uni.get("source")))
    for r in rows:
        print("  %-12s %-10s %s" % (r["symbol"], r["status"], r.get("name", "")))


def cmd_compare(a, cfg):
    """Compare our universe with a trusted Shariah list (CSV with a Symbol column).

    If the CSV has a Status/Compliance/Shariah column, its values are used
    (compliant / halal / yes / pass vs anything else); otherwise every symbol in
    the file is taken as compliant by that source."""
    with open(a.file, "r", encoding="utf-8-sig") as f:
        text = f.read()
    import csv as _csv
    import io as _io
    theirs = {}
    for r in _csv.DictReader(_io.StringIO(text)):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        sym = tc.normalize_symbol(r.get("symbol") or r.get("nse symbol") or r.get("ticker") or r.get("nse code") or "")
        if not sym or sym.startswith("DUMMY"):
            continue
        st = (r.get("status") or r.get("compliance") or r.get("shariah") or r.get("halal") or "compliant").lower()
        theirs[sym] = "compliant" if st in ("compliant", "halal", "yes", "pass", "passed", "shariah compliant", "y") else "not compliant"
    uni = tc.load_universe()
    if not uni.get("stocks"):
        tc.die("no halal universe yet: run halal.py build first")
    ours = {s: tc.halal_status(s, uni) for s in uni["stocks"]}
    agree, we_stricter, we_looser, not_in_ours = [], [], [], []
    for sym, t in sorted(theirs.items()):
        o = ours.get(sym)
        if o is None:
            not_in_ours.append({"symbol": sym, "theirs": t})
            continue
        row = {"symbol": sym, "theirs": t, "ours": o["status"], "name": o.get("name", ""),
               "reasons": o.get("reasons", [])[:3], "ratios": o.get("ratios", {})}
        if (t == "compliant") == (o["status"] == "compliant"):
            agree.append(row)
        elif t == "compliant":
            we_stricter.append(row)      # they say halal, we block: safe side, worth checking
        else:
            we_looser.append(row)        # we say halal, they don't: fix this first
    covered = len(agree) + len(we_stricter) + len(we_looser)
    out = {"file": a.file, "their_symbols": len(theirs), "overlap": covered,
           "agreement_pct": round(len(agree) / covered * 100, 1) if covered else None,
           "we_say_compliant_they_do_not": we_looser, "they_say_compliant_we_block": we_stricter,
           "not_in_our_universe": not_in_ours, "agree": len(agree)}
    banner = tc.halal_banner(cfg, uni)
    if banner:
        out = dict({"banner": banner}, **out)
    if getattr(a, "json", False):
        return tc.print_json(out)
    if banner:
        print(banner)
    print("Compared with %s: %d symbols, %d also in our universe, agreement %s%%"
          % (os.path.basename(a.file), len(theirs), covered, out["agreement_pct"]))
    print("\n1. WE SAY COMPLIANT, THEY DO NOT (%d): check these first; they could let a non-halal trade through"
          % len(we_looser))
    for r in we_looser:
        print("   %-12s %-30s ours %-9s %s" % (r["symbol"], r["name"][:30], r["ours"], r["ratios"]))
    print("\n2. THEY SAY COMPLIANT, WE BLOCK (%d): the safe side; often missing data or the income test" % len(we_stricter))
    if we_stricter:
        print("   %-12s %-9s %8s %9s %9s %8s  %s" % ("symbol", "ours", "debt%", "reported%", "+assumed%", "cash%", "why"))
    for r in we_stricter:
        q = r["ratios"] or {}
        f = lambda k: "-" if q.get(k) is None else "%.2f" % q[k]
        why = "assumed 8% return only" if any("only the assumed 8%" in x for x in r["reasons"]) else \
              "; ".join(r["reasons"])[:60]
        print("   %-12s %-9s %8s %9s %9s %8s  %s" % (r["symbol"], r["ours"], f("debt_to_assets_pct"),
              f("interest_income_pct"), f("noncompliant_income_pct"), f("cash_receivables_to_assets_pct"), why))
    if not_in_ours:
        print("\n3. ON THEIR LIST, NOT IN OUR UNIVERSE (%d): outside the Nifty 500 or not built yet: %s"
              % (len(not_in_ours), ", ".join(x["symbol"] for x in not_in_ours[:30])))
    income_only = [r for r in we_stricter if r["ours"] == "review"
                   and any(("only the assumed 8%" in x) or ("reported interest is over the limit by under 2x" in x)
                           or ("only the income test failed" in x) for x in r["reasons"])]
    if a.accept_income_reviews and income_only:
        ov = tc.read_json("halal_overrides.json", {}) or {}
        for r in income_only:
            ov[r["symbol"]] = {"status": "compliant", "date": tc.today_ist().isoformat(),
                               "note": "trusted list %s says compliant; ours failed only the income test"
                                       % os.path.basename(a.file)}
        tc.write_json("halal_overrides.json", ov)
        print("\nAccepted %d income-test reviews as compliant (overrides, source noted): %s"
              % (len(income_only), ", ".join(r["symbol"] for r in income_only)))
    elif income_only:
        print("\n%d of group 2 failed only the income test (%s). If you trust this list, accept them with:"
              % (len(income_only), ", ".join(r["symbol"] for r in income_only)))
        print("   halal.py compare %s --accept-income-reviews" % a.file)
    print("\nRecord any other ruling: halal.py override SYMBOL --status excluded|compliant --note \"source\"")


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
    cp = sub.add_parser("compare", help="compare with a trusted Shariah list (CSV with a Symbol column)")
    cp.add_argument("file")
    cp.add_argument("--accept-income-reviews", action="store_true",
                    help="override to compliant the stocks this list calls compliant where our only objection "
                         "is the income test (never debt or cash failures)")
    o = sub.add_parser("override", help="your own (or your scholar's) ruling on one stock")
    o.add_argument("symbol")
    o.add_argument("--status", default="excluded")
    o.add_argument("--note")
    o.add_argument("--clear", action="store_true")
    for sp in (b, c, l_, o, cp):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    {"build": cmd_build, "check": cmd_check, "list": cmd_list, "override": cmd_override,
     "compare": cmd_compare}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
