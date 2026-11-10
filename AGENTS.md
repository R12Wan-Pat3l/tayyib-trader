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
8. Halal rules are fixed in code (v0.2.7): the TASIS limits, `halal.method`, `allow_review` (always off),
   the Nifty 500 list URL, every charge rate and broker table, and the user agent. `validate_config`
   ignores any change to them ("... is fixed and can't be changed"). There are no per-stock overrides:
   `halal_overrides.json` is never read or written. Never add a way to loosen the screen or mark a stock
   compliant by hand; a stricter rule is a code change with tests. The Settings page has only money and
   risk, broker (zerodha / groww), the five strategies (at least one on) and holidays; everything else is
   an advanced config.json key.
9. "Why was X picked?": answer from the row's `why[]` in `trader/daily/DATE.json`, quoting the values
   and limits it recorded. Say UNKNOWN where it says UNKNOWN. Never invent reasons, and never show a
   missing value as 0.
10. Email (`tayyib-email`, v0.2.3) is for the user's own inbox only (at most 3 of their own addresses).
   Never set it up to send the list to other people: that can count as publishing stock recommendations,
   which in India may need SEBI Research Analyst registration; each person runs their own copy. The SMTP
   password is read only from the environment variable `TAYYIB_SMTP_PASSWORD`: never ask for it in the chat,
   never write it to `config.json` or any file, never print or log it.
11. Held stocks (v0.2.4): when `halal.py held` or the daily list says a held stock is "No longer compliant",
   say it first, with its ratios and source. Offer the SELL ticket and the purification estimate; never sell,
   never say it must be sold now (the timing is the user's, with their scholar), and never call a "Could not
   verify" stock compliant or non-compliant. The regime filter stays OFF unless the user switches it on;
   suggest `backtest.py run --regime-compare` first. (v0.2.5) Say "Not compliant now (status at purchase
   unknown)" for a backfilled or imported holding, as the tool does.
12. Holdings import (v0.2.5): `ticket.py import FILE` reads a Zerodha / Groww holdings file the user saved. Run
   the preview first, show the table, and add `--yes` only after the user says yes to that import. Holdings are
   not trades: never give them a stop, target or tracker row, never count them in results, and never present a
   "could not match" row as compliant. Pullback is on by default again since v0.2.6 (default@4 = default@2);
   switch it off only when the user asks.
13. Defaults (v0.2.6): never propose changing a default on one backtest number. Run
   `backtest.py run --years 5 --robust-compare "A" "B"` (and 3 years) and quote its verdict line; only "B is better
   in X of N runs" (80%+) supports a change. "No clear difference" means keep the default.

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

Dashboard (127.0.0.1 only): `python3 tayyib-dashboard/dashboard.py [--port 8765] [--no-browser]`.
Everything is GET / HEAD except exactly two write endpoints: `POST /api/config` (saves `trader/config.json`
through `tc.validate_config`, with a backup) and `POST /api/run` (starts `tayyib-daily`, analysis only, or
`tayyib-backtest run --years 3|5 --mode M [--compare] [--symbols=A,B,... | --holdings] --write` (v0.2.8: the
symbols checked with `tc.check_backtest_symbols` before anything starts), or (v0.2.3) `tayyib-email test`, or (v0.2.5)
`tayyib-broker import trader/import/FILE [--yes]` for a file already in `trader/import/` (Import only after a
Preview of the same file), nothing else).
Both need the Host, Origin, per-start token, JSON type and 64 KB checks. Never add another write endpoint,
and never a button, endpoint or request that places, modifies or cancels an order or talks to a broker.

While holding: `tayyib-alerts/alerts.py check`, `tayyib-broker/ticket.py stop|close|positions|import`,
`tayyib-halal/halal.py held` (re-check the stocks you hold), `tayyib-purify/purify.py estimate SYMBOL --since D`.
Research: `tayyib-results/results.py SYMBOL`, `tayyib-insider/insider.py SYMBOL`.
Backtest: `tayyib-backtest/backtest.py run [--mode all] [--years 3] [--robust [N]] [--robust-compare A B] --write`
(writes only `trader/backtest/`); v0.2.8 "My stocks": `--symbols A,B,...` (1 to 20, each compliant on today's list,
or the run is refused) or `--holdings`. Say the hindsight line first ("You chose these stocks today..."), and never
present a basket result as how the daily list did: "All halal stocks" is that test,
`backtest.py list`, `backtest.py show ID`. Read out every line of its `banners[]` first: they are the
honest limits (today's halal list applied to the past, survivorship bias, news can't be replayed, too few
trades, overfit, the Shariah ETF did better). The Nifty 50 is reference only, never a halal option. A benchmark it could not fetch is UNKNOWN, never 0.
Email (18th skill, `tayyib-email`): `email_report.py send --dry-run` (writes `trader/email/`, sends nothing),
`email_report.py test`, `email_report.py send [--date D]`; `tayyib-daily/daily.py --email` makes the list and
then emails it (the Windows task from `tools/schedule_windows.py show | install --yes | remove --yes`). A
missing password is a clear message, never a crash; the daily list still runs.
Year end: `tayyib-purify/purify.py report --year 2026`.

Every script accepts `--json` (after the subcommand, where there is one) for machine-readable output.

## MCP

`python3 mcp/server.py` is a stdio MCP server exposing 20 read/analyse/plan tools with no order
placement. See the README for client configuration.

## Developing

- Edit `core/tayyib_core.py`, then `python3 tools/sync_core.py` (each skill folder carries a copy).
- Tests: `python3 -m unittest discover -s tests -v` (offline, synthetic fixtures).
- Standard library only. Python 3.8+. No new dependencies.
- New settings go in `DEFAULT_CONFIG` *and* `DEFAULT_CONFIG_DOCS` (a test fails otherwise). With the
  defaults, decisions must stay identical: `tests/test_v015.py` compares them with the v0.1.4 baseline
  (`tests/baseline.py`). Never regenerate that baseline to make a test pass.
- Record `why[]` items where the decision is made (`tc.why_item`), never recompute them afterwards.
- Ranking (default@2): `tc.rank_key` orders the daily list, the sizing order and the top picks. With
  `daily.min_past_trades_for_rank = 0` the baseline test proves every decision is the v0.1.4 one.
- tayyib-backtest must call the live functions (`detect_at`, `liquidity_ok`, `plan_trade`, `choose_candidates`,
  `rank_key`, `tm_history` / `tm_monte_carlo`, `size_trade`, `risk_check_order`, `trade_outcome`, `order_charges`),
  never a copy.
  On day t it may use bars[0..t] only (a test changes every later bar and expects the same plans).
- A future official Shariah-list import may only compare with the self-screen or make it stricter. It must
  never mark a stock compliant on its own.
