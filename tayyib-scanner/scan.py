#!/usr/bin/env python3
"""tayyib-scanner: scan halal-compliant NSE stocks for swing and delivery setups.

Reads trader/halal_universe.json (only 'compliant' stocks, and 'review' if
the config allows it), pulls daily bars from Yahoo Finance (.NS), checks
liquidity, and arms setups on the latest close. Writes trader/scan.json.
A setup is a chart that matches a rule, not a prediction.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def universe_symbols(cfg, include_review):
    uni = tc.load_universe()
    if not uni.get("stocks"):
        tc.die("no halal universe yet: run tayyib-halal/halal.py build first")
    ok = {"compliant"} | ({"review"} if include_review or cfg["halal"]["allow_review"] else set())
    syms = []
    for s in sorted(uni["stocks"]):
        if tc.halal_status(s, uni)["status"] in ok:
            syms.append(s)
    return syms, uni


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=("swing", "delivery", "all"), default="all")
    p.add_argument("--setups", help="comma list: %s" % ",".join(tc.SWING_SETUPS + tc.DELIVERY_SETUPS))
    p.add_argument("--symbols", help="scan only these (they must still be halal-compliant)")
    p.add_argument("--limit", type=int, default=0, help="scan at most N symbols")
    p.add_argument("--top", type=int, default=25, help="keep the best N candidates")
    p.add_argument("--min-score", type=float, default=0)
    p.add_argument("--include-review", action="store_true")
    p.add_argument("--sleep", type=float, default=0.25)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()

    allowed, uni = universe_symbols(cfg, a.include_review)
    skipped = []
    if a.symbols:
        req = tc.parse_symbols(a.symbols)
        syms = [s for s in req if s in allowed]
        for s in req:
            if s not in allowed:
                skipped.append({"symbol": s, "reason": "not halal-compliant (%s)"
                                % tc.halal_status(s, uni)["status"]})
    else:
        syms = allowed
    if a.limit:
        syms = syms[: a.limit]
    setups = [x.strip() for x in a.setups.split(",")] if a.setups else None

    cands, errors = [], []
    for s in syms:
        try:
            bars, _ = tc.get_daily_bars(s)
        except tc.FetchError as e:
            errors.append({"symbol": s, "error": str(e)})
            continue
        if len(bars) < 210:
            skipped.append({"symbol": s, "reason": "only %d days of history" % len(bars)})
            continue
        ok, why = tc.liquidity_ok(bars, cfg)
        if not ok:
            skipped.append({"symbol": s, "reason": why})
            continue
        for sig in tc.detect_all(bars, a.mode, setups=setups, tick=cfg["tick_size"]):
            if sig["score"] < a.min_score:
                continue
            rec = tc.halal_status(s, uni)
            sig.update(symbol=s, name=rec.get("name", ""), industry=rec.get("industry", ""),
                       halal=rec["status"])
            cands.append(sig)
        if not tc.fixtures_dir():
            time.sleep(a.sleep)
    cands.sort(key=lambda x: -x["score"])
    cands = cands[: a.top]
    out = {"asof": tc.now_ist().isoformat(timespec="minutes"), "mode": a.mode,
           "universe_updated": uni.get("updated"), "scanned": len(syms),
           "candidates": cands, "skipped": skipped, "errors": errors}
    tc.write_json("scan.json", out)
    if a.json:
        return tc.print_json(out)
    print("Scanned %d halal-compliant stocks (%s mode), %d setups armed:" % (len(syms), a.mode, len(cands)))
    if cands:
        print("  %-12s %-9s %-8s %9s %9s %9s %6s" % ("symbol", "setup", "mode", "close", "trigger", "invalid", "score"))
        for c in cands:
            print("  %-12s %-9s %-8s %9.2f %9.2f %9.2f %6.1f" % (c["symbol"], c["setup"], c["mode"], c["close"],
                                                              c["trigger"], c["invalidation"], c["score"]))
            print("      %s" % c["notes"])
    if skipped:
        print("  skipped %d (illiquid, short history or not halal)" % len(skipped))
    if errors:
        print("  %d data errors, first: %s" % (len(errors), errors[0]["error"]))
    print("Next: tayyib-news for these, then tayyib-entry check SYMBOL. -> trader/scan.json")


if __name__ == "__main__":
    main()
