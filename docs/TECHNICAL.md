# Technical guide

For developers and anyone who wants to run the scripts directly. For the plain-words version, see
[How it works](HOW_IT_WORKS.md).

## Requirements

- Python 3.8 or newer, **standard library only**: no `pip install`.
- Windows: use `py` wherever this guide says `python3` (on many machines, `python3` opens the Microsoft Store).
- Network access to Yahoo Finance, niftyindices.com, nseindia.com, news.google.com and the RSS feeds.

## Install

| way | how |
|---|---|
| Claude Code plugin | `/plugin marketplace add R12Wan-Pat3l/tayyib-trader`, then `/plugin install tayyib-trader@tayyib-trader`. Update: `claude plugin update tayyib-trader@tayyib-trader` |
| Plain skills | `git clone https://github.com/R12Wan-Pat3l/tayyib-trader.git`, then copy the `tayyib-*` folders to `~/.claude/skills/`. Each folder is self-contained, but `tayyib-daily` needs the others next to it |
| Any MCP client | `python3 mcp/server.py` over stdio. 17 tools, none of which place orders. Config below |
| Other AI agents (Codex, Gemini CLI, Aider...) | Point them at [AGENTS.md](../AGENTS.md) |
| No AI | Run the scripts. Each one has `--help` and `--json` |

MCP client configuration:
```json
{ "mcpServers": { "tayyib-trader": {
    "command": "python3",
    "args": ["/ABSOLUTE/PATH/tayyib-trader/mcp/server.py"],
    "env": { "TAYYIB_DIR": "/ABSOLUTE/PATH/your-data/trader" } } } }
```

## Layout

```
core/tayyib_core.py      shared library (config, data, indicators, setups, charges, halal, guards)
tools/sync_core.py       copies the core into every skill folder (--check verifies)
tayyib-<skill>/          SKILL.md (instructions for Claude) + one script + a copy of tayyib_core.py
mcp/server.py            stdio MCP server wrapping the scripts
tests/                   offline unittest suite + make_fixtures.py (synthetic data, real formats)
AGENTS.md                rules and commands for non-Claude agents
```

Always edit `core/tayyib_core.py` and then run `python3 tools/sync_core.py`. Never edit the copies.

## The pipeline and its files

All state lives in `./trader/` (override with `TAYYIB_DIR`):

| step | command | reads | writes |
|---|---|---|---|
| halal | `tayyib-halal/halal.py build \| check \| list \| compare \| override` | Nifty 500 CSV, Yahoo fundamentals | `halal_universe.json`, `halal_overrides.json` |
| scan | `tayyib-scanner/scan.py --mode swing\|delivery\|all` | universe, Yahoo daily bars | `scan.json` |
| news | `tayyib-news/news.py --symbols A,B` | RSS, Google News, NSE | `news.json` |
| entry | `tayyib-entry/entry.py check SYM [--mode]` | scan, bars | `entries.json` |
| exit | `tayyib-exit/exit.py plan SYM [--setup] [--mode] --write` | scan/entries | `plan.json` |
| time machine | `tayyib-timemachine/timemachine.py run [SYMS] --write` | plans, bars | `sim.json` |
| size | `tayyib-budget/size.py [SYMS] --write` | plans, positions | `orders.json` |
| risk | `tayyib-risk/check.py [SYMS]` | orders, positions, universe, news, sim | statuses in `orders.json`, `risk.json` |
| ticket / journal | `tayyib-broker/ticket.py show \| placed \| stop \| close \| positions` | orders | `positions.json` |
| alerts | `tayyib-alerts/alerts.py add \| check \| list` | plans, positions | `alerts.json` |
| results | `tayyib-results/results.py SYM` | Yahoo quarterly + annual | `results/SYM.json` |
| insider | `tayyib-insider/insider.py SYM` | NSE PIT, bulk/block deals | `insider.json` |
| purify | `tayyib-purify/purify.py add-dividend \| report` | universe ratios, positions | `purification.json` |
| **daily** | `tayyib-daily/daily.py [--mode] [--top 10] [--picks 3] [--no-news] [--no-rebuild]` | all of the above | `daily/DATE.md`, `daily/DATE.json` |

