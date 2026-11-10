#!/usr/bin/env python3
"""tayyib-daily: today's halal trade list in one command.

Runs the tested skills in order, for today's candidates only:
  halal list check -> scanner -> news -> exit plan -> time machine -> budget -> risk
and prints one table: stock, setup, entry, stop, stop %, target, quantity,
rupee risk, the time machine's verdict, and PASS / WARN / BLOCK with the
first reason. Saves trader/daily/YYYY-MM-DD.md and .json.

Run it after the close (3:30 PM IST). Nothing here places an order: the
list is a set of tickets for you to review, then place yourself.

--email (v0.2.3): run the list exactly as without it, then email it to your own inbox with tayyib-email
(when email.enabled is on and TAYYIB_SMTP_PASSWORD is set). If the list fails, the FAILED email is sent
instead. On a weekend or a holiday in your settings it makes no list and sends nothing ("market closed").
This is what the Windows scheduled task runs (tools/schedule_windows.py); --dir names the trader folder.

v0.2.4: every run re-checks the stocks you hold (tayyib-halal held: held_alerts[] at the top of the list),
shows the market regime (the regime filter is OFF by default), and when the run is after 3:30 PM IST on a
trading day but no scanned stock has a bar for today it treats the market as closed: no new list, no email
(--force runs anyway).
"""
import argparse
import json
import os
import re
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
    p = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))   # child scripts print UTF-8
    if p.returncode != 0:
        raise RuntimeError("%s %s failed: %s" % (skill, " ".join(map(str, args)), (p.stderr or p.stdout).strip()[:900]))
    return json.loads(p.stdout) if want_json else p.stdout


