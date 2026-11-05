#!/usr/bin/env python3
"""tayyib-timemachine: replay a planned trade before you risk a rupee.

Two honest checks for every plan in trader/plan.json:

  1. Monte Carlo: 10,000 futures built by resampling the stock's own daily
     moves (open/high/low/close relative to the prior close) from its last
     ~500 sessions. Stop and target checked every day, gaps fill at the open,
     a day that touches both counts as the stop (conservative), +1R moves the
     stop to breakeven on swing trades, time stop at max_hold_days.
  2. History: every past day the same setup armed on this stock, traded with
     the same rules on the real bars that followed.

Results are in R (multiples of the planned risk), after Indian charges.
A simulation, not a prediction. Writes trader/sim.json.
"""
import argparse
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def cost_r(entry, exit_price, risk, cfg, qty=100):
    return tc.round_trip(entry, exit_price, qty, cfg) / qty / risk


def walk(days, entry, stop, target, max_days, breakeven):
    """days: iterable of (open, high, low, close). -> (outcome, exit_price, n_days)."""
    risk = entry - stop
    cur_stop = stop
    n = 0
    last_close = entry
    for (o, h, l, c) in days:
        n += 1
        if o <= cur_stop:
            return ("breakeven" if cur_stop >= entry else "stop"), o, n
        if o >= target:
            return "target", o, n
        if l <= cur_stop:
            return ("breakeven" if cur_stop >= entry else "stop"), cur_stop, n
        if h >= target:
            return "target", target, n
        if breakeven and h >= entry + risk and cur_stop < entry:
            cur_stop = entry
        last_close = c
        if n >= max_days:
            return "time", c, n
    return "open", last_close, n


def monte_carlo(bars, plan, cfg, n, seed, lookback=500):
    hist = bars[-lookback:]
    moves = []
    for k in range(1, len(hist)):
        pc = hist[k - 1]["close"]
        b = hist[k]
        moves.append((b["open"] / pc, b["high"] / pc, b["low"] / pc, b["close"] / pc))
    rng = random.Random(seed)
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    risk = entry - stop
    max_days = min(plan["max_hold_days"], 250)
    be = plan["mode"] == "swing"
    counts = {"target": 0, "stop": 0, "breakeven": 0, "time": 0, "open": 0}
    rs, days = [], []

    def gen():
        pc = entry
        for _ in range(max_days):
            ro, rh, rl, rc = moves[rng.randrange(len(moves))]
            o, h, l, c = pc * ro, pc * rh, pc * rl, pc * rc
            yield (o, max(o, h, c), min(o, l, c), c)
            pc = c

    for _ in range(n):
        out, px, d = walk(gen(), entry, stop, target, max_days, be)
        counts[out] += 1
        rs.append((px - entry) / risk - cost_r(entry, px, risk, cfg))
        days.append(d)
    rs.sort()
    pct = lambda q: round(rs[min(len(rs) - 1, int(q * len(rs)))], 2)
    return {
        "runs": n, "seed": seed, "sessions_sampled": len(moves),
        "probabilities_pct": {k: round(v / n * 100, 1) for k, v in counts.items() if k != "open"},
        "expectancy_r": round(sum(rs) / n, 3),
        "r_percentiles": {"p10": pct(0.10), "p50": pct(0.50), "p90": pct(0.90)},
        "median_days": statistics.median(days),
    }


def history(bars, plan, cfg):
    ind = tc.indicators(bars)
    m = cfg["modes"][plan["mode"]]
    trades, i = [], (cfg.get("scanner") or {}).get("warmup_bars", 200)
    last_i = len(bars) - 2
    while i < last_i:
        sig = tc.detect(plan["setup"], bars, ind, i, cfg["tick_size"], cfg)
        if not sig:
            i += 1
            continue
        fill_k = None
        for k in range(i + 1, min(i + 1 + sig["valid_days"], len(bars))):
            if bars[k]["close"] < sig["invalidation"] and bars[k]["high"] < sig["trigger"]:
                break
            if bars[k]["high"] >= sig["trigger"]:
                fill_k = k
                break
        if fill_k is None:
            i += 1
            continue
        entry = max(bars[fill_k]["open"], sig["trigger"])
        try:
            p = tc.plan_trade(sig, cfg, entry)
        except ValueError:
            i += 1
            continue
        # the fill day itself: only the part after the trigger counts, so check stop on its low
        b = bars[fill_k]
        if b["low"] <= p["stop"] and b["close"] < entry:
            out, px, d = "stop", p["stop"], 1
        else:
            fwd = [(x["open"], x["high"], x["low"], x["close"]) for x in bars[fill_k + 1:]]
            out, px, d = walk(fwd, entry, p["stop"], p["target"], m["max_hold_days"],
                              plan["mode"] == "swing")
            d += 1
        risk = entry - p["stop"]
        if out != "open":
            trades.append({"date": bars[fill_k]["date"], "entry": round(entry, 2), "outcome": out,
                           "exit": round(px, 2), "days": d,
                           "r": round((px - entry) / risk - cost_r(entry, px, risk, cfg), 2)})
        i = fill_k + d
    n = len(trades)
    summ = {"trades": n}
    if n:
        summ.update({
            "target": sum(t["outcome"] == "target" for t in trades),
            "stop": sum(t["outcome"] == "stop" for t in trades),
            "breakeven": sum(t["outcome"] == "breakeven" for t in trades),
            "time": sum(t["outcome"] == "time" for t in trades),
            "win_rate_pct": round(sum(t["r"] > 0 for t in trades) / n * 100, 1),
            "expectancy_r": round(sum(t["r"] for t in trades) / n, 3),
        })
    return summ, trades


