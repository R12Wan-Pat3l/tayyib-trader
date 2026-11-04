---
name: tayyib-halal
description: >-
  Halal Screener. Builds and queries the Shariah-screened stock universe that every other
  tayyib skill depends on: self-screens the Nifty 500 (business screen + TASIS-style ratios: debt under
  25% of assets, non-compliant income under 3%, cash + receivables under 90% of assets) or loads an
  official Shariah list, and keeps user overrides. Use when the user asks "is X halal", "Shariah compliant
  stocks", "build the halal list", "which stocks can I buy", "check if TCS is halal", or before the first
  scan, and monthly or after results season to refresh.
argument-hint: "[build | check SYMBOLS | list | override SYMBOL]"
---

# tayyib-halal

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-halal/halal.py ...`.

The first step, always. A stock that is not `compliant` here never reaches the scanner, and
`tayyib-risk` blocks any order for it.

```bash
python3 "${CLAUDE_SKILL_DIR}/halal.py" build                         # self-screen Nifty 500 (~500 requests, slow)
python3 "${CLAUDE_SKILL_DIR}/halal.py" build --no-financials         # business screen only, fast (mostly 'unknown')
python3 "${CLAUDE_SKILL_DIR}/halal.py" build --official list.csv     # trust an official Shariah list (Symbol column)
python3 "${CLAUDE_SKILL_DIR}/halal.py" check TCS,INFY                # status + reasons + ratios
python3 "${CLAUDE_SKILL_DIR}/halal.py" check XYZ --live              # screen a stock not in the universe (not saved)
python3 "${CLAUDE_SKILL_DIR}/halal.py" list --status compliant
python3 "${CLAUDE_SKILL_DIR}/halal.py" compare trusted.csv               # agreement with a trusted Shariah list
python3 "${CLAUDE_SKILL_DIR}/halal.py" override ABC --status excluded --note "scholar: hotel income"
```

## How it decides

1. **Business screen.** Excluded: interest-based finance (the Nifty "Financial Services" industry:
   banks, NBFCs, insurers), known alcohol / tobacco / casino companies, and names containing words such
   as bank, insurance, breweries, distillers, tobacco. **Review** (blocked unless the user allows it):
   media and entertainment, and names with finance, capital, hotel, gaming and similar words.
2. **Financial screen** (TASIS-style, the methodology NSE's Shariah indices use), from the latest annual
   numbers on Yahoo: debt / total assets < 25%; (interest income + 8% of interest-bearing investments) /
   total income < 3%; (cash + receivables) / total assets < 90%. Thresholds are in config.
3. **Overrides** in `trader/halal_overrides.json` win over everything (the user's or their scholar's ruling).

Statuses: `compliant`, `review`, `excluded`, `unknown` (data missing). Only `compliant` trades by default.

## What to tell the user

- Self-screening is an approximation: Yahoo's Indian fundamentals have gaps and its "total revenue"
  may not match the annual report. An official list (NSE Nifty 500 Shariah constituents, or an export
  from a TASIS-based screener) is better when they have one: `build --official`.
- Rebuild monthly and after each results season; `tayyib-risk` warns when the list is over 120 days old.
- Scholars differ on thresholds and on businesses such as media or hotels. Point them to their own
  scholar or a recognised Shariah board for a ruling; use `override` to record it.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
