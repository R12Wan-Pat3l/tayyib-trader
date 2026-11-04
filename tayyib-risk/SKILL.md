---
name: tayyib-risk
description: >-
  Risk Manager. Checks every sized order and returns PASS, WARN or BLOCK with reasons:
  hard rules (CNC delivery only, BUY to open, no short selling, no F&O, no margin, halal-compliant only)
  and limits (loss at stop, position size, cash, open positions, portfolio heat, positions per industry,
  net reward:risk, plan still valid, halal list age, HALAL-WATCH and results news). Use when the user asks
  "is this trade OK", "check my risk", "can I take this trade", or always before showing a ticket.
argument-hint: "[IDS]"
---

# tayyib-risk

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-risk/check.py ...`.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"            # every SIZED order in trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/check.py" TCS
```

Only PASS and WARN orders become tickets. Read every WARN to the user. Orders are checked in turn,
so a later one counts the cash, heat and positions of the earlier approved ones, even before they
are placed. That is deliberate: it assumes every approved ticket may fill.

The hard rules are in the code, not the config, and cannot be switched off:
CNC only (no MIS, NRML or MTF); no short selling (a SELL can never exceed shares held);
no futures or options; no margin or leverage; and, unless the user changed `halal.require_compliant`,
nothing that is not `compliant`.

Config limits (defaults): max risk per trade 1% of capital, max position 20%, 6 open positions,
total open risk (heat) 6%, 2 positions per industry, net reward:risk at least 1.5.

Next: `tayyib-broker show`.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
