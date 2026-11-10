---
name: tayyib-backtest
description: >-
  Backtest. Answers "if I had run this strategy every day for the last N years across the halal list
  with my capital and settings, what happened?": replays tayyib-daily day by day (same setups, plans,
  ranking, sizing, outcome rules and Indian charges), one cash account, no look-ahead, then win rate,
  expectancy in R, CAGR, max drawdown, in-sample vs out-of-sample and buy-and-hold of the Shariah ETF and
  Nifty 50. Writes trader/backtest/. Use when the user says "backtest", "test my strategy", "how did this
  strategy do", "past performance".
argument-hint: "run [--mode swing|delivery|all] [--years 3] [--capital N] [--max-positions N] [--no-take-warn] [--compare] [--robust [N]] [--robust-compare A B] [--symbols A,B,... | --holdings] [--write] | list | show ID"
---

# tayyib-backtest

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-backtest/backtest.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups, levels or results from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --write                 # last 3 years, swing + delivery, your config
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --mode swing --setups breakout,pullback --years 5 --write
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --from 2023-01-01 --to 2025-12-31 --capital 200000 --max-positions 4
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --years 5 --symbols TCS,INFY,NESTLEIND --write   # My stocks (v0.2.8)
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --years 5 --holdings --write                # the stocks you hold
python3 "${CLAUDE_SKILL_DIR}/backtest.py" list                        # saved runs
python3 "${CLAUDE_SKILL_DIR}/backtest.py" show ID                     # one saved run
```

It takes minutes: one 5-year price download per halal stock (cached for the day), then about 750 trading
days of scanning. It needs the halal list (`tayyib-halal build`) first. `--split` sets the in-sample /
out-of-sample date (default: the start of the last third of the window).

What it does, in order, every trading day of the window:
1. Scans every compliant stock (review / excluded are never traded) on its bars up to
   that day only, with the live liquidity filter and exit plan.
2. Picks and ranks the day's stocks exactly like tayyib-daily (one setup per stock, swing and delivery
   alternated in `--mode all`, time-machine expectancy for stocks with enough past trades, else score).
3. Sizes each with tayyib-budget's rule (1% risk incl. charges, 20% max position, by default), runs the
   live tayyib-risk check against the simulated book (heat, 2 per industry, reward:risk, cash...; news
   can't be replayed), never places a BLOCK, places WARN unless `--no-take-warn`, and leaves a buy-stop
   plan waiting until its valid-until date. Recent listings join once they have 250 days of prices.
4. Fills and exits follow the paper tracker's rules: gap through the stop fills at the open, a day touching
   stop and target counts as the stop, swing breakeven at +1R, time stop at that day's close.

How to present it:
- **Read every banner first, word for word.** Four are always there (today's halal list applied to the
  past, survivorship bias, past results are no promise, news can't be replayed). Others say there were too
  few trades, that out-of-sample was much weaker (possibly overfit), that holding the Shariah ETF did
  better, or that the Nifty 50 did (say it is reference only: not halal-screened, never a halal option).
- A group marked "(too few to judge)" (under 30 trades) is noise: never suggest switching a setup on or off
  because of it.
- Then the overall table (trades, win rate, expectancy R, profit factor, CAGR, max drawdown with dates),
  then in-sample vs out-of-sample side by side, then the two benchmarks. A benchmark that could not be
  fetched is UNKNOWN: say so, never treat it as 0.
- Say how many plans the risk check blocked and the top reasons, which stocks joined late, and the skipped
  stocks with why.
- With `--compare`, show (a) as run next to (b) score-only ranking: the difference is what the
  time-machine ranking added.
- With `--robust [N]` (v0.2.6; 20 runs by default, at most 50), give the range, not one number: median and 10th to
  90th percentile of CAGR, expectancy, max drawdown and trades, how many runs beat the Shariah ETF, and the max
  positions 3 / 5 / 8 table. Each seed changes only the order of equal-ranked signals and the start by one trading
  day, on the same prices.
- With `--robust-compare "A" "B"` (e.g. "pullback=on" "pullback=off", "regime=off"
  "regime=close_below_200dma:half_risk"), read the verdict line first and exactly as written. Only "B is better in X
  of N runs" (80%+) supports changing a default; "No clear difference: don't change the default on this evidence"
  means keep it.

**My stocks (v0.2.8).** `--symbols` (1 to 20) or `--holdings` runs the same strategy on that basket only and
adds "Buy and hold these stocks" (equal shares, one buy and one sell charge) and a per-stock table (trades, wins,
win rate, total R, P&L, holding return, better / worse / no trades). Every symbol must be compliant on today's
halal list: a review, excluded, unknown or unlisted symbol refuses the whole run with its status; never retry
without it silently, tell the user which one and why. When presenting it:
- Read the hindsight line first: "You chose these stocks today, knowing how they did since. Results are likely
  better than reality (hindsight)." Then "Small basket..." (under 10 stocks) and "Buying and holding these same
  stocks did better." when present.
- Never present a basket result as how the daily list did; "All halal stocks" (no flag) is that test.
- A stock with no prices is UNKNOWN and left out of the basket: say so.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF. The replay never
  borrows: cash cannot go below zero.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
  This skill writes only `trader/backtest/` (and the price cache): never the tracker, orders, positions,
  daily lists or config.
- ## Market regime filter (v0.2.4)

```bash
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --years 5 --mode all --regime-compare --write   # off + 4 variants, same bars
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --years 3 --regime close_below_200dma:no_new_swing --write
```

Causal: each day's regime uses the index's bars up to that day only. Compare trades, win rate, expectancy,
CAGR, max drawdown, worst year and the swing / pullback expectancy across the columns. Recommend switching the
filter on (Settings, Regime) only if a variant helps on more than one window (e.g. both 3 and 5 years); it
is OFF by default.

Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
