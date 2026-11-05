# AGENTS.md: using tayyib-trader from any AI assistant

This file is for AI coding agents and assistants (Claude Code, Codex, Cursor, Gemini CLI, Copilot,
Aider and others). Claude reads the `SKILL.md` in each `tayyib-*` folder; everything below works the
same without skills, because every skill is a plain Python 3.8+ script with no dependencies.

## What this is

Halal (Shariah-screened) **swing and delivery** trading tools for Indian stocks (NSE/BSE). It
analyses, plans and checks. It never places an order.

## Non-negotiable rules for agents

1. Only halal-compliant stocks. Run `tayyib-halal` first; never suggest a stock that is not `compliant`.
2. Delivery (CNC) only. Never suggest intraday (MIS), futures, options, short selling, margin or MTF.
3. Never place, modify or cancel an order, and never write code that does. Show the ticket from
   `tayyib-broker show`, ask the user for an explicit yes for that exact order, and let them place it in
   their broker app. Record their fill only when they tell you it (`ticket.py placed`).
4. Say plainly that results are not financial advice and the halal screen is not a fatwa.
5. Do not invent prices, news or ratios. If a data source fails, say which one. If a script cannot
   run at all, say so and stop: never give halal status, setups or levels from memory.
6. Python: use `python3`; on Windows, if it opens the Microsoft Store, use `py`.
7. Settings are validated (`tc.validate_config`). Read out every `CONFIG: ...` note: an invalid or
   unknown setting was ignored and its default used. Never add a config key, flag or code path that
   enables intraday, F&O, short selling, margin/MTF, non-compliant stocks or order placement.
8. Halal thresholds: stricter than TASIS is fine. Looser (debt > 25%, non-compliant income > 3%,
   cash + receivables > 90%, assumed return < 8%, or `allow_review`) only with a `halal.loosen_note`
   naming the user's scholar or source; never fill that note in yourself. If an output starts with
   "Halal thresholds are looser than TASIS (your setting): ...", say that line first.
9. "Why was X picked?": answer from the row's `why[]` in `trader/daily/DATE.json`, quoting the values
   and limits it recorded. Say UNKNOWN where it says UNKNOWN. Never invent reasons, and never show a
   missing value as 0.

## Today's list in one command

```bash
python3 tayyib-daily/daily.py          # after 3:30 PM IST: halal setups with entry, stop, target, qty, PASS/WARN
python3 tayyib-daily/daily.py --risk-preview   # what the risk settings mean in rupees (runs nothing else)
```

## The pipeline (one trade)

Run from the folder where the user keeps their data; files go to `./trader/` (or `$TAYYIB_DIR`).

```bash
python3 tayyib-halal/halal.py build                 # once a month: the halal universe
python3 tayyib-scanner/scan.py --mode swing         # setups on halal stocks -> trader/scan.json
python3 tayyib-news/news.py                         # headlines, HALAL-WATCH flags
python3 tayyib-entry/entry.py check SYMBOL          # WAITING / TRIGGERED / ...
python3 tayyib-exit/exit.py plan SYMBOL --write     # stop, target, time stop -> trader/plan.json
python3 tayyib-timemachine/timemachine.py run --write   # odds in R after charges
python3 tayyib-budget/size.py --write               # quantity -> trader/orders.json
python3 tayyib-risk/check.py                        # PASS / WARN / BLOCK
python3 tayyib-broker/ticket.py show                # the ticket the user places themselves
```

While holding: `tayyib-alerts/alerts.py check`, `tayyib-broker/ticket.py stop|close|positions`.
Research: `tayyib-results/results.py SYMBOL`, `tayyib-insider/insider.py SYMBOL`.
Year end: `tayyib-purify/purify.py report --year 2026`.

Every script accepts `--json` (after the subcommand, where there is one) for machine-readable output.

## MCP

`python3 mcp/server.py` is a stdio MCP server exposing 18 read/analyse/plan tools with no order
placement. See the README for client configuration.

## Developing

- Edit `core/tayyib_core.py`, then `python3 tools/sync_core.py` (each skill folder carries a copy).
- Tests: `python3 -m unittest discover -s tests -v` (offline, synthetic fixtures).
- Standard library only. Python 3.8+. No new dependencies.
- New settings go in `DEFAULT_CONFIG` *and* `DEFAULT_CONFIG_DOCS` (a test fails otherwise). With the
  defaults, decisions must stay identical: `tests/test_v015.py` compares them with the v0.1.4 baseline
  (`tests/baseline.py`). Never regenerate that baseline to make a test pass.
- Record `why[]` items where the decision is made (`tc.why_item`), never recompute them afterwards.
