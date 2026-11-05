#!/usr/bin/env python3
"""tayyib-entry: has the setup triggered yet?

For a symbol, takes the armed signal (from trader/scan.json, or found on the
last few daily closes) and checks the sessions since: TRIGGERED (a high
crossed the buy-stop trigger), WAITING, EXTENDED (ran too far past the
trigger: do not chase), INVALIDATED (closed under the invalidation level)
or EXPIRED (not triggered within its valid days). Swing/delivery only: the
decision is on daily bars, the live price is a heads-up. Writes trader/entries.json.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def find_signal(sym, bars, setup, cfg, lookback=6, mode=None):
    scan = tc.read_json("scan.json", {}) or {}
    if not mode and scan.get("mode") in ("swing", "delivery"):
        mode = scan["mode"]
    hits = [c for c in scan.get("candidates", []) if c["symbol"] == sym and (not setup or c["setup"] == setup)
            and (not mode or c["mode"] == mode)]
    if hits:
        best = dict(max(hits, key=lambda c: c["score"]))
        best["other_setups"] = sorted({c["setup"] for c in hits} - {best["setup"]})
        return best
    ind = tc.indicators(bars)
    names = [setup] if setup else list(tc.SWING_SETUPS if mode == "swing" else tc.DELIVERY_SETUPS
                                       if mode == "delivery" else tc.SWING_SETUPS + tc.DELIVERY_SETUPS)
    names = tc.enabled_setups(cfg, names)
    for i in range(len(bars) - 1, max(len(bars) - 1 - lookback, cfg["scanner"]["warmup_bars"]), -1):
        sigs = [x for x in (tc.detect(n, bars, ind, i, cfg["tick_size"], cfg) for n in names) if x]
        if sigs:
            s = max(sigs, key=lambda x: x["score"])
            s["symbol"] = sym
            s["other_setups"] = sorted({x["setup"] for x in sigs} - {s["setup"]})
            return s
    return None


def evaluate(sig, bars, live=None, chase_pct=4.0):
    dates = [b["date"] for b in bars]
    if sig["date"] not in dates:
        return {"status": "UNKNOWN", "why": "signal date %s not in the bars" % sig["date"]}
    k = dates.index(sig["date"])
    after = bars[k + 1:]
    trig, inv = sig["trigger"], sig["invalidation"]
    for n, b in enumerate(after, 1):
        if b["high"] >= trig:
            fill = max(b["open"], trig)
            last = live or bars[-1]["close"]
            st = "EXTENDED" if last > fill * (1 + chase_pct / 100) else "TRIGGERED"
            return {"status": st, "date": b["date"], "fill": round(fill, 2),
                    "why": ("triggered %s at %.2f; now %.2f, more than %.0f%% above: do not chase"
                            % (b["date"], fill, last, chase_pct)) if st == "EXTENDED" else
                    "high %.2f crossed the trigger %.2f on %s%s" % (
                        b["high"], trig, b["date"], " (gap open %.2f)" % b["open"] if b["open"] > trig else "")}
        if b["close"] < inv:
            return {"status": "INVALIDATED", "date": b["date"],
                    "why": "closed %.2f under the invalidation %.2f" % (b["close"], inv)}
        if n >= sig.get("valid_days", 3):
            return {"status": "EXPIRED", "date": b["date"],
                    "why": "not triggered within %d sessions" % sig.get("valid_days", 3)}
    last = live or bars[-1]["close"]
    if live and live >= trig:
        return {"status": "TRIGGERING", "why": "live price %.2f is over the trigger %.2f (confirm at close)"
                % (live, trig)}
    return {"status": "WAITING", "distance_pct": round((trig - last) / last * 100, 2),
            "why": "price %.2f is %.2f%% under the trigger %.2f; %d of %d sessions used"
            % (last, (trig - last) / last * 100, trig, len(after), sig.get("valid_days", 3))}


def check(sym, setup, cfg, live_ok=True, mode=None):
    rec = tc.halal_status(sym)
    if rec["status"] != "compliant" and not (rec["status"] == "review" and cfg["halal"]["allow_review"]):
        return {"symbol": sym, "status": "BLOCKED", "why": "not halal-compliant (%s)" % rec["status"]}
    bars, _ = tc.get_daily_bars(sym, use_cache=False)
    sig = find_signal(sym, bars, setup, cfg, mode=mode)
    if not sig:
        return {"symbol": sym, "status": "NO-SETUP", "why": "no setup armed on the last few closes"}
    live = None
    if live_ok and tc.market_status() == "open":
        try:
            live = tc.last_price(sym)
        except tc.FetchError:
            live = None
    ev = evaluate(sig, bars, live)
    ev.update(symbol=sym, setup=sig["setup"], mode=sig["mode"], signal_date=sig["date"],
              trigger=sig["trigger"], invalidation=sig["invalidation"], signal=sig,
              other_setups=sig.get("other_setups", []))
    return ev


def save(ev):
    e = tc.read_json("entries.json", {}) or {}
    e[ev["symbol"]] = dict(ev, checked=tc.now_ist().isoformat(timespec="minutes"))
    tc.write_json("entries.json", e)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("symbols")
    c.add_argument("--setup")
    c.add_argument("--mode", choices=("swing", "delivery"), help="only setups of this style")
    c.add_argument("--json", action="store_true")
    w = sub.add_parser("watch", help="re-check during market hours until it triggers")
    w.add_argument("symbol")
    w.add_argument("--setup")
    w.add_argument("--every", type=int, default=300, help="seconds (default 5 minutes)")
    w.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    if a.cmd == "check":
        out = []
        for s in tc.parse_symbols(a.symbols):
            try:
                ev = check(s, a.setup, cfg, mode=a.mode)
            except tc.FetchError as e:
                ev = {"symbol": s, "status": "ERROR", "why": str(e)}
            if ev["status"] not in ("ERROR",):
                save(ev)
            out.append(ev)
        if a.json:
            return tc.print_json(out)
        for ev in out:
            print("%-12s %-12s %s" % (ev["symbol"], ev["status"], ev["why"]))
            if ev.get("trigger"):
                print("             %s (%s), trigger %.2f, invalidation %.2f, armed %s"
                      % (ev["setup"], ev["mode"], ev["trigger"], ev["invalidation"], ev["signal_date"]))
                pl = ((tc.read_json("plan.json", {}) or {}).get("plans") or {}).get(ev["symbol"])
                if pl and pl.get("setup") == ev["setup"]:
                    print("             plan stop %.2f (the order's stop); invalidation is the setup's own "
                          "level and only decides whether to enter" % pl["stop"])
                if ev.get("other_setups"):
                    print("             also armed: %s (pick one with --setup)" % ", ".join(ev["other_setups"]))
        print("Next: tayyib-exit plan SYMBOL to set the stop and target before you buy.")
        return
    sym = tc.normalize_symbol(a.symbol)
    last = None
    while True:
        ev = check(sym, a.setup, cfg)
        if ev["status"] != last:
            print("%s  %-12s %s" % (tc.now_ist().strftime("%H:%M"), ev["status"], ev["why"]), flush=True)
            save(ev)
            last = ev["status"]
        if ev["status"] in ("TRIGGERED", "TRIGGERING", "EXTENDED", "INVALIDATED", "EXPIRED",
                            "NO-SETUP", "BLOCKED") or tc.market_status() != "open":
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
