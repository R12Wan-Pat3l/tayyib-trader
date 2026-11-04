---
name: tayyib-exit
description: >-
  Exit Planner. Sets the stop-loss, the target, the time stop and the trailing rules
  before entry. Swing: stop at the setup's invalidation kept between 0.75 and 3 ATR and never more than 10% below entry, target 2R, out
  after 20 sessions, breakeven at +1R. Delivery: stop under the 200-day average, never wider than 15%,
  review at 3R, exit on a weekly close under the 200-day. Writes trader/plan.json. Use when the user
  asks "where should my stop be", "what's the target", "plan the trade", "exit strategy", "stop loss for X".
argument-hint: "[plan SYMBOLS --write | show | remove SYMBOL]"
---

# tayyib-exit

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-exit/exit.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan ALFA --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan TCS --setup trend --write          # delivery plan
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan TCS --mode swing --write          # only swing setups
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan TCS --entry 4012 --stop 3890 --write  # user's own levels
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

Every plan has: entry (the trigger, or the actual fill if already triggered), stop and how it was set,
target and its R multiple, the last day the entry is valid, the time-stop date, and trailing rules.
R = risk per share = entry - stop. A 2R target means the target is twice the risk away.

Tell the user to place the stop as soon as the buy fills (Zerodha: GTT OCO with stop and target), and
that a stop is a plan, not a guarantee: a gap down at the open fills below it. Stops only move up
(`tayyib-broker stop` refuses to lower one).

Next: `tayyib-timemachine run` (replay it), then `tayyib-budget --write` (size it).

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
