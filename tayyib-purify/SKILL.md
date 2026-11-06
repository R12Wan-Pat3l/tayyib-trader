---
name: tayyib-purify
description: >-
  Purification Calculator. Works out how much of the user's dividends (and, if they
  choose, realised gains) to give to charity for the non-compliant share of each company's income, using
  the ratio from the halal screen or one the user gives. Use when the user asks "how much should I
  purify", "purification of dividends", "safai / tazkiya of income", "I got a dividend from X", or at the
  end of the year.
argument-hint: "[add-dividend SYMBOL AMOUNT | report [--year] [--include-gains]]"
---

# tayyib-purify

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-purify/purify.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

```bash
python3 "${CLAUDE_SKILL_DIR}/purify.py" add-dividend TCS 2400 --date 2026-07-20
python3 "${CLAUDE_SKILL_DIR}/purify.py" add-dividend XYZ 500 --ratio 2.1   # when the screen has no ratio
python3 "${CLAUDE_SKILL_DIR}/purify.py" report --year 2026
python3 "${CLAUDE_SKILL_DIR}/purify.py" report --year 2026 --include-gains
```

Amount to purify = income x (non-compliant income % of that company). Many contemporary scholars hold
that this part of a dividend must be given away to charity (not counted as one's own zakat or sadaqah);
some advise doing the same for capital gains as a precaution. This is arithmetic only: the ruling, and
whether gains are included, is for the user's scholar. If the user writes in Roman Urdu or asks in an
Islamic-studies frame, answer in that register and cite sources carefully.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- ## A held stock that stopped passing (v0.2.4)

```bash
python3 "${CLAUDE_SKILL_DIR}/purify.py" estimate SYMBOL --since YYYY-MM-DD   # the date of the "No longer compliant" alert
```

The non-compliant share of the dividends received while holding it, plus any gain since the change. Always
say it is an estimate: confirm with your scholar. A part it cannot work out is UNKNOWN, never 0.

Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
