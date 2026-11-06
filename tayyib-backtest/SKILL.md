---
name: tayyib-backtest
description: >-
  Backtest. Answers "if I had run this strategy every day for the last N years across the halal list
  with my capital and settings, what happened?": replays tayyib-daily day by day (same setups, plans,
  ranking, sizing, outcome rules and Indian charges), one cash account, no look-ahead, then win rate,
  expectancy in R, CAGR, max drawdown, in-sample vs out-of-sample and buy-and-hold of the Shariah ETF and
  Nifty 50. Writes trader/backtest/. Use when the user says "backtest", "test my strategy", "how did this
  strategy do", "past performance".
argument-hint: "run [--mode swing|delivery|all] [--years 3] [--capital N] [--max-positions 5] [--write] | list | show ID"
---

# tayyib-backtest

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-backtest/backtest.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups, levels or results from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --write                 # last 3 years, swing + delivery, your config
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --mode swing --setups breakout,pullback --years 5 --write
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --from 2023-01-01 --to 2025-12-31 --capital 200000 --max-positions 4
python3 "${CLAUDE_SKILL_DIR}/backtest.py" list                        # saved runs
python3 "${CLAUDE_SKILL_DIR}/backtest.py" show ID                     # one saved run
```

It takes minutes: one 5-year price download per halal stock (cached for the day), then about 750 trading
days of scanning. It needs the halal list (`tayyib-halal build`) first. `--split` sets the in-sample /
out-of-sample date (default: the start of the last third of the window).

What it does, in order, every trading day of the window:
1. Scans every compliant stock (your overrides win; review / excluded are never traded) on its bars up to
   that day only, with the live liquidity filter and exit plan.
2. Picks and ranks the day's stocks exactly like tayyib-daily (one setup per stock, swing and delivery
   alternated in `--mode all`, time-machine expectancy for stocks with enough past trades, else score).
3. Sizes each with tayyib-budget's rule (1% risk incl. charges, 20% max position, by default) against the
   cash not already used, and places a buy-stop plan that waits until its valid-until date.
4. Fills and exits follow the paper tracker's rules: gap through the stop fills at the open, a day touching
   stop and target counts as the stop, swing breakeven at +1R, time stop at that day's close.

How to present it:
- **Read every banner first, word for word.** Three are always there (today's halal list applied to the
  past, survivorship bias, past results are no promise). Others say there were too few trades, that
  out-of-sample was much weaker (possibly overfit), or that holding the Shariah ETF did better.
- Then the overall table (trades, win rate, expectancy R, profit factor, CAGR, max drawdown with dates),
  then in-sample vs out-of-sample side by side, then the two benchmarks. A benchmark that could not be
  fetched is UNKNOWN: say so, never treat it as 0.
- Name the skipped stocks and why (no data, or not enough history before the window).
- tayyib-risk's portfolio heat, industry and news checks are not part of the replay: say so if the user
  compares it with their live list.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF. The replay never
  borrows: cash cannot go below zero.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
  This skill writes only `trader/backtest/` (and the price cache): never the tracker, orders, positions,
  daily lists or config.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
