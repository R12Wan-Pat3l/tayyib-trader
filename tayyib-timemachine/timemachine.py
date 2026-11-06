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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


# The walk, the Monte Carlo and the history replay live in core (v0.2.0) so tayyib-backtest ranks a day's
# picks with the same numbers tayyib-daily gets from here. Same code, same results.
cost_r = tc.tm_cost_r
walk = tc.tm_walk
monte_carlo = tc.tm_monte_carlo
history = tc.tm_history


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
