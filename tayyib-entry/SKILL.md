---
name: tayyib-entry
description: >-
  Entry Timer. Checks whether a scanned setup has triggered: WAITING (under the trigger),
  TRIGGERED (a daily high crossed the buy-stop trigger), EXTENDED (ran more than 4% past it: don't
  chase), INVALIDATED (closed under the invalidation) or EXPIRED. Uses daily bars for the decision and
  the live price as a heads-up in market hours. Use when the user asks "has X triggered", "should I buy
  X now", "is it time to enter", "watch X for me".
argument-hint: "[check SYMBOLS | watch SYMBOL]"
---

# tayyib-entry

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-entry/entry.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ALFA,CHRL
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --setup pullback
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --mode swing            # only swing setups
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch TCS --every 300     # re-checks in market hours until it resolves
```

The signal comes from `trader/scan.json`, or is found on the last six closes. A trigger is meant to be a
**buy-stop**: an order that only buys if price trades up through the level (a GTT or SL order in the
broker app). This is swing and delivery trading: the entry can fill on any of the setup's valid
sessions (3 for swing, 5 for delivery), and the position is held overnight as CNC.

Status meanings for the user:
- WAITING: leave the buy-stop in place, or wait. Not a reason to buy early.
- TRIGGERED: if they were not already filled, the planned entry was hit; the plan still applies only
  if the price is near the trigger.
- EXTENDED: missed it. Chasing a stock 4%+ above the trigger worsens the risk:reward. Skip it.
- INVALIDATED / EXPIRED: the idea is off. Re-scan later.

Next: `tayyib-exit plan SYMBOL --write` (set the stop and target before buying).

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