def verdict(mc, hist):
    e = mc["expectancy_r"]
    he, hn = hist.get("expectancy_r"), hist.get("trades", 0)
    if hn < 8:
        h_txt = "only %d past trades of this setup on this stock: too few to trust" % hn
    else:
        h_txt = "past trades of this setup: %d, expectancy %+.2fR" % (hn, he)
    if e > 0.15 and (hn < 8 or he > 0.1):
        v = "leans positive after charges, still no promise"
    elif e < -0.1 or (hn >= 8 and he < -0.1):
        v = "negative after charges: the past says skip or rethink the plan"
    else:
        v = "close to a coin flip after charges"
    pr = mc["probabilities_pct"]
    outcomes = {k: pr.get(k, 0) for k in ("target", "stop", "breakeven", "time")}
    if mc["r_percentiles"]["p50"] < 0 or max(outcomes, key=outcomes.get) == "stop":
        v += ("; but the most likely single outcome is a loss (stop first %.0f%% vs target first %.0f%%, "
              "median %+.2fR): the average is carried by fewer, bigger wins"
              % (pr.get("stop", 0), pr.get("target", 0), mc["r_percentiles"]["p50"]))
    return "%s (%s)" % (v, h_txt)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("symbols", nargs="?", help="default: every plan in trader/plan.json")
    r.add_argument("--runs", type=int, default=10000)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--write", action="store_true")
    r.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    plans = (tc.read_json("plan.json", {}) or {}).get("plans", {})
    syms = tc.parse_symbols(a.symbols) if a.symbols else list(plans)
    if not syms:
        tc.die("no plans: run tayyib-exit plan SYMBOL --write first")
    results = {}
    for s in syms:
        if s not in plans:
            results[s] = {"error": "no plan for %s" % s}
            continue
        bars, _ = tc.get_daily_bars(s)
        mc = monte_carlo(bars, plans[s], cfg, a.runs, a.seed)
        hs, trades = history(bars, plans[s], cfg)
        results[s] = {"plan": plans[s], "monte_carlo": mc, "history": hs,
                      "history_trades": trades[-30:], "verdict": verdict(mc, hs)}
    out = {"asof": tc.now_ist().isoformat(timespec="minutes"), "results": results}
    if a.write:
        tc.write_json("sim.json", out)
    if a.json:
        return tc.print_json(out)
    for s, res in results.items():
        if "error" in res:
            print("%s: %s" % (s, res["error"]))
            continue
        mc, hs, pl = res["monte_carlo"], res["history"], res["plan"]
        pr = mc["probabilities_pct"]
        print("%s  %s/%s  entry %.2f  stop %.2f  target %.2f" % (s, pl["mode"], pl["setup"], pl["entry"],
                                                              pl["stop"], pl["target"]))
        print("  %d simulated futures (seed %d, from %d real sessions):" % (mc["runs"], mc["seed"],
                                                                         mc["sessions_sampled"]))
        print("    target first %.1f%%  stop first %.1f%%  breakeven %.1f%%  time stop %.1f%%"
              % (pr["target"], pr["stop"], pr["breakeven"], pr["time"]))
        print("    expectancy %+.2fR after charges, median %s sessions, R p10/p50/p90 %s/%s/%s"
              % (mc["expectancy_r"], mc["median_days"], mc["r_percentiles"]["p10"],
                 mc["r_percentiles"]["p50"], mc["r_percentiles"]["p90"]))
        if hs["trades"]:
            print("  history: %d past trades: %d target, %d stop, %d breakeven, %d time; win %.0f%%, %+.2fR each"
                  % (hs["trades"], hs["target"], hs["stop"], hs["breakeven"], hs["time"],
                     hs["win_rate_pct"], hs["expectancy_r"]))
        else:
            print("  history: the setup never armed and filled on this stock in the data")
        print("  verdict: %s" % res["verdict"])
    print("A simulation from past bars, not a prediction. Results, news and gaps can do what the past never did.")


if __name__ == "__main__":
    main()
