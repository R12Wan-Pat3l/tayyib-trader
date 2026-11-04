---
name: tayyib-insider
description: >-
  Insider and Bulk-Deal Tracker for NSE. Reads public disclosures under SEBI
  (Prohibition of Insider Trading) Regulations 2015 (promoter and director buys, sells and pledges) and
  NSE bulk and block deals for a stock, with promoter net buying in rupees. Writes trader/insider.json.
  Use when the user asks "are promoters buying X", "insider trading in X", "bulk deals", "block deals",
  "pledged shares".
argument-hint: "SYMBOLS [--days 90]"
---

# tayyib-insider

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-insider/insider.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" TCS
python3 "${CLAUDE_SKILL_DIR}/insider.py" ALFA,CHRL --days 180
```

These are public filings, not inside information. NSE's JSON endpoints are unofficial: they need a
cookie from a page visit (handled) and can block automated clients or change field names; errors are
reported per source and the rest still runs.

Reading it: promoters buying in the open market with their own money is often watched; pledge creation
can mean borrowing against shares (and forced selling if the price falls); a single bulk deal says who
traded, not why.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
