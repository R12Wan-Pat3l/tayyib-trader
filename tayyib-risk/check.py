#!/usr/bin/env python3
"""tayyib-risk: PASS / WARN / BLOCK every sized order before it can become a ticket.

Hard rules (cannot be configured away): CNC delivery only, BUY to open,
no short selling, no F&O, no margin, halal-compliant stocks only.
Limits from config: loss at stop, position size, cash, open positions,
portfolio heat (total open risk), positions per industry, net reward:risk,
plan still valid, halal list freshness, HALAL-WATCH news.
Updates trader/orders.json statuses and writes trader/risk.json.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


REQUIRED = ("id", "symbol", "side", "product", "qty", "trigger_price", "stop", "target")


def news_why(sym, news, today=None):
    """NEWS items for one stock from trader/news.json, in two lines (v0.1.10, display only):

    - "Media news" (Google News India for this stock + the market RSS feeds): one ok=False item per flagged
      headline (HALAL-WATCH, or results news: the same headlines that raise the risk check's WARNs);
      otherwise ok=True "none flagged"; UNKNOWN (ok=None) when Google News failed for this stock or no media
      source answered, because a flagged headline there would have been missed.
    - "Exchange filings (NSE)" (NSE corporate announcements, incl. board-meeting notices): flagged items,
      "none flagged", or, when NSE refused automated access, value "Not available" with op "not_available"
      and ok=None ("check yourself"; never a pass). Any other NSE failure is UNKNOWN.

    The warn[] list (and so PASS / WARN / BLOCK) is decided in check_order, not here."""
    W = tc.why_item
    MEDIA, FILINGS = tc.NEWS_MEDIA, tc.NEWS_FILINGS
    syms = (news or {}).get("symbols")
    if not news or syms is None or sym not in syms:
        why = "UNKNOWN: no news fetched for %s (news step skipped or failed)" % sym
        return [W("NEWS", MEDIA, None, None, None, None, None, why),
                W("NEWS", FILINGS, None, None, None, None, None, why)]
    asof, hours = news.get("asof"), news.get("hours")
    window = "last %s hours" % tc._fmt_val(hours) if hours is not None else "the news window"
    when = "news of %s" % (asof or "UNKNOWN date")
    if asof and today and asof[:10] < today:
        when += ", not today's"
    items = syms.get(sym) or []
    src = ((news.get("sources") or {}).get(sym))
    feeds = news.get("feeds") or {}
    errs = news.get("errors") or []
    old_err = {k: next((e.split(": ", 1)[-1] for e in errs if e.startswith("%s %s:" % (k, sym))), None)
               for k in ("google", "nse")}                        # news.json written before v0.1.9
    if src is None:
        g_fail, n_fail = old_err["google"], old_err["nse"]
        g_on, n_on = True, True
        f_ok, f_bad = None, {}
    else:
        g_fail = (src.get("failed") or {}).get("Google News")
        n_fail = (src.get("failed") or {}).get("NSE announcements")
        g_on = g_fail is not None or "Google News" in (src.get("answered") or [])
        n_on = n_fail is not None or "NSE announcements" in (src.get("answered") or [])
        f_ok, f_bad = feeds.get("answered") or [], feeds.get("failed") or {}

    def flags(check, mine):
        out = []
        for it in mine:
            what = []
            if it.get("halal_watch"):
                what.append("HALAL-WATCH: %s" % ", ".join(it["halal_watch"]))
            if "results" in it.get("tags", []):
                what.append("results news in the window: gaps are likely")
            if what:
                out.append(W("NEWS", check, it["title"], None, None, False, None, "%s: WARN (%s, %s)" % (
                    "; ".join(what), it.get("source") or "?", it.get("published") or "no date")))
        return out

    def n_text(n, word):
        return "%d %s%s" % (n, word, "" if n == 1 else "s")

    out = []
    # Media news
    media = [it for it in items if it.get("source") != "NSE announcement"]
    answered = (["Google News"] if g_on and not g_fail else []) + (
        [n_text(len(f_ok), "RSS feed")] if f_ok else [])
    failed = (["Google News: %s" % g_fail] if g_fail else []) + ["%s: %s" % kv for kv in f_bad.items()]
    tail = "%s%s" % ("; answered: " + ", ".join(answered) if answered else "",
                     "; failed: " + "; ".join(failed) if failed else "")
    got = flags(MEDIA, media)
    if got:
        out += got
    elif g_fail or (src is not None and not answered):
        out.append(W("NEWS", MEDIA, None, None, None, None, None,
                     "UNKNOWN: %s; %s from the others, none flagged%s" % (
                         "Google News failed for this stock" if g_fail else "no media source answered",
                         n_text(len(media), "headline"), tail)))
    else:
        out.append(W("NEWS", MEDIA, "none flagged", None, None, True, None, "%s in the %s checked (%s%s)" % (
            n_text(len(media), "headline"), window, when, tail)))
    # Exchange filings (NSE)
    filings = [it for it in items if it.get("source") == "NSE announcement"]
    if not n_on:
        out.append(W("NEWS", FILINGS, "not checked", None, None, None, None,
                     "not checked: NSE announcements are turned off in Settings; check yourself"))
    elif n_fail and tc.nse_blocked(n_fail):
        plain = n_fail if str(n_fail).startswith(("NSE ", "not tried")) else tc.fetch_reason(n_fail, "NSE")
        out.append(W("NEWS", FILINGS, tc.NOT_AVAILABLE, None, tc.NA_OP, None, None,
                     "NSE blocks automated access \u2192 check yourself (%s)" % plain))
    elif n_fail:
        out.append(W("NEWS", FILINGS, None, None, None, None, None,
                     "UNKNOWN: NSE announcements failed (%s)" % n_fail))
    else:
        got = flags(FILINGS, filings)
        out += got or [W("NEWS", FILINGS, "none flagged", None, None, True, None,
                         "%s in the %s checked (%s)" % (n_text(len(filings), "announcement"), window, when))]
    return out


def check_order(o, cfg, positions, uni, news, extra_heat=0.0, extra_count=0, extra_ind=None, extra_value=0.0,
                sim=None):
    """PASS / WARN / BLOCK for one order -> {id, symbol, status, block[], warn[], ok[], why[]}.
    why[] records every check with the value used and its limit, at the moment it is decided."""
    W = tc.why_item
    block, warn, ok, why = [], [], [], []
    missing = [k for k in REQUIRED if o.get(k) in (None, "")]
    if missing:
        return {"id": o.get("id", "?"), "symbol": o.get("symbol", "?"), "status": "BLOCK",
                "block": ["order is missing %s: re-run tayyib-budget --write" % ", ".join(missing)],
                "warn": [], "ok": [],
                "why": [W("RISK", "order fields", ", ".join(missing), None, None, False, None, "missing: BLOCK")]}
    holdings = {}
    for p in positions:
        if p.get("status") == "open":
            holdings[p["symbol"]] = holdings.get(p["symbol"], 0) + p["qty"]
    hard = tc.guard_order(o, holdings)
    block += ["hard rule: " + v for v in hard]
    why.append(W("RISK", "hard rules (CNC, BUY to open, no F&O, no margin)", "; ".join(hard) or "none broken",
                 None, None, not hard, None, "BLOCK" if hard else None))

    h = tc.halal_status(o["symbol"], uni)
    if not uni.get("stocks"):
        block.append("no halal universe: run tayyib-halal build")
        why.append(W("HALAL", "halal status at the risk check", None, "compliant", "==", None, None,
                     "UNKNOWN: no halal list: BLOCK"))
    elif h["status"] == "compliant":
        ok.append("halal: compliant (%s)" % h.get("source", ""))
        why.append(W("HALAL", "halal status at the risk check", "compliant", "compliant", "==", True, None,
                     h.get("source") or None))
    elif h["status"] == "review" and cfg["halal"]["allow_review"]:
        warn.append("halal: under review, allowed by config: %s" % "; ".join(h.get("reasons", [])[:2]))
        why.append(W("HALAL", "halal status at the risk check", "review", "compliant", "==", False, None,
                     "WARN: allowed by halal.allow_review (%s)" % (cfg.get("_halal_loosened") or "no note")))
    else:
        # hard rule: anything not compliant is blocked; no config key switches this off
        block.append("halal: %s (%s)" % (h["status"], "; ".join(h.get("reasons", [])[:2])))
        why.append(W("HALAL", "halal status at the risk check", h["status"], "compliant", "==", False, None,
                     "BLOCK"))
    age = tc.universe_age_days(uni)
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        warn.append("halal list is %s old (max %s): rebuild it" % (tc.plural(age, "day"),
                                                                        tc.plural(cfg["halal"]["list_max_age_days"], "day")))
    why.append(W("RISK", "halal list age", age, cfg["halal"]["list_max_age_days"], "<=",
                 None if age is None else not age > cfg["halal"]["list_max_age_days"], "days",
                 "WARN when older" if age is not None else "UNKNOWN: the list has no build date"))

    budget = cfg["capital"] * cfg["max_risk_per_trade_pct"] / 100.0
    if cfg.get("max_risk_per_trade_rs"):
        budget = min(budget, float(cfg["max_risk_per_trade_rs"]))
    loss = o.get("loss_at_stop_rs", 0)
    (ok if loss <= budget + 0.01 else block).append(
        "loss at stop %s vs max %s" % (tc.fmt_rs(loss), tc.fmt_rs(budget)))
    why.append(W("RISK", "loss at the stop incl. charges", o.get("loss_at_stop_rs"), round(budget, 2), "<=",
                 None if o.get("loss_at_stop_rs") is None else loss <= budget + 0.01, "Rs",
                 "%s%% of capital%s" % (tc._fmt_val(cfg["max_risk_per_trade_pct"]),
                                       ", capped at %s" % tc.fmt_rs(cfg["max_risk_per_trade_rs"], 0)
                                       if cfg.get("max_risk_per_trade_rs") else "")))
    pv = o["qty"] * o["trigger_price"]
    maxpv = cfg["capital"] * cfg["max_position_pct"] / 100.0
    (ok if pv <= maxpv + 0.01 else block).append(
        "position %s vs max %s" % (tc.fmt_rs(pv), tc.fmt_rs(maxpv)))
    why.append(W("RISK", "position size", pv, maxpv, "<=", pv <= maxpv + 0.01, "Rs",
                 "%s%% of capital max" % tc._fmt_val(cfg["max_position_pct"])))
    open_pos = [p for p in positions if p.get("status") == "open"]
    invested = sum(p["qty"] * p["entry"] for p in open_pos)
    cash = cfg["cash_available"] if cfg.get("cash_available") is not None else cfg["capital"] - invested
    cash -= extra_value
    need = pv + o.get("buy_charges_rs", 0)
    (ok if need <= cash + 0.01 else block).append("needs %s, cash %s" % (tc.fmt_rs(need), tc.fmt_rs(cash)))
    why.append(W("RISK", "cash needed (after earlier tickets)", need, cash, "<=", need <= cash + 0.01, "Rs"))
    n = len(open_pos) + extra_count
    (ok if n < cfg["max_open_positions"] else block).append(
        "open positions %d (max %d)" % (n, cfg["max_open_positions"]))
    why.append(W("RISK", "open positions + approved tickets before this one", n, cfg["max_open_positions"], "<",
                 n < cfg["max_open_positions"], "positions"))
    heat = sum(max(0.0, (p["entry"] - p["stop"]) * p["qty"]) for p in open_pos) + extra_heat
    heat_new = (heat + loss) / cfg["capital"] * 100
    (ok if heat_new <= cfg["max_portfolio_heat_pct"] + 1e-9 else block).append(
        "portfolio heat %.2f%% after this trade (max %.1f%%)" % (heat_new, cfg["max_portfolio_heat_pct"]))
    why.append(W("RISK", "portfolio heat after this trade", heat_new, cfg["max_portfolio_heat_pct"], "<=",
                 heat_new <= cfg["max_portfolio_heat_pct"] + 1e-9, "%", "total loss if every open stop is hit"))
    ind = h.get("industry") or ""
    if ind:
        same = sum(1 for p in open_pos if tc.halal_status(p["symbol"], uni).get("industry") == ind)
        same += (extra_ind or {}).get(ind, 0)
        (ok if same < cfg["max_positions_per_industry"] else block).append(
            "%d open in %s (max %d)" % (same, ind, cfg["max_positions_per_industry"]))
        why.append(W("RISK", "positions in %s before this one" % ind, same, cfg["max_positions_per_industry"], "<",
                     same < cfg["max_positions_per_industry"], "positions"))
    else:
        why.append(W("RISK", "positions in the same industry", None, cfg["max_positions_per_industry"], "<", None,
                     "positions", "UNKNOWN: no industry in the halal list, so this limit was not checked"))
    rr = o.get("reward_risk_net") or 0
    (ok if rr >= cfg["min_reward_risk"] else block).append(
        "net reward:risk %.2f (min %.1f)" % (rr, cfg["min_reward_risk"]))
    why.append(W("PLAN", "net reward:risk after charges", o.get("reward_risk_net"), cfg["min_reward_risk"], ">=",
                 None if o.get("reward_risk_net") is None else rr >= cfg["min_reward_risk"], "R"))
    vu = o.get("valid_until")
    if vu and tc.today_ist() > tc.parse_date(vu):
        block.append("plan expired on %s: re-scan" % vu)
    why.append(W("RISK", "plan valid until", vu, tc.today_ist().isoformat(), ">=",
                 None if not vu else not tc.today_ist() > tc.parse_date(vu), "date",
                 None if vu else "UNKNOWN: the order has no expiry date"))
    if o["symbol"] in holdings:
        warn.append("already holding %d %s: this adds to it" % (holdings[o["symbol"]], o["symbol"]))
        why.append(W("RISK", "already holding", holdings[o["symbol"]], None, None, False, "shares", "WARN"))
    res = ((sim or {}).get("results") or {}).get(o["symbol"]) or {}
    same_setup = (res.get("plan") or {}).get("setup") == o.get("setup")
    exp = (res.get("monte_carlo") or {}).get("expectancy_r")
    if exp is not None and exp < 0 and same_setup:
        warn.append("time machine expectancy is negative (%+.2fR after charges): the past says this plan loses "
                    "on average" % exp)
    hist = res.get("history") or {}
    used = exp if same_setup else None
    why.append(W("HISTORY", "time-machine expectancy after charges", used, 0, ">=",
                 None if used is None else not used < 0, "R",
                 ("WARN when negative" if used is not None else
                  "UNKNOWN: no time-machine result for this plan" if not res else
                  "UNKNOWN: the time-machine result is for another setup (%s)" % (res.get("plan") or {}).get("setup"))))
    nt = hist.get("trades") if same_setup else None
    k = (cfg.get("daily") or {}).get("min_past_trades_for_rank", 8)
    why.append(W("HISTORY", "past trades of this setup on this stock", nt, k, ">=",
                 None if nt is None else nt >= k, "trades",
                 None if nt is None else ("too few to rank by (under %d): information only, ranked by setup score"
                                          % k if nt < k else
                                          "past expectancy %+.2fR" % hist["expectancy_r"]
                                          if hist.get("expectancy_r") is not None else None)))
    for it in (news.get("symbols", {}) or {}).get(o["symbol"], []):
        if it.get("halal_watch"):
            warn.append("HALAL-WATCH news: %s (%s)" % (it["title"][:90], ", ".join(it["halal_watch"])))
        if "results" in it.get("tags", []):
            warn.append("results news in the window: gaps are likely (%s)" % it["title"][:70])
    why += news_why(o["symbol"], news, tc.today_ist().isoformat())
    status = "BLOCK" if block else ("WARN" if warn else "PASS")
    return {"id": o["id"], "symbol": o["symbol"], "status": status, "block": block, "warn": warn, "ok": ok,
            "why": why}


def result_why(r):
    """The final RISK item: the status and the first reason, the same one tayyib-daily shows."""
    first = (r.get("block") or [None])[0] or \
        (sorted(r.get("warn") or [], key=lambda w: "HALAL-WATCH" not in w) or [None])[0]
    return tc.why_item("RISK", "result", r["status"], None, None, r["status"] == "PASS", None,
                       first or "every check passed")


def base_id(oid):
    """SANSERA-2026-11-04-breakout-2 -> SANSERA-2026-11-04-breakout (the signal)."""
    import re as _re
    return _re.sub(r"-\d+$", "", oid or "")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="?", help="order ids or symbols (default: all SIZED orders)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    store = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    positions = (tc.read_json("positions.json", {}) or {}).get("positions", [])
    uni = tc.load_universe()
    news = tc.read_json("news.json", {}) or {}
    sim = tc.read_json("sim.json", {}) or {}
    want = set(tc.parse_symbols(a.ids)) if a.ids else None
    results, heat, count, inds, value = [], 0.0, 0, {}, 0.0
    placed_signals = {base_id(o["id"]) for o in store["orders"] if o.get("status") == "PLACED"}
    for o in store["orders"]:
        if o.get("status") == "PLACED":
            continue
        # Every unplaced order is evaluated in file order, so limits always count all of them;
        # only the requested ones are reported and saved.
        r = check_order(o, cfg, positions, uni, news, heat, count, inds, value, sim)
        if base_id(o.get("id", "")) in placed_signals and o.get("id") not in placed_signals:
            r["block"].append("this signal (%s) is already placed: a second ticket would double the risk "
                              "on one trade" % base_id(o["id"]))
            r["status"] = "BLOCK"
            r.setdefault("why", []).append(tc.why_item("RISK", "second ticket for a placed signal", base_id(o["id"]),
                                                       None, None, False, None, "BLOCK"))
        r.setdefault("why", []).append(result_why(r))
        requested = not want or o.get("symbol") in want or str(o.get("id", "")).upper() in want
        if requested:
            o["status"] = r["status"]
            o["risk_checked"] = tc.now_ist().isoformat(timespec="minutes")
            results.append(r)
        if r["status"] != "BLOCK":   # later orders count earlier approved ones
            heat += o.get("loss_at_stop_rs", 0)
            value += o["qty"] * o["trigger_price"] + o.get("buy_charges_rs", 0)
            count += 1
            ind = tc.halal_status(o["symbol"], uni).get("industry") or ""
            if ind:
                inds[ind] = inds.get(ind, 0) + 1
    tc.write_json("orders.json", store)
    tc.write_json("risk.json", {"asof": tc.now_ist().isoformat(timespec="minutes"), "results": results})
    if a.json:
        return tc.print_json(results)
    if not results:
        print("no sized orders to check: run tayyib-budget --write first")
    for r in results:
        print("%-5s %s" % (r["status"], r["id"]))
        for x in r["block"]:
            print("   BLOCK  %s" % x)
        for x in r["warn"]:
            print("   warn   %s" % x)
        for x in r["ok"]:
            print("   ok     %s" % x)
    print("Hard rules: " + "; ".join(tc.HARD_RULES))


if __name__ == "__main__":
    main()
