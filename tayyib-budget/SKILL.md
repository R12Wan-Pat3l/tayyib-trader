---
name: tayyib-budget
description: >-
  Budget Manager. Sizes each planned trade in whole shares so the loss at the stop,
  including all Indian delivery charges (STT, stamp duty, exchange, SEBI, GST, DP charge, brokerage for
  Zerodha or Groww), stays within the user's risk per trade (default 1% of capital), capped by max
  position size (20%) and cash. Writes trader/orders.json. Use when the user asks "how many shares",
  "position size", "how much should I invest in X", "size my trade".
argument-hint: "[SYMBOLS] [--capital N] [--risk-pct 1] --write"
---

# tayyib-budget

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-budget/size.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                       # every plan
python3 "${CLAUDE_SKILL_DIR}/size.py" TCS --capital 300000 --risk-pct 0.5 --broker groww --write
```

The order written is: BUY, CNC, an SL (stop-limit) buy with trigger = planned entry and limit 0.5%
above, plus the stop and target to set after the fill. It also shows loss at the stop and gain at the
target after charges, and net reward:risk.

Set the user's real numbers once in `trader/config.json` (copy `config.example.json`): `capital`,
`max_risk_per_trade_pct` or `max_risk_per_trade_rs`, `max_position_pct`, `broker`. The charges are
approximate (2026 rates); tell the user to check their broker's charges page. On small positions the
fixed DP charge on selling (about Rs 15) is a real share of the profit.

Next: `tayyib-risk` (check every order).

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
