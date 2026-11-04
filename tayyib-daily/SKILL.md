---
name: tayyib-daily
description: >-
  Daily Halal Trade List. One command that runs the whole tayyib pipeline for today's candidates
  (halal list check, scanner, news, exit plan, time machine, sizing with Indian charges, risk check)
  and prints one table of halal NSE stocks with entry, stop, stop %, target, quantity, rupee risk,
  time-machine verdict and PASS / WARN / BLOCK. Saves trader/daily/DATE.md. Use when the user says
  "today's list", "daily list", "what should I trade today", "give me halal stocks with entry and
  exit", "run my daily", or after 3:30 PM IST on a trading day.
argument-hint: "[--mode swing|delivery|all] [--top 10] [--no-news]"
---

# tayyib-daily

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-daily/daily.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/daily.py"                     # swing + delivery, best 10 stocks
python3 "${CLAUDE_SKILL_DIR}/daily.py" --mode swing --top 5
python3 "${CLAUDE_SKILL_DIR}/daily.py" --no-news           # faster
```

It needs the other tayyib skills next to it (as in the plugin or the repo), and a halal universe
(`tayyib-halal build`, monthly). It takes one to three minutes: a price download per halal stock.

What it does: scan; keep one setup per stock (with `--mode all`, alternating the best swing and the
best delivery ideas); news (so HALAL-WATCH and results warnings reach the risk check); plan; time
machine (3,000 runs each); size, best expectancy first; then the risk check on the whole orders file,
exactly like `tayyib-risk`, so open positions and placed orders count. Today's tickets replace
earlier unplaced ones (it says which); placed orders are never touched. Rows are sorted PASS, WARN,
BLOCK, best expectancy first within each. A negative time-machine expectancy is a WARN.

How to present it:
- Show the table as it is. Read out every WARN and BLOCK reason.
- "No setups armed today" is a normal answer. Do not go looking for trades to fill the list.
- Say the time machine is resampled history, and that few past trades means little.
- For any row the user wants, show `tayyib-broker show SYMBOL` and ask: "Do you want to place this
  order?" They place it themselves. Then record the fill with `ticket.py placed`.
- If it ran during market hours, say that the levels can still move until the close.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