# One setup per stock, swing and delivery alternated in --mode all: in core (v0.2.0) so tayyib-backtest
# picks each day's stocks the same way.
choose = tc.choose_candidates


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
    p.add_argument("--top", type=int, default=None, help="plan at most N stocks, best scores first "
                   "(default: daily.top in config, 10)")
    p.add_argument("--runs", type=int, default=3000, help="time-machine simulations per stock")
    p.add_argument("--no-news", action="store_true", help="skip the news step (faster)")
    p.add_argument("--picks", type=int, default=None, help="how many top PASS stocks to highlight "
                   "(default: daily.picks in config, 3)")
    p.add_argument("--no-rebuild", action="store_true", help="never rebuild the halal list automatically")
    p.add_argument("--no-track", action="store_true", help="do not record the list in the Excel tracker")
    p.add_argument("--risk-preview", action="store_true",
                   help="show what your risk settings mean in rupees (losing streaks, which limit sets the "
                        "quantity) and stop; runs nothing else")
    p.add_argument("--stop-pct", type=float, action="append",
                   help="with --risk-preview: a sample stop distance in %% (repeat for more)")
    p.add_argument("--entry", type=float, default=1000.0, help="with --risk-preview: a sample entry price")
    p.add_argument("--email", action="store_true", help="make the list, then email it to your own inbox "
                   "(tayyib-email: when email is on and TAYYIB_SMTP_PASSWORD is set; the scheduled run)")
    p.add_argument("--dir", default=None, help="with --email: the trader folder to use (sets TAYYIB_DIR)")
    p.add_argument("--force", action="store_true", help="make the list even when no stock has a bar for today "
                   "(the market-closed check)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.email:
        return run_and_email(a, sys.argv[1:] if argv is None else list(argv))
    if a.dir:
        tc.die("--dir is only for --email (otherwise set TAYYIB_DIR)")
    pullback_note = None
    if not a.risk_preview:
        try:                                      # v0.2.6: pullback back on by default; once per folder, before the config
            pullback_note, _ = tc.pullback_migration()
        except OSError as e:
            sys.stderr.write("could not record the v0.2.6 settings notice: %s\n" % e)
    cfg = tc.load_config()
    if a.risk_preview:
        rp = tc.risk_preview(cfg, a.stop_pct or (2, 3, 5, 8, 10, 15), a.entry)
        rp["config_notes"] = tc.config_notes(cfg)
        if a.json:
            return tc.print_json(rp)
        return print(render_risk_preview(rp))
    a.top = cfg["daily"]["top"] if a.top is None else a.top
    a.picks = cfg["daily"]["picks"] if a.picks is None else a.picks
    cfg["daily"]["top"], cfg["daily"]["picks"] = a.top, a.picks      # the snapshot records what was used
    notes = tc.config_notes(cfg)
    banners = [pullback_note] if pullback_note else []    # list-level warnings (a data source failed today)
    K = cfg["daily"]["min_past_trades_for_rank"]

    # 1. halal universe: built on first run, rebuilt automatically once it is a month old
    rebuild_error = None
    uni = tc.load_universe()
    age = tc.universe_age_days(uni) if uni.get("stocks") else None
    every = cfg["halal"].get("auto_rebuild_days") or 0
    if not a.no_rebuild and every and (not uni.get("stocks") or (age is not None and age >= every)):
        why = "first run" if not uni.get("stocks") else "list was %s old" % tc.plural(age, "day")
        if not a.json:
            sys.stderr.write("Rebuilding the halal list (%s): about 5 minutes...\n" % why)
        try:
            b = run("tayyib-halal", "halal.py", "build")
            c = b["counts"]
            notes.append("rebuilt the halal list (%s): %d compliant, %d review, %d excluded, %d unknown"
                         % (why, c["compliant"], c["review"], c["excluded"], c["unknown"]))
            notes += b.get("notes") or []                # where the Nifty 500 list came from (and its age)
        except RuntimeError as e:
            rebuild_error = str(e)[:900]
            notes.append("halal list rebuild failed, using the existing list: %s" % rebuild_error)
        uni = tc.load_universe()
        age = tc.universe_age_days(uni)
    if not uni.get("stocks"):
        if rebuild_error:                                   # v0.2.7: say why, not only "no universe"
            tc.die("could not build the halal list (first run): %s" % rebuild_error)
        tc.die("no halal universe yet: run tayyib-halal/halal.py build first (about 5 minutes, monthly)")
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        notes.append("halal list is %s old: rebuild it (halal.py build)" % tc.plural(age, "day"))
    elif age is not None and age > 35:
        notes.append("halal list is %s old: a monthly rebuild is due" % tc.plural(age, "day"))
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
    today = tc.today_ist().isoformat()
    closed = market_closed(scan, cfg)
    if closed and not a.force:
        log_closed(today, closed)
        if a.json:
            return tc.print_json({"date": today, "market_closed": closed, "rows": []})
        print("market closed (no bars for today): %s. No new list was written; run with --force to make one anyway."
              % closed)
        return 0
    heldchk = held_check(notes, banners)
    regime = regime_today(cfg, scan.get("latest_bar") or today)
    effect = tc.regime_effect(regime, cfg.get("regime"))
    if cfg["regime"]["enabled"] and regime["state"] == "UNKNOWN":
        banners.append("Market regime UNKNOWN today (%s): the regime filter did nothing (it never blocks or allows "
                       "on missing data)." % regime["reason"])
    picks = choose(cands, a.mode, a.top)
    syms = [c["symbol"] for c in picks]
    if scan.get("errors"):
        notes.append("%d price downloads failed (first: %s)" % (len(scan["errors"]), scan["errors"][0]["error"][:80]))

    rows, results = [], {}
    filtered, mn = {}, cfg["daily"].get("min_expectancy_r")
    if picks:
        # 3. news (feeds HALAL-WATCH and results warnings into the risk check)
        if not a.no_news:
            try:
                nw = run("tayyib-news", "news.py", "--symbols", ",".join(syms), "--hours", 72)
                if nw.get("errors"):
                    notes.append("%d news sources failed (e.g. %s)" % (len(nw["errors"]), nw["errors"][0][:70]))
                b = source_banner(nw.get("errors") or [], syms)
                if b:
                    banners.append(b)
            except RuntimeError as e:
                notes.append("news step failed: %s" % e)
                banners.append("News unavailable today (the news step failed): HALAL-WATCH and results checks are "
                               "incomplete for %d of %d stocks." % (len(syms), len(syms)))
        # 4. plans, one per stock with its own setup and mode
        for c in picks:
            run("tayyib-exit", "exit.py", "plan", c["symbol"], "--setup", c["setup"], "--mode", c["mode"], "--write")
        # 5. time machine, 6. size, 7. risk, all for today's stocks only
        tm = run("tayyib-timemachine", "timemachine.py", "run", ",".join(syms), "--runs", a.runs, "--write")
        # Size in rank order: the risk check fills limits (positions, heat, cash) in file order, so this
        # decides what gets BLOCKed. The same key orders the list and the top picks (tc.rank_key): best
        # expectancy first among stocks with >= daily.min_past_trades_for_rank past trades, then by score.
        res = lambda s: tm["results"].get(s) or {}
        score = {c["symbol"]: c["score"] for c in picks}
        syms = sorted(syms, key=lambda s: tc.rank_key((res(s).get("monte_carlo") or {}).get("expectancy_r"),
                                                      (res(s).get("history") or {}).get("trades"), score.get(s), K))
        if mn is not None:
            raw = lambda s: ((tm["results"].get(s) or {}).get("monte_carlo") or {}).get("expectancy_r")
            filtered = {s: raw(s) for s in syms if raw(s) is None or raw(s) < mn}
            syms = [s for s in syms if s not in filtered]
            if filtered:
                notes.append("not sized: %s (time-machine expectancy under daily.min_expectancy_r %s)"
                             % (", ".join(sorted(filtered)), tc._fmt_val(mn)))
        mode_of = {c["symbol"]: c["mode"] for c in picks}
        market_off = {s for s in syms if mode_of.get(s) in effect["block_modes"]}   # empty unless the filter is on
        if market_off:
            syms = [s for s in syms if s not in market_off]
            notes.append("not sized: %s (%s)" % (", ".join(sorted(market_off)), effect["text"]))
        # Today's list replaces earlier UNPLACED tickets; placed orders are never touched.
        store = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
        stale = [o for o in store["orders"] if o.get("status") != "PLACED" and o["symbol"] not in syms]
        if stale:
            store["orders"] = [o for o in store["orders"] if o not in stale]
            tc.write_json("orders.json", store)
            notes.append("removed %d earlier unplaced ticket(s) not on today's list: %s"
                         % (len(stale), ", ".join(o["id"] for o in stale)))
        half = ["--risk-pct", cfg["max_risk_per_trade_pct"] * effect["risk_factor"]] if effect["risk_factor"] != 1 else []
        sized = ({o["symbol"]: o for o in run("tayyib-budget", "size.py", ",".join(syms), "--write", *half)}
                 if syms else {})
        swaps = ["%s with %s" % (o["replaced"], o["id"]) for o in sized.values()
                 if o.get("replaced") and o["replaced"] != o.get("id")]
        if swaps:
            notes.append("replaced " + "; ".join(swaps))
        # Risk-check the WHOLE file, exactly like a plain check.py, so the statuses here match it.
        by_id = {r["id"]: r for r in run("tayyib-risk", "check.py")} if syms else {}
        risk = {s: by_id.get(o.get("id")) for s, o in sized.items() if o.get("id")}
        plans = (tc.read_json("plan.json", {}) or {}).get("plans", {})
        for c in picks:
            s = c["symbol"]
            pl, o, r = plans.get(s, {}), sized.get(s, {}), (risk.get(s) or {})
            sim = tm["results"].get(s, {})
            if r:
                reasons = ["BLOCK: " + x for x in (r.get("block") or [])] + \
                          ["WARN: " + x for x in sorted(r.get("warn") or [], key=lambda w: "HALAL-WATCH" not in w)]
            elif s in filtered:
                reasons = ["FILTERED: time-machine expectancy %s under daily.min_expectancy_r %s"
                           % ("UNKNOWN" if filtered[s] is None else "%+.2fR" % filtered[s], tc._fmt_val(mn))]
            elif s in market_off:
                reasons = ["FILTERED: " + effect["text"]]
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
                "verdict": sim.get("verdict"),
                "ranked_by": "score" if tc.thin_evidence((sim.get("history") or {}).get("trades"), K) else "expectancy",
                "expectancy_use": tc.expectancy_label((sim.get("monte_carlo") or {}).get("expectancy_r"),
                                                      (sim.get("history") or {}).get("trades"), K),
                "stop_capped": any(x.get("stop_capped") for x in (pl.get("why") or [])),
                "risk": r.get("status") if r else ("FILTERED" if s in filtered or s in market_off else "NOT SIZED"),
                "reason": reason, "reasons": reasons, "order_id": o.get("id"),
            }
            row["why"] = build_why(c, pl, o, r, sim, reasons, mn if s in filtered else None,
                                   filtered.get(s), K)
            if effect["active"]:                     # v0.2.4: the regime filter decided (only when it is on)
                for x in row["why"]:
                    if x["group"] == "RISK" and x["check"] == "result" and s in market_off:
                        x["value"] = "FILTERED"
                row["why"].append(tc.why_item("RISK", "MARKET", regime["state"], None, None, s not in market_off,
                                              None, effect["text"]))
            rows.append(row)
            results[s] = {"plan": pl, "order": o, "risk": r, "sim": sim}
    order = {"PASS": 0, "WARN": 1, "BLOCK": 2, "FILTERED": 3, "NOT SIZED": 4}
    rows.sort(key=lambda x: (order.get(x["risk"], 4),) + tc.rank_key(x["expectancy_r"], x["past_trades"],
                                                                     x["score"], K))

    ov_note = tc.old_overrides_note()                      # v0.2.7: an old overrides file is never read
    if ov_note and ov_note not in notes:
        notes.append(ov_note)
    banner = tc.halal_banner(cfg, uni)
    out = {"banner": banner} if banner else {}
    out["banners"] = banners
    out.update({"date": today, "asof": tc.now_ist().isoformat(timespec="minutes"), "mode": a.mode,
           "capital": cfg["capital"], "risk_per_trade_pct": cfg["max_risk_per_trade_pct"], "broker": cfg["broker"],
           "universe_updated": uni.get("updated"), "scanned": scan["scanned"], "rows": rows, "notes": notes,
           "top_picks": [r["symbol"] for r in rows if r["risk"] == "PASS"][: max(a.picks, 0)],
           "settings": tc.settings_snapshot(cfg)})
    out["held_alerts"] = heldchk.get("alerts") or []         # v0.2.4: stocks you hold that stopped passing (or near)
    out["held_check"] = {k: heldchk.get(k) for k in ("checked", "errors", "note", "recheck_days")}
    out["held_check"]["held"] = len(heldchk.get("held") or [])
    out["regime"] = dict(regime, enabled=bool(cfg["regime"]["enabled"]), action=cfg["regime"]["action"],
                         applied=effect["active"], text=tc.regime_text(regime, cfg["regime"]["action"]
                                                                       if effect["active"] else None),
                         filtered=sorted(market_off) if picks else [])
    tc.write_json(os.path.join("daily", today + ".json"), out)
    if pullback_note:
        tc.pullback_banner_shown(today)
    # Paper tracker: record today's list, follow every earlier one on the latest prices, write Excel.
    out["tracker"] = None
    if not a.no_track and os.path.exists(os.path.join(ROOT, "tayyib-tracker", "tracker.py")):
        try:
            run("tayyib-tracker", "tracker.py", "add", "--from-daily", today)
            run("tayyib-tracker", "tracker.py", "update")
            ex = run("tayyib-tracker", "tracker.py", "export")
            rep = run("tayyib-tracker", "tracker.py", "summary")
            earlier = [r for r in rep["recent"] if r["date"] < today][:10]
            out["tracker"] = {"xlsx": ex["xlsx"], "all": rep["summary"]["all"], "earlier": earlier}
            tc.write_json(os.path.join("daily", today + ".json"), out)
        except RuntimeError as e:
            notes.append("tracker update failed: %s" % str(e)[:120])
        # v0.2.9: the paper account (PASS picks only) every run; the shareable report when report.every_days have
        # passed. Measurement only: the list above is already decided and saved.
        try:
            pr = run("tayyib-tracker", "tracker.py", "report", "--if-due")
            out["paper"] = {"totals": pr.get("totals"), "report": pr.get("md") if pr.get("written") else None,
                            "next_report": pr.get("next_due")}
            tc.write_json(os.path.join("daily", today + ".json"), out)
        except RuntimeError as e:
            notes.append("paper account update failed: %s" % str(e)[:120])
    md = render_md(out, uni)
    with open(tc.path("daily", today + ".md"), "w", encoding="utf-8") as f:
        f.write(md)
    if a.json:
        return tc.print_json(out)
    print(md)


