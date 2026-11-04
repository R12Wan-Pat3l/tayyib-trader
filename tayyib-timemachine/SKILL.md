---
name: tayyib-timemachine
description: >-
  Time Machine. Before risking a rupee, replays each planned trade: 10,000
  simulated futures resampled from the stock's own last ~500 daily moves, plus every past time the same
  setup armed and filled on that stock, all in R after Indian charges, with an honest verdict (leans
  positive / coin flip / negative). Writes trader/sim.json. Use when the user asks "what are the odds",
  "backtest this", "will this trade work", "simulate", "replay", or before sizing a trade.
argument-hint: "run [SYMBOLS] [--runs 10000] [--seed 7]"
---

# tayyib-timemachine

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-timemachine/timemachine.py ...`.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write            # every plan in trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run TCS --runs 20000 --seed 1
```

Rules in the simulation, the same as the plan: gaps through the stop fill at the open (worse than the
stop), a day that touches both stop and target counts as the stop (conservative), swing trades move
the stop to breakeven at +1R, and the time stop closes at that day's close. Expectancy is the average R
per trade after STT, stamp duty, exchange fees, GST and DP charges. The same seed gives the same result.

How to present it:
- Lead with the verdict and the expectancy, then target-first vs stop-first odds.
- Under 8 historical trades is too few to mean much; say so.
- It is resampled history. Results days, news, circuit limits and market crashes can do what the last
  two years never did. Treat it as a reality check, never as a promise.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
