---
name: tayyib-alerts
description: >-
  Price Alerts. Rings once when a price crosses a level or a date arrives: entry
  triggers from plans, stops, targets and time stops from open positions, or any level the user sets.
  Use when the user says "alert me when X crosses", "tell me if my stop is hit", "remind me to exit",
  "check my alerts"; schedule `check` every 15 minutes in market hours (9:15 AM-3:30 PM IST).
argument-hint: "[add ... | check | list | clear]"
---

# tayyib-alerts

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-alerts/alerts.py ...`.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                   # entry triggers
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-positions              # stop, target, time stop
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add TCS --above 4100 --note "breakout"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add TCS --on 2026-12-15 --note "results week"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
```

Prices are Yahoo's (can lag by a few minutes). The broker's own GTT is what actually protects a
position; these alerts are a second pair of eyes. When a STOP or TARGET rings, tell the user plainly
and point to `tayyib-broker close` once they have sold.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
