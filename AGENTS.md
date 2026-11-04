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
5. Do not invent prices, news or ratios. If a data source fails, say which one.

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

`python3 mcp/server.py` is a stdio MCP server exposing 16 read/analyse/plan tools with no order
placement. See the README for client configuration.

## Developing

- Edit `core/tayyib_core.py`, then `python3 tools/sync_core.py` (each skill folder carries a copy).
- Tests: `python3 -m unittest discover -s tests -v` (offline, synthetic fixtures).
- Standard library only. Python 3.8+. No new dependencies.
