#!/usr/bin/env python3
"""tayyib-daily: today's halal trade list in one command.

Runs the tested skills in order, for today's candidates only:
  halal list check -> scanner -> news -> exit plan -> time machine -> budget -> risk
and prints one table: stock, setup, entry, stop, stop %, target, quantity,
rupee risk, the time machine's verdict, and PASS / WARN / BLOCK with the
first reason. Saves trader/daily/YYYY-MM-DD.md and .json.

Run it after the close (3:30 PM IST). Nothing here places an order: the
list is a set of tickets for you to review, then place yourself.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tayyib_core as tc  # noqa: E402

ROOT = os.path.dirname(HERE)


def script(skill, name):
    p = os.path.join(ROOT, skill, name)
    if not os.path.exists(p):
        tc.die("tayyib-daily needs the other tayyib skills next to it (missing %s/%s)" % (skill, name))
    return p


def run(skill, name, *args, want_json=True):
    argv = [sys.executable, script(skill, name)] + [str(a) for a in args] + (["--json"] if want_json else [])
    p = subprocess.run(argv, capture_output=True, text=True, env=os.environ.copy())
    if p.returncode != 0:
        raise RuntimeError("%s %s failed: %s" % (skill, " ".join(map(str, args)), (p.stderr or p.stdout).strip()[:300]))
    return json.loads(p.stdout) if want_json else p.stdout


def choose(cands, mode, top):
    """One setup per stock. With --mode all, alternate the best swing and the best delivery
    setups, so delivery's higher scores don't crowd out every swing idea."""
    lists = [cands] if mode != "all" else [[c for c in cands if c["mode"] == "swing"],
                                            [c for c in cands if c["mode"] == "delivery"]]
    picks, seen, k = [], set(), 0
    while len(picks) < top and any(k < len(l) for l in lists):
        for l in lists:
            if k < len(l) and l[k]["symbol"] not in seen and len(picks) < top:
                picks.append(l[k])
                seen.add(l[k]["symbol"])
        k += 1
    return picks


def short_verdict(v):
    v = v or ""
    head = v.split(" (")[0]
    for k, s in (("negative", "negative"), ("coin flip", "coin flip"), ("leans positive", "leans +")):
        if k in head:
            return s + ("; sim: a loss is the most likely single outcome"
                        if "most likely single outcome is a loss" in v else "")
    return head[:30]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=("swing", "delivery", "all"), default="all")
    p.add_argument("--top", type=int, default=10, help="plan at most N stocks (best scores first)")
    p.add_argument("--runs", type=int, default=3000, help="time-machine simulations per stock")
    p.add_argument("--no-news", action="store_true", help="skip the news step (faster)")
    p.add_argument("--picks", type=int, default=3, help="how many top PASS stocks to highlight")
    p.add_argument("--no-rebuild", action="store_true", help="never rebuild the halal list automatically")
    p.add_argument("--no-track", action="store_true", help="do not record the list in the Excel tracker")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    notes = []

    # 1. halal universe: built on first run, rebuilt automatically once it is a month old
    uni = tc.load_universe()
    age = tc.universe_age_days(uni) if uni.get("stocks") else None
    every = cfg["halal"].get("auto_rebuild_days") or 0
    if not a.no_rebuild and every and (not uni.get("stocks") or (age is not None and age >= every)):
        why = "first run" if not uni.get("stocks") else "list was %d days old" % age
        if not a.json:
            sys.stderr.write("Rebuilding the halal list (%s): about 5 minutes...\n" % why)
        try:
            b = run("tayyib-halal", "halal.py", "build")
            c = b.get("counts_with_overrides") or b["counts"]
            notes.append("rebuilt the halal list (%s): %d compliant, %d review, %d excluded, %d unknown"
                         % (why, c["compliant"], c["review"], c["excluded"], c["unknown"]))
        except RuntimeError as e:
            notes.append("halal list rebuild failed, using the existing list: %s" % str(e)[:120])
        uni = tc.load_universe()
        age = tc.universe_age_days(uni)
    if not uni.get("stocks"):
        tc.die("no halal universe yet: run tayyib-halal/halal.py build first (about 5 minutes, monthly)")
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        notes.append("halal list is %d days old: rebuild it (halal.py build)" % age)
    elif age is not None and age > 35:
        notes.append("halal list is %d days old: a monthly rebuild is due" % age)
    if tc.market_status() != "closed":
        notes.append("market is %s: today's bar is not final, so levels can still move. Best run after 3:30 PM IST"
                     % tc.market_status())

    # 2. scan
    scan = run("tayyib-scanner", "scan.py", "--mode", a.mode, "--top", max(a.top * 2, 25))
    store0 = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    held = {p_["symbol"] for p_ in (tc.read_json("positions.json", {}) or {}).get("positions", [])
            if p_.get("status") == "open"}
    held |= {o["symbol"] for o in store0["orders"] if o.get("status") == "PLACED"}
    cands = [c for c in scan["candidates"] if c["symbol"] not in held]
    skipped_held = sorted({c["symbol"] for c in scan["candidates"] if c["symbol"] in held})
    if skipped_held:
        notes.append("skipped %s: already held or placed (manage it with tayyib-broker / tayyib-alerts)"
                     % ", ".join(skipped_held))
    picks = choose(cands, a.mode, a.top)
    syms = [c["symbol"] for c in picks]
    if scan.get("errors"):
        notes.append("%d price downloads failed (first: %s)" % (len(scan["errors"]), scan["errors"][0]["error"][:80]))

    rows, results = [], {}
    if picks:
        # 3. news (feeds HALAL-WATCH and results warnings into the risk check)
        if not a.no_news:
            try:
                nw = run("tayyib-news", "news.py", "--symbols", ",".join(syms), "--hours", 72)
                if nw.get("errors"):
                    notes.append("%d news sources failed (e.g. %s)" % (len(nw["errors"]), nw["errors"][0][:70]))
            except RuntimeError as e:
                notes.append("news step failed: %s" % e)
        # 4. plans, one per stock with its own setup and mode
        for c in picks:
            run("tayyib-exit", "exit.py", "plan", c["symbol"], "--setup", c["setup"], "--mode", c["mode"], "--write")
        # 5. time machine, 6. size, 7. risk, all for today's stocks only
        tm = run("tayyib-timemachine", "timemachine.py", "run", ",".join(syms), "--runs", a.runs, "--write")
        # Size best expectancy first: the risk check fills limits (positions, heat, cash) in file order.
        exp = lambda s: ((tm["results"].get(s) or {}).get("monte_carlo") or {}).get("expectancy_r") or -9
        syms = sorted(syms, key=lambda s: -exp(s))
        # Today's list replaces earlier UNPLACED tickets; placed orders are never touched.
        store = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
        stale = [o for o in store["orders"] if o.get("status") != "PLACED" and o["symbol"] not in syms]
        if stale:
            store["orders"] = [o for o in store["orders"] if o not in stale]
            tc.write_json("orders.json", store)
            notes.append("removed %d earlier unplaced ticket(s) not on today's list: %s"
                         % (len(stale), ", ".join(o["id"] for o in stale)))
        sized = {o["symbol"]: o for o in run("tayyib-budget", "size.py", ",".join(syms), "--write")}
        swaps = ["%s with %s" % (o["replaced"], o["id"]) for o in sized.values()
                 if o.get("replaced") and o["replaced"] != o.get("id")]
        if swaps:
            notes.append("replaced " + "; ".join(swaps))
        # Risk-check the WHOLE file, exactly like a plain check.py, so the statuses here match it.
        by_id = {r["id"]: r for r in run("tayyib-risk", "check.py")}
        risk = {s: by_id.get(o.get("id")) for s, o in sized.items() if o.get("id")}
        plans = (tc.read_json("plan.json", {}) or {}).get("plans", {})
        for c in picks:
            s = c["symbol"]
            pl, o, r = plans.get(s, {}), sized.get(s, {}), (risk.get(s) or {})
            sim = tm["results"].get(s, {})
            if r:
                reasons = ["BLOCK: " + x for x in (r.get("block") or [])] + \
                          ["WARN: " + x for x in sorted(r.get("warn") or [], key=lambda w: "HALAL-WATCH" not in w)]
            else:
                reasons = ["NOT SIZED: " + (o.get("error") or "no plan")]
            reason = reasons[0] if reasons else ""
            row = {
                "symbol": s, "name": c.get("name", ""), "mode": c["mode"], "setup": c["setup"], "score": c["score"],
                "entry": pl.get("entry"), "stop": pl.get("stop"),
                "stop_pct": round((pl["entry"] - pl["stop"]) / pl["entry"] * 100, 1) if pl else None,
                "target": pl.get("target"), "valid_until": pl.get("valid_until"),
                "max_hold_days": pl.get("max_hold_days"),
                "qty": o.get("qty"), "position_rs": o.get("position_value_rs"),
                "loss_at_stop_rs": o.get("loss_at_stop_rs"), "gain_at_target_rs": o.get("gain_at_target_rs"),
                "rr_net": o.get("reward_risk_net"),
                "expectancy_r": (sim.get("monte_carlo") or {}).get("expectancy_r"),
                "past_trades": (sim.get("history") or {}).get("trades"),
                "verdict": sim.get("verdict"), "risk": r.get("status") if r else "NOT SIZED",
                "reason": reason, "reasons": reasons, "order_id": o.get("id"),
            }
            rows.append(row)
            results[s] = {"plan": pl, "order": o, "risk": r, "sim": sim}
    order = {"PASS": 0, "WARN": 1, "BLOCK": 2, "NOT SIZED": 3}
    rows.sort(key=lambda x: (order.get(x["risk"], 4), -(x["expectancy_r"] or -9)))

    today = tc.today_ist().isoformat()
    out = {"date": today, "asof": tc.now_ist().isoformat(timespec="minutes"), "mode": a.mode,
           "capital": cfg["capital"], "risk_per_trade_pct": cfg["max_risk_per_trade_pct"], "broker": cfg["broker"],
           "universe_updated": uni.get("updated"), "scanned": scan["scanned"], "rows": rows, "notes": notes,
           "top_picks": [r["symbol"] for r in rows if r["risk"] == "PASS"][: max(a.picks, 0)]}
    tc.write_json(os.path.join("daily", today + ".json"), out)
    # Paper tracker: record today's list, follow every earlier one on the latest prices, write Excel.
    out["tracker"] = None
    if not a.no_track and os.path.exists(os.path.join(ROOT, "tayyib-tracker", "tracker.py")):
        try:
            run("tayyib-tracker", "tracker.py", "add", "--from-daily", today)
            run("tayyib-tracker", "tracker.py", "update")
            ex = run("tayyib-tracker", "tracker.py", "export")
            rep = run("tayyib-tracker", "tracker.py", "report")
            earlier = [r for r in rep["recent"] if r["date"] < today][:10]
            out["tracker"] = {"xlsx": ex["xlsx"], "all": rep["summary"]["all"], "earlier": earlier}
            tc.write_json(os.path.join("daily", today + ".json"), out)
        except RuntimeError as e:
            notes.append("tracker update failed: %s" % str(e)[:120])
    md = render_md(out)
    with open(tc.path("daily", today + ".md"), "w", encoding="utf-8") as f:
        f.write(md)
    if a.json:
        return tc.print_json(out)
    print(md)


def fmt(x, d=2):
    return "-" if x is None else ("%." + str(d) + "f") % x


def render_md(out):
    L = ["# Halal trade list, %s" % out["date"], "",
         "Capital %s, risk %s%% a trade, %s. Scanned %d halal-compliant stocks (list of %s)."
         % (tc.fmt_rs(out["capital"], 0), out["risk_per_trade_pct"], out["broker"], out["scanned"],
            out["universe_updated"]), ""]
    rows = out["rows"]
    tops = [r for r in rows if r["symbol"] in out.get("top_picks", [])]
    if tops:
        L.append("**Today's top picks** (PASS, best time-machine expectancy first):")
        for r in tops:
            L.append("- **%s** (%s %s): buy above %s, stop %s, target %s, %s shares, risk %s"
                     % (r["symbol"], r["mode"], r["setup"], fmt(r["entry"]), fmt(r["stop"]), fmt(r["target"]),
                        r["qty"], tc.fmt_rs(r["loss_at_stop_rs"], 0)))
        L.append("")
    elif rows:
        L += ["No stock passed every check today. Look at the reasons below; no trade is also a decision.", ""]
    if not rows:
        L += ["No setups armed today. That is a normal result: no trade is also a decision.", ""]
    else:
        L += ["| # | stock | setup | entry | stop | stop% | target | qty | risk Rs | net R:R | time machine | check |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, r in enumerate(rows, 1):
            tmx = "-" if r["expectancy_r"] is None else "%+.2fR %s; %s past trade%s%s" % (
                r["expectancy_r"], short_verdict(r["verdict"]), r["past_trades"],
                "" if r["past_trades"] == 1 else "s", " (too few)" if (r["past_trades"] or 0) < 8 else "")
            L.append("| %d | %s | %s %s | %s | %s | %s | %s | %s | %s | %s | %s | **%s** |" % (
                k, r["symbol"], r["mode"], r["setup"], fmt(r["entry"]), fmt(r["stop"]), fmt(r["stop_pct"], 1),
                fmt(r["target"]), r["qty"] if r["qty"] is not None else "-",
                fmt(r["loss_at_stop_rs"], 0), fmt(r["rr_net"]), tmx, r["risk"]))
        L.append("")
        flagged = [r for r in rows if r["risk"] != "PASS" and r.get("reasons")]
        if flagged:
            L.append("Why not PASS:")
            for r in flagged:
                for why in r["reasons"]:
                    L.append("- %s %s" % (r["symbol"], why))
            L.append("")
        L += ["Entry is a buy-stop: it only buys if price trades up to it, valid until the date in the plan.",
              "Next: `tayyib-broker/ticket.py show SYMBOL` for the exact Kite / Groww steps. Place it yourself "
              "only after you say yes, then record the fill with `ticket.py placed`.", ""]
    t = out.get("tracker")
    if t:
        L.append("## How earlier lists did (paper, nothing bought)")
        if t["earlier"]:
            L += ["| list date | stock | setup | check | status | bought | exit | result |", "|---|---|---|---|---|---|---|---|"]
            for r in t["earlier"]:
                L.append("| %s | %s | %s %s | %s | %s | %s | %s | %s |" % (
                    r["date"], r["symbol"], r["mode"], r["setup"], r.get("check") or "-", r["status"],
                    r.get("filled") or "-", r.get("exited") or "-",
                    "-" if r.get("r") is None else "%+.2fR" % r["r"]))
        else:
            L.append("Nothing tracked from earlier days yet: results appear from the next trading day.")
        s = t["all"]
        L.append("")
        L.append("All tracked so far: %d listed, %d bought, %d closed (%d target, %d stop), win rate %s, "
                 "average %s. Full record: `%s`." % (
                     s["listed"], s["triggered"], s["closed"], s["target"], s["stop"],
                     "-" if s["win_rate_pct"] is None else "%s%%" % s["win_rate_pct"],
                     "-" if s["avg_r"] is None else "%+.2fR" % s["avg_r"], "trader/tracker.xlsx"))
        L.append("")
    for n in out["notes"]:
        L.append("Note: " + n)
    L += ["", tc.DISCLAIMER]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
