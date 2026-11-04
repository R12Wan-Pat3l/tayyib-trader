---
name: tayyib-results
description: >-
  Results Analyst. Reads a company's quarterly results (revenue, operating profit and
  margin, net profit, EPS with QoQ and YoY growth) and compares the latest annual halal ratios with the
  year before, flagging HALAL-WATCH drift toward the TASIS limits. Writes trader/results/SYMBOL.json.
  Use when the user asks "how were X's results", "is X growing", "quarterly numbers", "did X's debt go
  up", or after a results headline.
argument-hint: "SYMBOL [--quarters 6]"
---

# tayyib-results

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-results/results.py ...`.

```bash
python3 "${CLAUDE_SKILL_DIR}/results.py" TCS
python3 "${CLAUDE_SKILL_DIR}/results.py" ASIANPAINT --quarters 8
```

Figures are in Rs crore from Yahoo's fundamentals feed: free and unofficial, and Indian coverage has
gaps (some quarters or lines missing, consolidated vs standalone not always clear). For anything that
matters, point the user to the filing on NSE or BSE.

HALAL-WATCH flags: a ratio within 20% of its limit, or a ratio that rose sharply in a year. Neither
makes the stock non-compliant by itself; they say what to re-check when the halal list is rebuilt.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