def without_email_args(argv):
    """argv minus --email and --dir PATH: the plain run --email wraps (so its decisions are the same)."""
    out, skip = [], False
    for x in argv:
        if skip:
            skip = False
        elif x == "--email":
            continue
        elif x == "--dir":
            skip = True
        elif not x.startswith("--dir="):
            out.append(x)
    return out


def run_and_email(a, argv):
    """The list (this script, unchanged, as a child), then `email_report.py send --scheduled`."""
    if a.dir:
        d = os.path.abspath(a.dir)
        os.environ["TAYYIB_DIR"] = d
        os.chdir(os.path.dirname(d))
    cfg = tc.load_config()
    email = script("tayyib-email", "email_report.py")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    today = tc.today_ist()
    if not tc.is_trading_day(today, cfg):
        print("market closed on %s (weekend or a holiday in your settings): no list, no email" % today.isoformat())
        return subprocess.run([sys.executable, email, "send", "--scheduled"], env=env).returncode
    p = subprocess.run([sys.executable, os.path.abspath(__file__)] + without_email_args(argv), env=env,
                       stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    sys.stderr.write(p.stderr or "")
    failed = None
    if p.returncode != 0:
        tail = [x.strip() for x in (p.stderr or "").splitlines() if x.strip()]
        failed = "exit code %d: %s" % (p.returncode, tail[-1][:300] if tail else "no output")
    q = subprocess.run([sys.executable, email, "send", "--scheduled"] + (["--run-failed", failed] if failed else []),
                       env=env)          # email_report.py reads daily/closed.json: a market-closed day sends nothing
    return p.returncode or q.returncode


CLOSE_MIN = 15 * 60 + 30


def market_closed(scan, cfg, now=None):
    """C3 (v0.2.4): the reason the market looks closed today, or None. Only after 3:30 PM IST on a day that is a
    trading day in your settings (weekends and listed holidays are handled before), when the scan read bars but
    none is dated today: a holiday missing from your settings. A scan that read no bars at all is a failure, not
    a holiday (None)."""
    now = now or tc.now_ist()
    d = now.date()
    if not tc.is_trading_day(d, cfg) or now.hour * 60 + now.minute < CLOSE_MIN:
        return None
    latest = scan.get("latest_bar")
    if latest is None or latest >= d.isoformat():
        return None
    return "after 3:30 PM IST no scanned stock has a bar for %s (latest %s)" % (d.isoformat(), latest)


def log_closed(date, why):
    """trader/daily/closed.json: the days the market-closed check found no bars (tayyib-email sends nothing)."""
    c = tc.read_json(os.path.join("daily", "closed.json"), {"days": {}}) or {"days": {}}
    c.setdefault("days", {})[date] = "market closed (no bars for today): %s" % why
    tc.write_json(os.path.join("daily", "closed.json"), c)


def held_check(notes, banners):
    """tayyib-halal held --write: re-checks the stocks you hold. Never stops the list: a failure is a banner."""
    try:
        h = run("tayyib-halal", "halal.py", "held", "--write")
    except (RuntimeError, ValueError) as e:
        banners.append("The halal re-check of the stocks you hold failed today (%s): check them yourself."
                       % str(e)[:200])
        return {"alerts": [], "errors": [str(e)[:200]]}
    if h.get("errors"):
        notes.append("held-stock halal re-check could not verify %s" % "; ".join(h["errors"])[:300])
    return h


def regime_today(cfg, date):
    """The regime on the signal day from the configured index (shown even when the filter is off)."""
    r = cfg.get("regime") or {}
    idx = r.get("index") or "^NSEI"
    try:
        bars, _ = tc.get_daily_bars(idx)
    except tc.FetchError as e:
        st = tc.regime_state([], date, r.get("rule"), idx)
        st["reason"] = "the %s could not be fetched: %s" % (st["name"], str(e)[:160])
        return st
    return tc.regime_state(bars, date, r.get("rule") or "close_below_200dma", idx)


def held_md(alerts):
    """The held-stock halal alerts, first in the .md."""
    if not alerts:
        return []
    L = ["## Stocks you hold: halal re-check", ""]
    for x in alerts:
        L.append("**%s: %s** (%d shares; at buy %s%s, now %s; data %s, %s)%s" % (
            x["title"], x["symbol"], x["qty"], x["status_at_buy"], ", backfilled" if x.get("backfilled") else "",
            x["status_now"], x.get("data_date") or "UNKNOWN", x.get("source") or "UNKNOWN source",
            "" if (x.get("alert") or {}).get("new") else " (open since %s)" % (x.get("alert") or {}).get("since")))
        for r in x.get("ratios") or []:
            if r["over"] or r["near"] or x["level"] == "BLOCK":
                L.append("- %s: %s -> %s (limit %s)%s" % (
                    r["check"], "-" if r["old"] is None else "%.2f%%" % r["old"],
                    "UNKNOWN" if r["new"] is None else "%.2f%%" % r["new"],
                    "-" if r["limit"] is None else "%.0f%%" % r["limit"],
                    " OVER" if r["over"] else " near the limit" if r["near"] else ""))
        for f in x.get("failed") or []:
            L.append("- failed: %s" % f)
        if x["level"] == "UNKNOWN":
            L.append("- could not verify: %s. Not read as compliant or as non-compliant." % (x.get("reason") or "no data"))
        if x["level"] == "BLOCK":
            t, p = x["sell_ticket"], x["purify"]
            L += ["- " + x["wording"], "- Sell %s. SELL ticket %s: CNC, %d shares, you place it:" % (x["sell_by"], t["id"], t["qty"])]
            L += ["  %d. %s" % (k, step) for k, step in enumerate(t["steps"], 1)]
            L.append("- Purification (%s): %s; `%s`" % (
                p["label"], "UNKNOWN" if p["total_rs"] is None else tc.fmt_rs(p["total_rs"]), p["command"]))
        L.append("")
    return L


def fmt(x, d=2):
    return "-" if x is None else ("%." + str(d) + "f") % x


def links_md(sym, uni):
    """'Check announcements yourself: [NSE company page](...) · [BSE search](...) (search for ISIN ...)'.
    Links the user opens; the tool never fetches them."""
    rec = ((uni or {}).get("stocks") or {}).get(sym)
    parts = ["[%s](%s)%s" % (x["label"], x["url"], " (%s)" % x["hint"] if x["hint"] else "")
             for x in tc.manual_links(sym, rec)]
    return "  Check announcements yourself: " + " · ".join(parts)


def render_md(out, uni=None):
    banners = ["**%s**" % b for b in out.get("banners") or []] + ([""] if out.get("banners") else [])
    L = ([out["banner"], ""] if out.get("banner") else []) + held_md(out.get("held_alerts")) + banners + \
        ["# Halal trade list, %s" % out["date"], "",
         "Capital %s, risk %s%% a trade, %s. Scanned %d halal-compliant stocks (list of %s)."
         % (tc.fmt_rs(out["capital"], 0), out["risk_per_trade_pct"], out["broker"], out["scanned"],
            out["universe_updated"]), ""]
    rg = out.get("regime")
    if rg:
        L += [regime_line(rg), ""]
    rows = out["rows"]
    tops = [r for r in rows if r["symbol"] in out.get("top_picks", [])]
    if tops:
        k = ((out.get("settings") or {}).get("values") or {}).get("daily", {}).get("min_past_trades_for_rank", 8)
        L.append("**Today's top picks** (PASS; best time-machine expectancy first among stocks with at least %d "
                 "past trades, then the rest by setup score):" % k)
        for r in tops:
            L.append("- **%s** (%s %s): buy above %s, stop %s, target %s, %s shares, risk %s"
                     % (r["symbol"], r["mode"], r["setup"], fmt(r["entry"]), fmt(r["stop"]), fmt(r["target"]),
                        r["qty"], tc.fmt_rs(r["loss_at_stop_rs"], 0)))
            L += why_md(r.get("why") or [], links_md(r["symbol"], uni))
        L.append("")
    elif rows:
        L += ["No stock passed every check today. Look at the reasons below; no trade is also a decision.", ""]
    if not rows:
        L += ["No setups armed today. That is a normal result: no trade is also a decision.", ""]
    else:
        kk = ((out.get("settings") or {}).get("values") or {}).get("daily", {}).get("min_past_trades_for_rank", 8)
        L += ["| # | stock | setup | entry | stop | stop% | target | qty | risk Rs | net R:R | time machine | check |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, r in enumerate(rows, 1):
            tmx = "-" if r["expectancy_r"] is None else "%s %s%s" % (
                tc.tm_label(r["expectancy_r"], r["past_trades"], kk), short_verdict(r["verdict"]),
                ", information only: ranked by score" if r.get("ranked_by") == "score" else "")
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


def _placeholder(group, why):
    return tc.why_item(group, "not checked", None, None, None, None, None, why)


def source_banner(errors, syms):
    """One list-level line when NSE announcements or Google News failed for any of today's stocks
    (news.py errors look like "nse SYM: ..." and "google SYM: ..."), saying why and what to do:
    "Exchange filings unavailable today (NSE refused automated access (HTTP 403)). HALAL-WATCH and results
    checks are incomplete for 10 of 10 stocks: check the announcements yourself for any stock you plan to buy." """
    names = (("nse", "Exchange filings", "NSE"), ("google", "Google News", "Google News"))
    failed, hit, why = set(), [], []
    for key, label, who in names:
        mine = [e for e in errors if e.startswith(key + " ") and e.split(":", 1)[0][len(key) + 1:] in set(syms)]
        if not mine:
            continue
        hit.append(label)
        failed |= {e.split(":", 1)[0][len(key) + 1:] for e in mine}
        reasons = [tc.fetch_reason(e.split(":", 1)[1].strip(), who) for e in mine]
        first = [r for r in reasons if not r.startswith("not tried")] or reasons
        why.append(max(set(first), key=first.count))
    if not hit:
        return None
    return ("%s unavailable today (%s). HALAL-WATCH and results checks are incomplete for %d of %d stocks: check the "
            "announcements yourself for any stock you plan to buy." % (" and ".join(hit), "; ".join(why),
                                                                      len(failed), len(syms)))


def build_why(c, pl, o, r, sim, reasons, min_exp=None, exp_value=None, min_trades=8):
    """why[] for one daily row, put together from what each step recorded when it decided:
    the scanner (HALAL, LIQUIDITY, SETUP), the exit plan (PLAN), the risk check (HALAL at check
    time, NEWS, PLAN net R:R, HISTORY, RISK). Nothing is recomputed here."""
    sw, rw = c.get("why") or [], (r or {}).get("why") or []
    pick = lambda items, g: [dict(x) for x in items if x.get("group") == g]
    first = reasons[0] if reasons else ""
    why = pick(sw, "HALAL") + pick(rw, "HALAL") + pick(sw, "LIQUIDITY") + pick(sw, "SETUP")
    if not sw:
        why.append(_placeholder("SETUP", "UNKNOWN: the scan did not record its checks (scan.json from before "
                                         "v0.1.5)"))
    why += pick(rw, "NEWS") if r else [_placeholder("NEWS", "the risk check did not run: " + first)]
    why += [dict(x) for x in (pl or {}).get("why") or []] or [_placeholder("PLAN", "no plan")]
    if r:
        why += pick(rw, "PLAN") + pick(rw, "HISTORY")
    else:
        mc, hs = (sim or {}).get("monte_carlo") or {}, (sim or {}).get("history") or {}
        why.append(tc.why_item("HISTORY", "time-machine expectancy after charges", mc.get("expectancy_r"),
                               min_exp, ">=" if min_exp is not None else None,
                               (False if exp_value is None or exp_value < min_exp else True)
                               if min_exp is not None else None, "R",
                               "daily.min_expectancy_r: not sized" if min_exp is not None
                               else "not checked: " + first))
        why.append(tc.why_item("HISTORY", "past trades of this setup on this stock", hs.get("trades"), min_trades, ">=",
                               None, "trades", "not checked: " + first))
    if o and o.get("qty"):
        why.append(tc.why_item("RISK", "quantity set by", o.get("binding_limit"), None, None, True, None,
                               "%d shares; risk budget %s" % (o["qty"], tc.fmt_rs(o.get("budget_rs"), 0))))
    if r:
        why += pick(rw, "RISK")
        if not any(x["check"] == "result" for x in why):
            why.append(tc.why_item("RISK", "result", r.get("status"), None, None, r.get("status") == "PASS",
                                   None, first or "every check passed"))
    else:
        why.append(tc.why_item("RISK", "result", "FILTERED" if min_exp is not None else "NOT SIZED", None, None,
                               False, None, first))
    for g in tc.WHY_GROUPS:
        if not any(x["group"] == g for x in why):
            why.append(_placeholder(g, "UNKNOWN: nothing was recorded for this group"))
    rank = {g: k for k, g in enumerate(tc.WHY_GROUPS)}
    return sorted(why, key=lambda x: rank.get(x["group"], 99))


OPS = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "="}


def why_value(v, unit):
    if v is None:
        return "UNKNOWN"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if unit == "Rs":
            return tc.fmt_rs(v, 0 if abs(v) >= 1000 else 2)
        if unit == "%":
            return "%.2f%%" % v
        if unit == "R":
            return "%.2fR" % v
        if isinstance(v, int):
            return str(v)
        return "%.2f" % v
    return str(v)


def why_text(it, with_note=False):
    s = "%s %s" % (it["check"], why_value(it["value"], it.get("unit")))
    if it.get("op") and it.get("limit") is not None:
        s += " %s %s" % (OPS.get(it["op"], it["op"]), why_value(it["limit"], it.get("unit")))
    if it.get("ok") is False:
        s += " (no)"
    note = it.get("note") or ""
    if note.startswith("UNKNOWN: "):
        note = note[len("UNKNOWN: "):]
    if note and (with_note or it.get("ok") is not True):
        s += " (%s)" % note
    return s


def news_md(x):
    """'Media news: none flagged (...)', 'Exchange filings (NSE): Not available: NSE blocks automated access
    -> check yourself', '...: flagged: <headline> (...)' or '...: UNKNOWN (...)'."""
    note = re.sub(r"^UNKNOWN: ", "", x.get("note") or "")
    if x.get("op") == tc.NA_OP:
        return "%s: %s: NSE blocks automated access → check yourself" % (x["check"], tc.NOT_AVAILABLE)
    if x.get("ok") is False:
        return "%s: flagged: %s (%s)" % (x["check"], x["value"], note)
    if x.get("ok") is True:
        return "%s: ✓ %s (%s)" % (x["check"], x["value"], note)
    return "%s: UNKNOWN (%s)" % (x["check"], note)


regime_line = tc.regime_line


def why_md(why, links=None):
    """A compact Why: block for the daily .md (C1, v0.2.4): decision lines first, one line per group; then the
    information-only lines ("info:"), then UNKNOWN lines with the "check yourself" links. The full list is in
    the .json."""
    L = ["  - Why:"]
    dec = [x for x in why if tc.why_tier(x) == 0]
    news = [x for x in why if x["group"] == "NEWS" and x["check"] in (tc.NEWS_MEDIA, tc.NEWS_FILINGS)]
    info = [x for x in why if tc.why_tier(x) == 1 and x not in news]
    unk = [x for x in why if tc.why_tier(x) == 2 and x not in news]
    late_news = news and min(tc.why_tier(x) for x in news) > 0
    for g in tc.WHY_GROUPS:
        if g == "NEWS" and news and not late_news:
            L.append("    - NEWS:")
            L += ["      - %s" % news_md(x) for x in news]
            continue
        items = [x for x in dec if x["group"] == g and x not in news]
        if not items:
            continue
        if g == "SETUP":
            items = [x for x in items if x["check"] != "score"]
        if g == "RISK":
            items = [x for x in items if x["ok"] is not True or x["check"] in ("result", "quantity set by")]
        L.append("    - %s: %s" % (g, "; ".join(why_text(x, with_note=x["check"] in ("result",) or
                                                         x["value"] is None) for x in items)))
    if info:
        L.append("    - info (information only, decides nothing): %s"
                 % "; ".join("%s: %s" % (x["group"], why_text(x, with_note=True).replace(" (no)", ""))
                             for x in info))
    if late_news:
        L.append("    - NEWS:")                          # v0.1.10: one line per source, Media news / Exchange filings
        L += ["      - %s" % news_md(x) for x in news]
    if unk:
        L.append("    - UNKNOWN (check yourself): %s"
                 % "; ".join("%s: %s" % (x["group"], why_text(x, with_note=True)) for x in unk))
    if links:
        L.append("  " + links.strip())
    return L


def render_risk_preview(rp):
    L = ["Risk preview: capital %s, risk %s%% a trade = %s lost when a stop is hit (charges included in "
         "tayyib-budget)." % (tc.fmt_rs(rp["capital"], 0), tc._fmt_val(rp["risk_per_trade_pct"]),
                              tc.fmt_rs(rp["risk_per_trade_rs"], 0)),
         "Losses in a row, each one %.2f%% of what is left:" % rp["effective_risk_pct"]]
    for x in rp["losing_streaks"]:
        L.append("  %2d losses: down %.2f%%, %s left (%s lost)" % (x["losses"], x["drawdown_pct"],
                                                                  tc.fmt_rs(x["capital_left_rs"], 0),
                                                                  tc.fmt_rs(x["lost_rs"], 0)))
    L.append("Max position %s%% = %s. %s" % (tc._fmt_val(rp["max_position_pct"]), tc.fmt_rs(rp["max_position_rs"], 0),
                                            rp["explain"]))
    L.append("  %6s %10s %14s %5s %9s %12s %12s" % ("stop%", "qty(risk)", "qty(position)", "qty", "binding",
                                                   "position", "loss at stop"))
    for x in rp["samples"]:
        L.append("  %6.1f %10d %14d %5d %9s %12s %12s" % (x["stop_pct"], x["qty_by_risk"], x["qty_by_position"],
                                                         x["qty"], x["binding"], tc.fmt_rs(x["position_rs"], 0),
                                                         tc.fmt_rs(x["loss_at_stop_rs"], 0)))
    L.append("(sample entry %s) %s" % (tc.fmt_rs(rp["samples"][0]["entry"] if rp["samples"] else 0, 0), rp["note"]))
    if rp.get("warning"):
        L.append("Warning: " + rp["warning"])
    for n in rp.get("config_notes") or []:
        L.append(n)
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
