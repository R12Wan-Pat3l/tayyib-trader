---
name: tayyib-halal
description: >-
  Halal Screener. Builds and queries the Shariah-screened stock universe that every other
  tayyib skill depends on: self-screens the Nifty 500 (business screen + TASIS-style ratios: debt under
  25% of assets, non-compliant income under 3%, cash + receivables under 90% of assets) or loads an
  official Shariah list. Automatic and strict: the rules are fixed in code, no per-stock overrides. Use when the user asks "is X halal", "Shariah compliant
  stocks", "build the halal list", "which stocks can I buy", "check if TCS is halal", or before the first
  scan, and monthly or after results season to refresh.
argument-hint: "[build | check SYMBOLS | list | compare FILE | held]"
---

# tayyib-halal

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-halal/halal.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

The first step, always. A stock that is not `compliant` here never reaches the scanner, and
`tayyib-risk` blocks any order for it.

```bash
python3 "${CLAUDE_SKILL_DIR}/halal.py" build                         # self-screen Nifty 500 (~500 requests, slow)
python3 "${CLAUDE_SKILL_DIR}/halal.py" build --no-financials         # business screen only, fast (mostly 'unknown')
python3 "${CLAUDE_SKILL_DIR}/halal.py" build --official list.csv     # trust an official Shariah list (Symbol column)
python3 "${CLAUDE_SKILL_DIR}/halal.py" check TCS,INFY                # status + reasons + ratios
python3 "${CLAUDE_SKILL_DIR}/halal.py" check XYZ --live              # screen a stock not in the universe (not saved)
python3 "${CLAUDE_SKILL_DIR}/halal.py" list --status compliant
python3 "${CLAUDE_SKILL_DIR}/halal.py" compare trusted.csv               # agreement with a trusted Shariah list (read-only)
```

The Nifty 500 list is downloaded from niftyindices.com with the tool's own honest user agent (never a
browser disguise). If that is refused, `build` uses the last good copy in `trader/cache/` (and says how
old it is), then an `ind_nifty500list.csv` the user saved in their data folder; with neither it stops and
says how to download it. Tell the user exactly that message; never build from a partial list or from memory.

## How it decides

1. **Business screen.** Excluded: interest-based finance (the Nifty "Financial Services" industry:
   banks, NBFCs, insurers), known alcohol / tobacco / casino companies, and names containing words such
   as bank, insurance, breweries, distillers, tobacco. **Review** (always blocked):
   media and entertainment, and names with finance, capital, hotel, gaming and similar words.
2. **Financial screen** (TASIS-style, the methodology NSE's Shariah indices use), from the latest annual
   numbers on Yahoo: debt / total assets < 25%; (interest income + 8% of interest-bearing investments) /
   total income < 3%; (cash + receivables) / total assets < 90%. These limits are fixed in code (v0.2.7):
   a change in config.json is ignored with "... is fixed and can't be changed".

There are no overrides (v0.2.7): `trader/halal_overrides.json` is never read or written; an old file gives one
note, "halal_overrides.json is no longer used (v0.2.7): the automatic TASIS screen decides."

Statuses: `compliant`, `review`, `excluded`, `unknown` (data missing). Only `compliant` ever trades.

The income test shows two figures: **reported interest** (what the company declared) and **+ assumed
8%** on its short-term investments (the TASIS-style estimate of returns on interest-bearing funds). When
reported interest passes and only the assumption tips a stock over, it goes to `review` with that
reason. The real figure is in the annual report's "Other income" note (gains on mutual funds and
treasury investments). In the first live check, 9 of 9 such stocks were under 3% on their actual reports.

## Comparing with a trusted list

`compare` is read-only. It sorts disagreements into: (1) we say compliant, they do not (report these: they
would point to a screen bug); (2) they say compliant, we block (the safe side); (3) not in our universe.
Free data tends to overstate interest income, so many group-2 stocks fail only the 3% income test. In the
November 2026 check against two Shariah funds the screen agreed on about 81%, and every difference was in
group 2.

## What to tell the user

- Self-screening is an approximation: Yahoo's Indian fundamentals have gaps and its "total revenue"
  may not match the annual report. An official list (NSE Nifty 500 Shariah constituents, or an export
  from a TASIS-based screener) is better when they have one: `build --official`.
- Rebuild monthly and after each results season; `tayyib-risk` warns when the list is over 120 days old.
- Scholars differ on thresholds and on businesses such as media or hotels. Point them to their own
  scholar or a recognised Shariah board. The tool itself never trades a stock its screen does not pass.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- ## Stocks you hold (v0.2.4)

```bash
python3 "${CLAUDE_SKILL_DIR}/halal.py" held            # re-check your open positions now (nothing saved)
python3 "${CLAUDE_SKILL_DIR}/halal.py" held --write    # what the daily list runs: saves the alerts
```

Each held stock is screened again when its screen is older than `halal.held_recheck_days` (7).
Per stock: the status at buy, now, the ratios then and now, the data date and source, and an alert level:
**No longer compliant** (excluded or review, and recorded compliant when bought; for a backfilled
position or an imported holding: **Not compliant now (status at purchase unknown)**. Say it first; offer the SELL ticket and the purification
estimate it gives, never sell or say "sell now", the timing is the user's with their scholar), **Near a
limit**, or **Could not verify** (UNKNOWN: never call it compliant or non-compliant). One alert per status
change; it is resolved when the sale is recorded with `ticket.py close`.

Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