What `daily` does:
- It rebuilds the halal list on the first run, and again whenever the list is `halal.auto_rebuild_days` (default 30) old.
- It keeps one setup per stock. With `--mode all` it alternates swing and delivery.
- It skips stocks you already hold or have placed.
- Orders are sized best expectancy first.
- It then risk-checks the whole orders file, so its statuses always match a plain `check.py`.
- Earlier unplaced tickets are removed, and it reports which ones. Placed orders are never touched.

## Rules in code (not configurable)

`tc.guard_order` and `tayyib-risk` enforce:
- CNC only
- BUY to open
- SELL never more than held
- no derivatives
- no margin or MTF
- halal `compliant` only (unless `halal.allow_review`)

A second ticket for an already-placed signal is blocked. No module contains order-placement code, and a
test fails if one appears. The MCP server has no order tool.

## Config (`trader/config.json`, merged over the defaults)

| key | default | meaning |
|---|---|---|
| `capital` | 100000 | rupees |
| `max_risk_per_trade_pct` / `max_risk_per_trade_rs` | 1.0 / null | loss at stop incl. charges |
| `max_position_pct` | 20 | per stock |
| `max_open_positions` | 6 | open + pending approved tickets |
| `max_portfolio_heat_pct` | 6 | total open risk |
| `max_positions_per_industry` | 2 | |
| `min_reward_risk` | 1.5 | net of charges |
| `min_price`, `min_turnover_rs` | 20, 2 crore | liquidity filter |
| `modes.swing` | stop cap 10%, 2R target, 20 sessions | |
| `modes.delivery` | stop cap 15%, 3R review, 250 sessions | |
| `broker` | zerodha | `zerodha`, `groww`, `custom` (see `brokers`) |
| `charges` | 2026 NSE delivery rates | STT 0.1%, txn 0.00297% + IPFT 0.0001%, SEBI, stamp 0.015%, GST 18% |
| `halal.max_debt_to_assets_pct` / `max_noncompliant_income_pct` / `max_cash_receivables_to_assets_pct` | 25 / 3 / 90 | TASIS |
| `halal.noncompliant_investment_return_pct` | 8 | assumed return on short-term investments |
| `halal.allow_review` | false | let `review` stocks through with a WARN |
| `halal.auto_rebuild_days` | 30 | `daily` rebuilds when older (0 = never) |
| `holidays` | [] | NSE holidays, `YYYY-MM-DD` (used for plan dates) |

## Data endpoints (free, unofficial)

| data | endpoint |
|---|---|
| bars | `query1.finance.yahoo.com/v8/finance/chart/SYM.NS?range=2y&interval=1d` |
| fundamentals | `query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/SYM.NS` |
| universe | `niftyindices.com/IndexConstituent/ind_nifty500list.csv` |
| NSE | `/api/corporate-announcements`, `/api/corporates-pit`, `/api/historical/bulk-deals` and `block-deals` (cookie from a page visit; 403s are common) |
| news | Google News India RSS search, plus the feeds in `config.news.feeds` |

Failures are reported and never filled with guesses: missing data gives `unknown` or `UNKNOWN`, never zero.

## Tests

```bash
python3 -m unittest discover -s tests          # offline, synthetic fixtures, real data formats
python3 tools/sync_core.py --check
python3 tests/make_fixtures.py                 # regenerate fixtures
```

Live checks against real data: [TESTING.md](../TESTING.md).

## Releasing

1. Bump the version everywhere: `.claude-plugin/plugin.json`, `VERSION` in `core/tayyib_core.py` (then sync) and in `mcp/server.py`, and add a new top entry to `CHANGELOG.md`. `claude plugin update` only compares this number, and `tests/test_repo.py` fails if they disagree.
2. Make sure the tests pass and the sync check is clean.
3. Tag `vX.Y.Z`, push the tag, then publish the GitHub release with the changelog section.
