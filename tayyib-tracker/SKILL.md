---
name: tayyib-tracker
description: >-
  Paper Tracker in Excel. Records every stock each daily list showed and follows it on the real
  prices afterwards: did it reach the buy price, then hit the target or the stop first, with the
  result in R and rupees after charges. Writes trader/tracker.xlsx (Tracker, Summary, Read me sheets)
  and trader/tracker.csv. Use when the user asks "did yesterday's picks work", "how is the list
  doing", "did it hit the target", "show my tracker", "paper trading results", "open the Excel". Also the
  paper account (PASS picks only, one cash account) and the 15-day report to share: "how is my paper
  account", "paper account", "make my report", "15-day report".
argument-hint: "[summary | paper | report [--days 15] | update | export | add --from-daily DATE]"
---

# tayyib-tracker

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-tracker/tracker.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/tracker.py" summary      # how every earlier list did (all checks)
python3 "${CLAUDE_SKILL_DIR}/tracker.py" paper        # v0.2.9: the paper account -> trader/paper_account.json
python3 "${CLAUDE_SKILL_DIR}/tracker.py" report       # v0.2.9: paper account + trader/reports/DATE.md (last 15 days)
python3 "${CLAUDE_SKILL_DIR}/tracker.py" report --days 30
python3 "${CLAUDE_SKILL_DIR}/tracker.py" update       # re-follow unfinished rows on the latest prices
python3 "${CLAUDE_SKILL_DIR}/tracker.py" export       # write trader/tracker.xlsx and tracker.csv
python3 "${CLAUDE_SKILL_DIR}/tracker.py" migrate      # apply the REPLACED / ALREADY_HELD rule (no prices)
python3 "${CLAUDE_SKILL_DIR}/tracker.py" add --from-daily 2026-11-04
```

`tayyib-daily` runs `add`, `update` and `export` itself on every run, and puts a "How earlier
lists did" table at the bottom of the daily list. So normally the user just opens
`trader\tracker.xlsx` in Excel.

It records every row, PASS, WARN and BLOCK alike, so the user can see whether the risk check helped
(the Summary sheet compares them). It uses the plan's own rules:
- **Bought:** the price reached "Buy above" within its valid days.
- **Fill day:** if the price touched the stop and closed under the buy price, that's a stop.
- **Gaps** through the stop fill at the open.
- **Both stop and target touched** on the same day counts as the stop.
- **Swing:** the stop moves to the buy price at +1R.
- **Time exit** after the plan's holding days.

Statuses: WAITING, NOT TRIGGERED, OPEN, TARGET, STOP, BREAKEVEN, TIME EXIT. Kept for the record but
never followed or counted: SUPERSEDED (the same date's list re-made with other settings), REPLACED (a
later list showed the stock again while this row was still waiting) and ALREADY_HELD (a later listing of
a stock an earlier row already held). A stock is counted once while it is waiting or held.

## Paper account and the 15-day report (v0.2.9)

The tracker counts every pick; the **paper account** copies what the user would do with real money: only PASS
picks, from lists dated on or after `paper.start` (default 2026-11-10, the first default@5 list), in each list's
order, one position per stock, at most `max_open_positions` open or waiting to buy, cash from the capital that
never goes below zero (sale proceeds usable from the next day), the list's quantity. A PASS pick it can't take is
SKIPPED with the reason (slots full, not enough cash, already held / already waiting, no prices = UNKNOWN). Fills,
exits and charges are the tracker's own. Benchmark: the Shariah BeES bought with the same capital on the start
date (UNKNOWN with the reason if it can't be fetched).

`report` writes `trader/reports/DATE.md` (short enough to paste into a chat) and `.json`. The daily run writes one
by itself when the last is `report.every_days` (15) days old, and the email attaches it. When presenting:
- Say the banners first: "Paper only: nothing was bought." and, under 30 closed trades, "Too early to judge: N
  closed trades (need 30+)."
- Lead with the paper account (PASS only), compared with the Shariah BeES over the same dates. The full tracker
  section "includes WARN/BLOCK picks you would not buy": reference only, never the headline.

How to present it:
- This is paper, not real trades. Nothing was bought.
- Lead with closed trades: count, win rate, average R. Under 30 closed trades is too few to judge;
  say so plainly and do not draw conclusions from a few weeks.
- If Excel has the file open, a copy is written with the time in its name.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
