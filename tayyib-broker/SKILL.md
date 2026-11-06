---
name: tayyib-broker
description: >-
  Order Ticket and trade journal. Turns risk-approved orders into plain-words tickets
  with exact steps for Zerodha Kite and Groww (SL / GTT buy, then a GTT OCO stop and target), and keeps
  the journal: placed (the user's actual fill), stop (raise only), close (P&L after charges, in R),
  positions. Places no order and connects to no broker. Use when the user says "give me the order",
  "how do I place this", "I bought X at", "I sold X", "move my stop", "show my positions", "my P&L".
argument-hint: "[show | placed ID --price P | stop ID --stop P | close ID --price P | positions]"
---

# tayyib-broker

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-broker/ticket.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                                   # tickets for PASS/WARN orders
python3 "${CLAUDE_SKILL_DIR}/ticket.py" placed ALFA-2026-10-30-breakout --price 1004.5
python3 "${CLAUDE_SKILL_DIR}/ticket.py" stop ALFA --stop 1004.5                # breakeven; never lower
python3 "${CLAUDE_SKILL_DIR}/ticket.py" close ALFA --price 1064.1 --reason target
python3 "${CLAUDE_SKILL_DIR}/ticket.py" positions
```

The flow with the user:
1. Show the ticket in plain words. Ask: "Do you want to place this order?" Do nothing else until they
   answer yes for that exact order.
2. They place it themselves in Kite or Groww. Nothing in this pack can place an order; there is no
   broker connection in this version.
3. When they tell you their fill, record it with `placed`. Remind them to set the stop/target GTT.
4. When they sell, record it with `close`. Then `tayyib-purify` if the stock paid a dividend.

`placed` refuses an order that risk did not pass, and a fill at or under the stop. `close` refuses to
sell more than is held (that would be a short sale). Closing a whole position cancels its alerts.

## Import the user's holdings (v0.2.5)

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" import trader/import/holdings.xlsx            # preview: writes nothing
python3 "${CLAUDE_SKILL_DIR}/ticket.py" import trader/import/holdings.xlsx --yes      # only after the user's yes
```

The Zerodha Console / Kite or Groww holdings file (CSV or XLSX) the user downloaded and saved. Show the preview
table (symbol, qty, average price, matched NSE symbol, halal now, alert, add / update / leave, and every "could
not match" row), then ask "Import these holdings?" and run `--yes` only on a yes. It backs up positions.json
first. If the columns are not found it prints the headers it saw: never guess a column. For an ISIN outside
the halal list, `--map ISIN=SYMBOL` only with a symbol the user gives. Imported holdings are not trades (no
stop, target, R or tracker row); `halal.py held --write` then re-checks them. `close HOLD-SYMBOL --price P`
records a sale of a holding (no R).

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
