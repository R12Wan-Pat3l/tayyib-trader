# Technical guide

For developers and anyone who wants to run the scripts directly. For the plain-words version, see
[How it works](HOW_IT_WORKS.md).

## Requirements

- Python 3.8 or newer, **standard library only**: no `pip install`.
- Windows: use `py` wherever this guide says `python3` (on many machines, `python3` opens the Microsoft Store).
- Network access to Yahoo Finance, niftyindices.com, nseindia.com, news.google.com and the RSS feeds.

**Requests (v0.1.9 audit).** No bot-check circumvention anywhere in the project.

| source | sent by | headers |
|---|---|---|
| NSE API (announcements, insider PIT, bulk / block deals) | `tc.NSESession` (tayyib-news, tayyib-insider) | `User-Agent: tayyib-trader/<VERSION> (+https://github.com/R12Wan-Pat3l/tayyib-trader)` (`tc.HONEST_UA`), `Accept: application/json`. No cookie warm-up, no Referer, no browser headers |
| BSE | nothing fetches BSE | (links only, opened by the user) |
| Yahoo Finance charts and fundamentals | `tc.fetch` | `User-Agent: tayyib-trader/0.1 (+https://github.com/...)` (the default `user_agent`), `Accept: */*`, `Accept-Encoding: gzip` |
| Google News RSS, Moneycontrol / ET / Livemint RSS | `tc.fetch` | the same as Yahoo |
| niftyindices.com Nifty 500 list | tayyib-halal `build` | `tc.fetch`'s honest default (since the v0.1.9 review; `BROWSER_UA` is gone from the code) |

**Nifty 500 list fallbacks (`halal.load_parent`):** a successful download (a CSV with a Symbol column and
rows, every row with a symbol) is kept as `trader/cache/parent_list.csv` with `parent_list.json`
`{url, downloaded, rows}` (temp file + replace). If the download is refused or is not a constituents list:
(a) that last good copy, with its age; (b) the user's `ind_nifty500list.csv` in the data folder (its
file date); (c) otherwise `halal.py build` exits 1 with "Could not get the Nifty 500 list (...) and there
is no saved copy. Download it yourself: ..." and writes nothing. A broken cache or user file is skipped
and named, never partly used. The universe records `parent_list{kind (download / cache / user_file /
file), url, date, age_days, note}`; the build prints the note (`notes[]` in `--json`), tayyib-daily adds
it to the list's notes after a rebuild, and the dashboard's Halal tab shows "Nifty 500 list: downloaded
2026-11-05 (0 days old)" or "the saved copy of 2026-10-01 (35 days old): the download was refused".

NSE refusals: after the first refusal or timeout in a run, `NSESession` does not ask again (one polite
attempt per run); each later call fails with "not tried: NSE refused automated access earlier in this
run". `tc.fetch_reason` turns an error into plain words ("NSE refused automated access", "NSE did not
answer", "NSE failed: HTTP 503").

## Install

| way | how |
|---|---|
| Claude Code plugin | `/plugin marketplace add R12Wan-Pat3l/tayyib-trader`, then `/plugin install tayyib-trader@tayyib-trader`. Update: `claude plugin update tayyib-trader@tayyib-trader` |
| Plain skills | `git clone https://github.com/R12Wan-Pat3l/tayyib-trader.git`, then copy the `tayyib-*` folders to `~/.claude/skills/`. Each folder is self-contained, but `tayyib-daily` needs the others next to it |
| Any MCP client | `python3 mcp/server.py` over stdio. 20 tools, none of which place orders. Config below |
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
tayyib-<skill>/          SKILL.md (instructions for Claude) + one script + a copy of tayyib_core.py (18 skills)
mcp/server.py            stdio MCP server wrapping the scripts
tayyib-dashboard/        dashboard.py (local web server) + actions.py (save settings, backups, run) + index.html (one page, inline CSS/JS/SVG)
design-system/tayyib/    the dashboard's design system (MASTER.md, pages/dashboard.md); not shipped code
tests/                   offline unittest suite + make_fixtures.py (synthetic data, real formats)
AGENTS.md                rules and commands for non-Claude agents
```

Always edit `core/tayyib_core.py` and then run `python3 tools/sync_core.py`. Never edit the copies.

## The pipeline and its files

All state lives in `./trader/` (override with `TAYYIB_DIR`):

| step | command | reads | writes |
|---|---|---|---|
| halal | `tayyib-halal/halal.py build \| check \| list \| compare \| override \| held` | Nifty 500 CSV, Yahoo fundamentals | `halal_universe.json`, `halal_overrides.json`; `held --write`: `held_halal.json`, halal alerts in `alerts.json`, `halal_at_buy` on positions |
| scan | `tayyib-scanner/scan.py --mode swing\|delivery\|all` | universe, Yahoo daily bars | `scan.json` |
| news | `tayyib-news/news.py --symbols A,B` | RSS, Google News, NSE | `news.json` |
| entry | `tayyib-entry/entry.py check SYM [--mode]` | scan, bars | `entries.json` (the exit planner uses a record only once TRIGGERED, or when the scan has no newer signal) |
| exit | `tayyib-exit/exit.py plan SYM [--setup] [--mode] --write` | scan/entries | `plan.json` |
| time machine | `tayyib-timemachine/timemachine.py run [SYMS] --write` | plans, bars | `sim.json` |
| size | `tayyib-budget/size.py [SYMS] --write` | plans, positions | `orders.json` |
| risk | `tayyib-risk/check.py [SYMS]` | orders, positions, universe, news, sim | statuses in `orders.json`, `risk.json` |
| ticket / journal | `tayyib-broker/ticket.py show \| placed \| stop \| close \| positions \| import` | orders; a holdings export in `trader/import/` | `positions.json` (+ `positions.backup-*.json` on import) |
| alerts | `tayyib-alerts/alerts.py add \| check \| list` | plans, positions | `alerts.json` |
| results | `tayyib-results/results.py SYM` | Yahoo quarterly + annual | `results/SYM.json` |
| insider | `tayyib-insider/insider.py SYM` | NSE PIT, bulk/block deals | `insider.json` |
| purify | `tayyib-purify/purify.py add-dividend \| report` | universe ratios, positions | `purification.json` |
| tracker | `tayyib-tracker/tracker.py add --from-daily DATE \| update \| report \| export` | daily lists, bars | `tracker.json`, `tracker.xlsx`, `tracker.csv` |
| **daily** | `tayyib-daily/daily.py [--mode] [--top N] [--picks N] [--no-news] [--no-rebuild] [--risk-preview]` | all of the above | `daily/DATE.md`, `daily/DATE.json` |

What `daily` does:
- It rebuilds the halal list on the first run, and again whenever the list is `halal.auto_rebuild_days` (default 30) old.
- It keeps one setup per stock. With `--mode all` it alternates swing and delivery.
- It skips stocks you already hold or have placed.
- Orders are sized in rank order (`tc.rank_key`, default@2): stocks with at least
  `daily.min_past_trades_for_rank` (8) past trades of their setup first, best time-machine expectancy
  first; then the rest by setup score. The same key orders the rows inside each PASS / WARN / BLOCK group
  and so picks the top picks. Because the risk check fills limits in file order, it also decides which
  tickets the position, heat, cash and industry limits block. With the key at 0 the order is the v0.1.4
  one (expectancy only), and the baseline test proves every decision is then identical.
- When NSE announcements or Google News failed for any of today's stocks, the list gets one banner in
  `banners[]` (`.json`) and at the top of the `.md` (v0.1.9 wording): "Exchange filings unavailable today (NSE refused automated access). HALAL-WATCH and results checks are incomplete for N of M stocks: check the announcements yourself for any stock you plan to buy." With Google News too:
  "Exchange filings and Google News unavailable today (NSE refused automated access; Google News did not
  answer). ...". Per row, the NEWS `why[]` items stay UNKNOWN. No verdict changes.
- **Sources in why[] NEWS (v0.1.9):** `news.json` has `sources{SYM: {answered[], failed{source: reason}}}`
  (Google News, NSE announcements) and `feeds{answered[], failed{}}` (the market RSS feeds, fetched once).
  A check with no flagged headline says "N headlines in the last 72 hours checked (news of ...; answered:
  Google News, NSE announcements, 4 RSS feeds)" or, when a source needed for the stock failed, "UNKNOWN: a
  source for this stock failed (NSE announcements: NSE refused automated access); ...; answered: Google
  News, 4 RSS feeds". A failed market feed is named but does not make the check UNKNOWN (as before).
- **Two NEWS lines (v0.1.10, display only):** `news_why` (tayyib-risk) writes the NEWS items per source,
  not per check: `check` is `tc.NEWS_MEDIA` "Media news" (Google News for the stock + the market RSS
  feeds) or `tc.NEWS_FILINGS` "Exchange filings (NSE)" (NSE corporate announcements, incl. board-meeting
  notices). Each line is one ok=False item per flagged headline (note "HALAL-WATCH: new debt: WARN (...)"
  or "results news in the window: gaps are likely: WARN (...)"), else ok=True value "none flagged".
  Media news is UNKNOWN (ok=None) when Google News failed for the stock or no media source answered; a
  failed market feed alone is only named. Exchange filings: when NSE refused automated access
  (`tc.nse_blocked`: "refused", HTTP 401 / 403 / 429, or "not tried" after a refusal) the item is
  value "Not available", `op` "not_available" (`tc.NA_OP`), ok=None, note "NSE blocks automated access →
  check yourself (reason)": never a pass. Any other NSE failure (5xx, unreachable, not JSON, timeout) is
  UNKNOWN: "UNKNOWN: NSE announcements failed (reason)". NSE turned off in Settings: value "not checked",
  ok=None. The dashboard's `why_view` gives that item mark "na" and symbol "–" (a neutral circle-dash
  icon); `news_lines(why)` gives the cards and tickets `[{label, state ok/failed/unknown/na, text}]`
  (tickets read the why[] from `risk.json`); the daily `.md` writes one sub-line per item under
  "NEWS:". The WARNs (and so PASS / WARN / BLOCK) still come from the headlines in `check_order`, not
  from these lines; lists written before v0.1.10 keep their per-check items and show no card lines.
- **Check announcements yourself (v0.1.9):** `tc.manual_links(sym, rec)`: the NSE company page
  `https://www.nseindia.com/get-quotes/equity?symbol=SYM`, and on BSE the stock page
  `https://m.bseindia.com/StockReach.aspx?scripcd=CODE` when a scrip code is already known locally
  (`bse_code` in the universe record; none is today), otherwise BSE's Get Quote search
  `https://www.bseindia.com/getquote.aspx` with "search for ISIN ..." (BSE has no verified URL that takes an
  ISIN, so none is guessed). In the `.md` under each top pick; in the dashboard on top-pick cards, ticket
  cards and the Why drawer's NEWS section, with a **Copy ISIN** button next to the BSE search link (the
link's `copy` field; the shared Copy helper says "Copied ✓") (`target="_blank" rel="noopener noreferrer"`, and the page
  accepts only `https://www|m.nseindia.com|bseindia.com/` URLs). The tool never fetches them; the daily
  JSON rows are unchanged.
- It then risk-checks the whole orders file, so its statuses always match a plain `check.py`.
- Earlier unplaced tickets are removed, and it reports which ones. Placed orders are never touched.
- Finally it records the list in the tracker, follows every unfinished earlier row (`tc.trade_outcome`)
  and writes the Excel file. Use `--no-track` to skip this. The `.xlsx` file is written with the standard
  library (zipfile plus SpreadsheetML), with 3 sheets: Tracker, Summary and Read me.

## Backtest (`tayyib-backtest`, v0.2.0, closer to live in v0.2.1, dashboard tab v0.2.2)

`backtest.py run [--mode] [--setups] [--years 3 | --from --to] [--capital] [--max-positions 5] [--split]
[--no-take-warn] [--no-late] [--compare] [--regime R] [--regime-compare] [--robust [N]] [--robust-compare A B]
[--write] [--json]`, `list`, `show ID`.

**Window end (v0.2.2):** without `--to`, `default_end(now, cfg)` picks the last completed session: today
once it is 15:30 IST on a trading day (`tc.is_trading_day`: weekends and `holidays`), otherwise the
previous trading day. A stock with no bar on that day ends on its session before. The rule is recorded
as `params.end_rule` / `window.end_rule`; with `--to` it is "--to DATE".

**Late joiners (v0.2.2):** `--no-late` simulates without the stocks in `joined_late[]` (same bars).
`late_joiners {stocks, trades, pnl_rs, total_pnl_rs, pct_of_total, excluded, text}` is always in the
result and the .md: "Late joiners: N stocks, contributing X% of total P&L" from the as-run trades;
`pct_of_total` is null (UNKNOWN in the text) when the total P&L is not positive. `--compare` adds
`compare.no_late` (c): the as-run simulation without them, from the same bars (with `--no-late` it is (a)).
Saved runs also carry `run_at` and, for an OK benchmark, `curve: [[date, value]]` (buy and hold from the
capital, sell charge on the last day) for the dashboard chart. Writes `trader/backtest/<id>.json` and `.md` with `--write`, and
nothing else (prices go to `trader/cache/`, range `5y` for 3 years, `10y` / `max` for longer). The id is
`<to>_<mode>_<from>_<hash6>` of the parameters, the settings hash and the universe, so the same inputs
give the same file, byte for byte.

It calls the live functions, never copies. To make that possible v0.2.0 moved four things into core with
no change in behaviour (the old names are aliases, and the v0.1.4 baseline test still passes):
`tc.size_trade` (was `size.size`), `tc.choose_candidates` (was `daily.choose`), `tc.tm_walk`,
`tc.tm_monte_carlo`, `tc.tm_history`, `tc.tm_cost_r` (were in `timemachine.py`), plus `tc.detect_at`
(`detect_all` with the indicators already computed; `detect_all` now calls it). `tc.yahoo_symbol` passes an
index symbol (`^NSEI`) through unchanged. v0.2.1 moved tayyib-risk's check into core the same way:
`tc.risk_check_order` (was `check.check_order`) and `tc.risk_news_why` (was `check.news_why`), with two optional
arguments only the backtest uses: `today` (the date for the plan-expiry check) and `replay=True` (leaves out the
halal list's age and the news). With the defaults it is the live check, byte for byte.

| step | how |
|---|---|
| universe | `halal_universe.json` stocks whose `tc.halal_status` (overrides last) is `compliant`; never review |
| data | `get_daily_bars(sym, range)`, cut at `--to`. A stock joins on the first day it has 250 bars (`join_date`; no signals before), listed in `joined_late[]` when that is after the window start; one that never gets there by `--to` (or has no data) is in `skipped[]` with the reason; gaps stay gaps |
| each close t | per stock: `tc.detect_at(bars, ind, i)` (indicators are causal: bar i uses bars 0..i), `tc.liquidity_ok(bars[:i+1])`, `tc.plan_trade`; best score first, the scanner's top `max(2 x daily.top, 25)`, held / waiting stocks dropped, `tc.choose_candidates` |
| ranking | `tc.rank_key` + symbol (ties). Expectancy and past trades from `tm_history` / `tm_monte_carlo` (3000 runs, seed 7: tayyib-daily's) on the stock's last 2 years up to t, run only when the order can change what is bought: more picks than free slots, not enough cash for all of them, or one of them would be blocked (or WARNed with `--no-take-warn`) with all the others approved. Every limit only tightens with more approved orders, so otherwise no order changes the result. With `--no-take-warn` the Monte Carlo runs for every pick (its negative-expectancy WARN then matters); `daily.min_expectancy_r` applies |
| sizing | `tc.size_trade(plan, cfg, cash)` in rank order, where cash = cash - cash promised to waiting plans, and each sized plan uses up cash for the next (as `size.py`, even one the risk check then blocks); capital is the configured capital, as live |
| risk check (v0.2.1) | `tc.risk_check_order(order, cfg + cash_available=cash, held positions, uni, {}, extras..., sim, today=day, replay=True)`, in rank order like `check.py`: waiting plans and plans approved earlier that day count as approved tickets (heat, count, industry, cash). Replayed: hard rules, halal status, loss at stop, max position %, cash, `max_open_positions`, portfolio heat, positions per industry, net reward:risk, plan expiry, time-machine expectancy WARN. Not replayed (counted in `counts.not_replayed`): news / HALAL-WATCH, halal list age. BLOCK is never placed; WARN only with `take_warn` (default true, `--no-take-warn`); reasons in `counts.risk_blocked` / `risk_warned` |
| account | one cash balance, never negative; at most `--max-positions` held + waiting; one per symbol; a plan waits until `valid_until` |
| outcome | `tc.trade_outcome(bars, plan, cfg, today=to)`: buy-stop fill at max(open, entry), gap through the stop at the open, stop + target on one day = stop, swing breakeven at +1R, time stop at that day's close. A fill is paid from cash free that day: not other plans' cash and (v0.2.1) not that day's sale proceeds, which count from the next trading day. A gap up that needs more cuts the quantity (`counts.qty_cut_at_fill`) |
| charges | `tc.order_charges` on every buy and sell; still open on the last day: valued at the last close after the sell charge (`OPEN AT END`) |

`--compare` (v0.2.1) runs `simulate` a second time on the same bars with `rank="score"` (setup score, ties by
symbol; no time machine) and (v0.2.2) a third time without late joiners, and adds
`compare{as_run, score_only, no_late, note}` (overall metrics, by-mode trades and
expectancy, out-of-sample expectancy). The result's `rules[]` lists what is and is not replayed.

Result JSON: `id, version, params, settings{label, hash, differs_from_default, capital, ...}, window{from, to,
split, first_day, last_day, trading_days, price_range}, universe{list_updated, statuses, compliant, tested,
joined_late, skipped}, skipped[{symbol, reason}], joined_late[{symbol, join_date, data_starts}], banners[],
metrics{overall, by_setup{}, by_mode{}}, split{in_sample,
out_of_sample}, benchmarks{SHARIABEES.NS, ^NSEI}, counts{}, rules[], trades[], equity_curve[{date, equity,
cash, open_positions, waiting_plans}], compare (with --compare), disclaimer`. `counts`: plans, not_triggered,
no_slot, not_sized, no_cash_at_fill, qty_cut_at_fill, risk_checked, risk_blocked_plans, risk_blocked{reason: n},
risk_warned{reason: n}, warn_taken, warn_skipped, not_replayed{news / HALAL-WATCH, halal list age}. Every
by_setup, by_mode, in_sample and out_of_sample group has `too_few` (under 30 trades). Each trade: `symbol, setup, mode, signal_date,
entry_date, entry_price, exit_date, exit_price, exit_reason, qty, charges, pnl_rs, r` plus the plan levels.
Metrics: `trades, win_rate_pct, avg_r, avg_win_r, avg_loss_r, expectancy_r` (p x avg win + (1 - p) x avg
loss, equal to avg_r), `profit_factor` (null with a note when nothing lost), `pnl_rs, total_return_pct,
cagr_pct, max_drawdown_pct, drawdown_peak, drawdown_trough, longest_losing_streak, exposure_pct,
total_charges_rs`. Setup and mode groups use a realised curve (capital + their closed P&L). In / out of
sample split trades by signal date; their return, CAGR and drawdown come from the account's equity on each
side. Benchmarks: all the capital at the first close (fractional units), one buy and one sell charge;
UNKNOWN with `reason` when they cannot be fetched, never 0.

Banners: always the four limits (today's halal list, survivorship, past results, news can't be replayed);
plus "Too few trades to judge." under 30 trades, "Out-of-sample results are much weaker..." when the in-sample expectancy is
positive and the out-of-sample one is under half of it (including below 0), "Buying and holding the
Shariah ETF did better." when the strategy's CAGR is lower, a line saying the ETF comparison was
impossible when the ETF is UNKNOWN, and "The Nifty 50 (not halal-screened, price only) did better..." when
its CAGR is higher (reference only, not a halal option).

MCP: `backtest_run` (never passes `--write`; `take_warn`, `compare`) and `backtest_list` (list, or show with `id`).

## Pullback back on (v0.2.6, default@4); default@3 is historic

`scanner.setups.pullback.enabled` is True again; `DEFAULTS_VERSION` 4. `tests/fixtures/defaults_versions.json`
version 4 equals version 2 on every v2 key (plus the four `regime.*` keys added off in v0.2.4). `test_v026` checks
`pipeline(config=None)` against the **default@2** snapshot with no allowed new keys and the same sha256; no
default@4 snapshot is written (it would be default@2). `test_v025` keeps the history: `PULLBACK_ON` == default@2,
`PULLBACK_OFF` == default@3. `tc.DEFAULTS_HISTORY` names every version; `settings_snapshot()` has `same_as`:
"default@2" for default@4 (or account facts only), "default@3" when the only decision difference is pullback off,
else None. The label stays `default@4` or the hash. The Settings note is `tc.PULLBACK_NOTE`.

`tc.pullback_migration()` (v0.2.6, run by `daily.py` before it loads the config, once per folder, recorded in
`trader/notices.json` as `pullback_on_v026`) never writes `config.json`. Following the default (no
`scanner.setups.pullback.enabled` in `config.json`) moves to default@4 by itself. A folder with an earlier daily list
gets `PULLBACK_BANNER` ("Pullback is back on by default (v0.2.6): ...") once, on the next written list
(`pullback_banner_shown`). An explicit pullback setting (`pullback_set_by_user`: the Settings page writes only keys
you change): left alone, no banner. New folder: nothing. A v0.2.5 notice whose banner was not shown yet is marked
`superseded` (`replaced_v025_banner`), so that folder sees only the new banner. `PULLBACK_BANNER_V025` is never
shown again. Tracker rows keep their stored labels (default@2, default@3).

## Robustness (`--robust`, `--robust-compare`, v0.2.6)

`backtest.py run ... --robust [N]` (N defaults to 20 when the flag is given, 1 to 50, else exit 1) and
`--robust-compare "A" "B"` (N from `--robust`, else 20).

- **Seeds.** Seed s = 1..N changes two things only:
  - `tie_key(s)`: equal-ranked signals are ordered by sha1("s:SYMBOL"), not by the symbol. This applies in the
    scanner's score sort (`_choose_day`), in `rank_day`'s `rank_key` + tie, and in the score-only and "not needed"
    orders of `place_day`.
  - `seed_shift(s)` = `random.Random(s).choice((-1, 1))`: the start moves one trading day (`shifted_start` over every
    bar date).

  The end, split, settings and bars stay the same. Without a seed the order is by symbol, as before: plain runs,
  their JSON and their ids are byte-identical (`params` gets `robust`, `robust_given`, `robust_compare` only when
  used).
- **Sensitivity.** `ROBUST_MAX_POSITIONS` (3, 5, 8): the plain run with only `max_positions` changed (the main run
  is reused for its own value).
- **Same bars.** Everything runs on the bars `run()` loaded once. `RunCache` holds the indicators (`Book`), each
  day's raw candidates (key: settings digest, stock set, mode, setups, date) and each pick's time-machine answer
  (key: settings digest, symbol, signal date, setup, entry, stop, target). Picks are copied out, so a seed never
  sees another run's fields. A simulation gives the same result with or without the cache (test). Causality is
  unchanged (test_v020's look-ahead test, repeated with a seed and the cache). Benchmarks are fetched once per symbol
  (`_memo_fetch`).
- **Report.** `robust{runs[], summary, max_positions[], settings{label, settings_label, hash, same_as}, regime, note}`:
  - each run: `seed, shift_days, start, tie_first[5], overall{cagr_pct, expectancy_r, max_drawdown_pct, trades,
    win_rate_pct}, by_mode{}, by_setup{}, benchmark_cagr_pct, beat_benchmark`;
  - `summary.overall/by_mode/by_setup`: per metric `distribution()` = `{n, unknown, median, p10, p90, min, max}`
    (linear between ranks; UNKNOWN left out and counted);
  - `beat_benchmark {runs, of, pct, text}`: CAGR above the Shariah BeES buy and hold from the same start (UNKNOWN,
    never 0, when the ETF could not be fetched).
- **Compare.** `--robust-compare`: each side is `parse_settings(text, config.json)`:
  - "default", or KEY=VALUE pairs (commas or spaces): a dotted setting, a setup name (`pullback=off`, on / off =
    true / false), or `regime=off|RULE:ACTION`;
  - every value goes through `tc.validate_config`; any `CONFIG` error, unknown, locked or account key exits 1;
  - `config.json` is never written;
  - `robust_compare{a, b, compare, note}`: `paired()` subtracts A from B per seed (it asserts the same seed and
    start). `compare_summary`: `b_beat_a, b_lost, equal_or_unknown, difference{metric: distribution}, verdict,
    verdict_text, basis`.
  - Verdict (`verdict()`, on CAGR): "B is better in X of N runs" when B beat A on at least 80% of the seeds; "B is
    worse in X of N runs" (X = seeds B lost) when B lost on at least 80% (so B beat A on at most 20%); equal seeds
    count for neither; else "No clear difference: don't change the default on this evidence".
  - With `--robust` too, `robust` is your settings (A's runs reused when A is your config as it is).
- **Output.** The .md gets "## Robustness" / "## Robust compare". The dashboard's `/api/backtest` has `robust`
  (`bt_robust`; in `order` after compare): sides with `metrics[{key, label, median, p10, p90, min, max, text, bar{min,
  lo, mid, hi, max, zero}}]` (0 to 100 % of the track, zero included except for trades), `beat`, `groups[]`,
  `max_positions[]`, and `compare{verdict, verdict_text, line, basis, metrics}` (B minus A). The page only draws
  them (`btRanges`).
- **Rule (PROJECT_BRIEF).** No decision default changes without an 80%+ verdict.

## Holdings import (v0.2.5)

`ticket.py import FILE [--broker zerodha|groww|auto] [--yes] [--map ISIN=SYMBOL]`:

- `tc.read_table`: `.csv` (`read_csv_rows`: UTF-8 / BOM / cp1252; comma, semicolon or tab) or `.xlsx`
  (`read_xlsx_rows`: zipfile + ElementTree, the first sheet via workbook.xml.rels, shared / inline strings,
  numbers; refused over 50 MB unpacked).
- `tc.find_holding_columns`: the first of the first 40 rows with a quantity column and a symbol / instrument /
  trading symbol or ISIN column (`HOLDING_COLUMNS`, exact normalised header names, in order of preference;
  `name`, `avg`, `exchange` optional). Zerodha Console's `Quantity Pledged (Margin|Loan)` are added to
  `Quantity Available` (`QTY_EXTRA`). Not found: refused, with the headers seen. `tc.detect_broker`; a
  mismatch with `--broker` is refused.
- `match_row`: `--map` first, then the ISIN against the halal list (`stocks[*].isin`), then the symbol (a
  `-EQ`/`-BE`/`-BL` suffix dropped; `-SM`/`-ST`/... SME series refused): in the list, or NSE price data found
  (`get_daily_bars`). A symbol whose ISIN disagrees with the list is refused. Never by company name.
- `plan_import` (pure): rows of the same symbol merged (weighted average); shares that are an open journal trade
  are subtracted (`journal_qty`); action add / update / leave; open holdings not in this file -> "mark not in
  latest import"; `alert_preview` gives the status now (overrides applied) and `tc.held_title` for an imported
  holding. `apply_import`: backup `positions.backup-YYYYmmdd-HHMMSS.json`, then holdings `{id: "HOLD-SYM",
  kind: "holding", symbol, qty, avg_price, isin, name, status: open | not_in_latest_import, source:
  "import:<broker>:<date>", imported, last_import, matched_by, journal_qty, product: CNC, halal_at_buy: {status:
  "unknown (imported)", imported: true}}`; `positions.json["unmatched_holdings"]` = the latest file's unmatched
  rows. Kind "holding" entries are the only ones it touches.
- `tc.is_holding` / `tc.trade_positions`: holdings are left out of `size.py` (cash), `check.py` (every limit),
  `alerts.py add --from-positions`, `ticket.py stop` and the `positions` totals, and the dashboard's trade
  tables / totals (`api_tickets` returns them as `holdings`). The tracker and the backtest never read
  positions.json. Held-stock re-check, the daily "already held" skip, news, purify (`estimate`: held since
  `imported`) and the email read every open position, holdings included. `ticket.py close HOLD-SYM` sells a
  holding: P&L against the average price, no R.
- Dashboard: `GET /api/import` (the steps, `trader/import/`, its .csv / .xlsx files, `previewed`).
  `POST /api/run` with `{"import": {"file": NAME, "apply": bool}}` (`actions.import_file`: a plain name matching
  `IMPORT_NAME_RE`, no "..", not a link, realpath inside `trader/import/`); runs `ticket.py import PATH --json
  [--yes]`. `Runner.previewed[name]` = sha1 of the file after a successful Preview; Import is refused (409)
  unless the sha1 matches now, and clears it. The result (`import_result`) is drawn in the run drawer.

## Held-stock halal re-check (v0.2.4)

`halal.py held [--write]` (`held_view()`), run by `tayyib-daily` on every list (before planning; a failure is a
banner, never a stopped list):

- Held = open positions in `positions.json`. Each has `halal_at_buy` {status, ratios, as_of, date, source,
  backfilled}: written by `ticket.py placed`, or backfilled from the list record (not the override) and
  marked `backfilled: true`.
- Screen: an override wins (`halal_overrides.json`), then `KNOWN_EXCLUDED`; otherwise the last screen kept in
  `held_halal.json` (or the list record) when it is younger than `halal.held_recheck_days`, else
  `screen_live()`: `business_screen` + `fetch_fundamentals` + `financial_screen`, the same screen as `build`.
  The universe file is not changed.
- `tc.held_level()`: BLOCK (review / excluded), WARN (compliant, `near_limits` non-empty), UNKNOWN (fetch failed
  or missing data: status "UNKNOWN", the last good screen kept, `last_status` not updated), None.
- Alerts in `alerts.json`: `kind: "halal"`, `key = LEVEL:status`, `status: open|resolved`, `since`,
  `since_price`, and `fired` set at creation, so `alerts.py check` never prices them. Same key: no new alert
  (`alert.new` false). A new key resolves the old one ("superseded"). Compliant and nothing near: resolved.
  Not held any more, or `ticket.py close` of the whole position: resolved; `held_halal.json`'s view drops it.
  `alerts.py clear` keeps open halal alerts.
- BLOCK items carry `wording` (`tc.HELD_WORDING`), `sell_by` (`tc.grace_text`, `halal.exit_grace_days`),
  `sell_ticket` (`tc.sell_ticket`: side SELL, CNC, the held quantity, `guard_order` checked, Kite / Groww steps
  from `BROKER_SELL_STEPS`) and `purify` (`tc.purify_estimate`: dividends since `opened` x the non-compliant
  income ratio, plus max(0, (last close - close on the change date) x qty); a missing part is None, listed in
  `unknown`). `purify.py estimate SYMBOL --since D` prints the same.
- Output: daily `held_alerts[]` and `held_check`; `held_halal.json` {symbols: {screen, last_status,
  last_checked}, view}; the dashboard reads the view (`held_alerts_now()`), the email the day's `held_alerts[]`
  (or the view when there is no list).

`tc.held_title(level, at_buy)` (v0.2.5): "No longer compliant" only when `tc.buy_status_known` (status
compliant, not backfilled, not imported); otherwise a BLOCK is "Not compliant now (status at purchase
unknown)" with `HELD_WORDING_UNKNOWN_BUY`.

## Market regime (v0.2.4, OFF by default)

`regime` {enabled false, index `^NSEI` | `SHARIABEES.NS`, rule `close_below_200dma` | `sma50_below_sma200`,
action `no_new_swing` | `no_new_trades` | `half_risk`}. In the settings hash (a decision once on); the defaults
keep default@2.

- `tc.regime_state(bars, date, rule, index)`: only bars dated <= date; UNKNOWN without a bar on that date or
  under 200 bars. `tc.regime_effect(state, cfg)`: active only when enabled AND risk-off -> `block_modes`,
  `risk_factor`, `text` ("MARKET: Nifty 50 below its 200-day average → no new swing trades").
- Live (`daily.py`): the index bar on the scan's latest bar date; blocked rows are FILTERED with that reason
  and a RISK why item `MARKET`; `half_risk` passes `--risk-pct` x 0.5 to `size.py`. Enabled and UNKNOWN: a
  banner, no effect. `out["regime"]` always (the Today header line, `tc.regime_line`).
- Backtest: `--regime off|RULE:ACTION`, `--regime-compare` (`REGIME_VARIANTS`, the same bars; the index
  fetched once). `regime_states()` walks the index bars forward, so a later bar cannot change an earlier day.
  On a risk-off day the action filters that day's picks or halves `max_risk_per_trade_pct` for sizing and
  the risk check. Columns (`regime_column`): trades, win rate, expectancy, CAGR, max drawdown, worst calendar
  year (part years marked), swing and pullback trades / expectancy, risk-off days, plans held back. Index
  UNKNOWN: a banner, every variant behaves like off. (v0.2.5) `risk_off_ranges()` -> `index.risk_off_ranges`
  {rule: [{start, end, days}]} (trading days), in the `.md` (`ranges_md`) and the Backtest tab (`bt_ranges`,
  collapsible), for a single `--regime` run too. `params` gets `regime` keys only when used, so earlier
  ids are unchanged.

## Why ordering, time-machine label, market closed (v0.2.4)

- `tc.why_tier(item)`: 0 decision, 1 information only (`op` "info", `info`, or "information only" in the note),
  2 UNKNOWN / not available (`ok` None or `op` not_available). `tc.order_why` sorts by tier, then group. The
  `.md` (`why_md`), the email (`why_lines`: mark "i" for info, "check yourself" on UNKNOWN) and the dashboard
  (`why_view` items carry `tier`; the drawer shows decisions by group, then "Information only", then "UNKNOWN:
  check yourself" with the links) use it. `why[]` in the `.json` keeps its group order.
- `tc.tm_label(exp, past, k)`: "+0.81R (1 past trade: too few to judge)".
- `scan.py` records `latest_bar`. `daily.market_closed()`: after 15:30 IST on a configured trading day, bars
  were read and none is dated today -> no list, `daily/closed.json` gets the day, exit 0; `--force` runs. The
  email reads `closed.json`: nothing sent, logged `market_closed`.

## Email (`tayyib-email`, v0.2.3)

`tayyib-email/email_report.py`:
- `test`: a short test email; the exact SMTP error on failure (`describe()`: class, code, server text; a
  535 adds the App Password hint), exit 1.
- `send [--date D] [--dry-run]`: the list of day D (default today). `--dry-run` writes
  `trader/email/D.eml` and `D.html`, sends nothing, needs no password. Hidden flags used by `daily.py --email`:
  `--scheduled` (honours `email.enabled` and `send_when`, and turns a missing password into a logged skip,
  exit 0) and `--run-failed TEXT`.
- `--json` for each.

**Config** (`email`, documented in `DEFAULT_CONFIG_DOCS`): `enabled` (false), `smtp_host`
(smtp.gmail.com), `smtp_port` (enum 465 SSL / 587 STARTTLS, certificate checked with
`ssl.create_default_context()`), `from` (type `email`), `to` (type `emails`, at most `tc.MAX_EMAIL_TO` = 3;
empty means `[from]`), `send_when` (`always` | `picks_only`), `attach_md` (true). `tc.EMAIL_RE` refuses
spaces, CR/LF, commas and angle brackets (no header injection). `email` is in `SETTINGS_EXCLUDE`: it is
not part of the settings snapshot or hash (still default@2). Invalid email values are reported as
"(not shown)" so addresses stay out of daily notes.

**The password** is read only from `TAYYIB_SMTP_PASSWORD` (`email_report.password()`). Any config key that
looks like a secret (`tc.is_secret_key`: words password, passwd, pwd, pass, secret, token, credential, auth,
apikey) is refused with a note that never echoes the value; `config_errors` includes it, so the dashboard
cannot save it and a hand-written one is dropped on the next save. Error texts are scrubbed of the password
and the addresses before they are logged or returned.

**Order of checks in `send`:** `--scheduled` and not enabled → skipped; not a trading day
(`tc.is_trading_day`: weekend or `holidays`) → `market_closed`, nothing sent; `email.to` invalid → refused;
then the email is built; `picks_only` with no pick → skipped; dry run → files; no password → the message
(`PASSWORD_MISSING`, exit 2) or, scheduled, a logged skip; no `from` → refused; send.

**Never invents (`load_daily`):** the list must be `daily/D.json` with `date` D and `asof` on D at or after
15:30 IST. Missing, unreadable, another date, made before the close, or `--run-failed` → kind `failed`,
subject `tayyib: run FAILED / data stale`, the problem stated, no picks, rows, banners or attachment.

**Content (`build()` → `render_text()` / `render_html()`):** subject `tayyib: N picks for D Mon YYYY (PASS a ·
WARN b)` (picks = `top_picks`) or `tayyib: no picks today`; sections in `ORDER`: problem, held but no longer
compliant (open positions in `positions.json` whose `tc.halal_status` is not compliant; red, at the top),
every banner (`banner`, `banners[]`), PASS cards (entry, stop, target, qty, position, loss at stop,
expectancy, past trades, valid until, up to 5 Why lines: what failed or is UNKNOWN first, then setup /
history / plan), the other rows (check and first reason), the tracker (open, waiting, this month's closed
trades, win rate by check from `tracker.json`), notes, the personal-use note, the footer. HTML with a
plain-text alternative, inline CSS only, tables for layout, no images, nothing remote. The daily `.md` is
attached when `attach_md`.

**Log:** `trader/email/log.json` `{entries: [{at, date, command (test | send | dry_run | scheduled), status
(sent | failed | skipped | dry_run | market_closed), recipients (a count), kind, error}]}`, the last 500. No
addresses, no secrets.

**Scheduled run:** `tayyib-daily/daily.py --email [--dir TRADER]` sets `TAYYIB_DIR` (and the working folder
to its parent), skips everything on a non-trading day (logged as market closed), runs itself without
`--email` / `--dir` as a child (so the list is exactly the plain run's) and then `email_report.py send
--scheduled`, adding `--run-failed "exit code N: last stderr line"` when the list failed.

**Windows task (`tools/schedule_windows.py`):** `show` prints the command and changes nothing; `install
--yes` runs `schtasks /Create /TN tayyib-daily /TR "<py.exe> <repo>\tayyib-daily\daily.py --email --dir
<trader>" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 16:20 /F` (16:20 IST converted to the PC's clock, days
shifted if that crosses midnight); `remove --yes` (`/Delete /TN tayyib-daily /F`); `status` (`/Query`).
Without `--yes` it refuses (exit 2). It only ever touches the task named `tayyib-daily`. The PC must be on
and the user logged in.

**`start.bat`** (repo root): checks `py`, sets `TAYYIB_DIR` to `%USERPROFILE%\tayyib-live\trader` when it is
not set (in the code `TAYYIB_DIR` names the trader folder itself), creates it, works from its parent and
starts the dashboard (which opens the browser).

## Rules in code (not configurable)

`tc.guard_order` and `tayyib-risk` enforce:
- CNC only
- BUY to open
- SELL never more than held
- no derivatives
- no margin or MTF
- halal `compliant` only. `review` stocks pass with a WARN only when `halal.allow_review` is true
  *and* `halal.loosen_note` is set; `excluded` and `unknown` are always blocked.
  `halal.require_compliant` is locked to true (any other value is reported and ignored).

No config key can switch any of these off: `validate_config` ignores unknown keys (with a warning
that names the hard rules when a key looks like `allow_intraday`, `product`, `margin`, `fno` and so on),
and `tests/test_v015.py` tries such keys and proves the config, the settings hash and the risk check
are unchanged. A second ticket for an already-placed signal is blocked. No module contains order-placement code, and a
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
| `halal.allow_review` | false | let `review` stocks through with a WARN (loosening: needs `loosen_note`) |
| `halal.method` | tasis | `tasis` or `custom`; reported as `custom` whenever a threshold differs from TASIS |
| `halal.loosen_note` | "" | your source or scholar; required for any threshold looser than TASIS |
| `halal.auto_rebuild_days` | 30 | `daily` rebuilds when older (0 = never) |
| `holidays` | [] | NSE holidays, `YYYY-MM-DD` (used for plan dates) |
| `daily.top` / `daily.picks` | 10 / 3 | stocks planned / PASS stocks highlighted; `--top` / `--picks` override |
| `daily.min_expectancy_r` | null | skip stocks whose time-machine expectancy is lower (null = no filter); skipped rows show `FILTERED` |
| `daily.min_past_trades_for_rank` | 8 (0–50) | rank by expectancy only with this many past trades; the rest by setup score, after them. 0 = the default@1 order |
| `halal.near_limit_pct` | 90 (50–100) | display only: mark a ratio from this % of its limit up to it (`near_limit`); at or over the limit is `over_limit`. Not in the settings hash |
| `scanner.warmup_bars` / `min_history_bars` / `liquidity_days` | 200 / 210 / 20 | bars before any signal / history the scanner needs / days in the turnover average |
| `scanner.setups.<name>` | see below | `{"enabled": true, ...thresholds}` for breakout, pullback, oversold, squeeze, trend |

Setup thresholds (`scanner.setups.<name>.<key>`; the defaults are exactly the values the code used
before v0.1.5, and `tests/test_v015.py` proves the output is unchanged):

| setup | keys (default) |
|---|---|
| all | `enabled` (true), `trigger_buffer_pct` (0.2: trigger 0.2% above the level), `valid_days` (3; trend 5), `min_score` (0) |
| breakout, pullback, squeeze | uptrend: `trend_fast_ma` (50), `trend_slow_ma` (200), `trend_slope_days` (10) |
| breakout | `high_lookback_days` (20), `max_distance_to_high_pct` (3.0), `volume_fast_days` (5), `volume_slow_days` (20), `volume_dry_ratio` (0.9, score bonus only), `invalidation_lookback_days` (5) |
| pullback | `ema_length` (20), `touch_band_pct` (1.0), `max_close_below_ema_pct` (1.5), `rsi_length` (14), `rsi_min` (35), `rsi_max` (58), `invalidation_lookback_days` (3), `invalidation_buffer_pct` (0.2) |
| oversold | `trend_slow_ma` (200), `rsi_length` (14), `rsi_below` (35), `rsi_lookback_days` (4), `require_green_day` (true), `invalidation_lookback_days` (6) |
| squeeze | `recent_days` (10), `prior_days` (30), `max_range_ratio` (0.5), `max_recent_range_pct` (8.0) |
| trend | `fast_ma` (50), `slow_ma` (200), `slope_days` (20), `high_lookback_days` (252), `min_pct_of_high` (85.0), `return_lookback_days` (126), `min_return_pct` (0.0), `invalidation_lookback_days` (20), `ma_buffer_pct` (3.0) |

The score weights (for example breakout's `50 + (3 - distance) x 6 + ...`) and the ATR length (14,
used by the exit plan) stay in the code: they are a ranking formula, not thresholds.

### Validation (`tc.validate_config`)

`load_config()` runs every value in `config.json` through `tc.validate_config(user) -> (cfg, notes)`
against `tc.DEFAULT_CONFIG_DOCS` (`key -> {description, min, max, unit, type, ...}`, one entry per
setting, ready for a settings screen). Ranges include:

| key | range |
|---|---|
| `max_risk_per_trade_pct` | 0.25–3 |
| `max_position_pct` | 5–40 |
| `max_open_positions` | 1–20 |
| `max_portfolio_heat_pct` | 1–15 |
| `min_reward_risk` | 1–5 |
| `modes.swing.max_stop_pct` / `modes.delivery.max_stop_pct` | 2–10 / 3–15 (never wider than before) |
| `min_turnover_rs` | at least 50 lakh (5000000) |

An invalid value (out of range, wrong type) falls back to its default **for that key only** and is
reported as `CONFIG: <key> = <value> invalid (range a–b), using default <d>`. Unknown keys:
`CONFIG: unknown key <key> ignored`. The notes are in `cfg["_notes"]`: `tayyib-daily` puts them in
its notes (`.md` and `--json`), `scan.py` and `halal.py` add `config_notes` to their JSON, and every
script prints them to stderr (never stdout, so `--json` stays clean).

### Halal thresholds: TASIS, stricter, looser

- Defaults are TASIS: debt < 25% of assets, non-compliant income < 3%, cash + receivables < 90%,
  assumed 8% return on short-term investments.
- **Stricter** values (lower limits, higher assumed return) apply freely; `halal.method` is then
  reported as `custom`.
- **Looser** values (debt > 25, income > 3, cash > 90, assumed return < 8, or `allow_review: true`)
  need a non-empty `halal.loosen_note`. Without it each is reported as
  `CONFIG ERROR: halal.<key> = <v> is looser than TASIS ...` and the TASIS value is used.
- With the note, every daily `.md` and `.json` and every `halal.py` output starts with
  `Halal thresholds are looser than TASIS (your setting): <note>`. In JSON it is a first `banner`
  key. `halal.py list` and `check --json` always return `{"banner": null | "<text>", "stocks": [...]}`
  (`banner` is null when nothing is loosened; before v0.1.5 they returned a bare list). The list records `method`, all four `thresholds` and `loosened` when it is built, so the
  banner stays until a rebuild even if the config is reset.
- **AAOIFI** is not offered: it tests debt and interest-bearing deposits against market value, and the
  data we fetch has no share count or market value. We do not approximate it.

### `why[]` on every daily row

Each row of `daily/DATE.json` has `why[]`: items `{group, check, value, limit, op, ok, unit, note}`,
in the group order `HALAL, LIQUIDITY, SETUP, NEWS, PLAN, HISTORY, RISK`. `ok` is true / false, or null
when the input was missing (the value is then null and shown as UNKNOWN, never 0). Each step records
its items when it decides, and `daily` only puts them together:

| group | recorded by | contents |
|---|---|---|
| HALAL | scanner (from the halal list) + risk check | status, your override, the three ratios with reported interest and the assumed-return part, the limits the list was built with, the date of the figures; status again at the risk check. Ratio items carry `near_limit` (from `halal.near_limit_pct`, 90%, of the limit up to it) and `over_limit` (at or over it) |
| LIQUIDITY | scanner (`tc.liquidity_check`) | last price vs `min_price`, average traded value vs `min_turnover_rs` |
| SETUP | `tc.detect` | every condition the setup tested, the measured value and its threshold, the score; two context items with `op: "info"`, `ok: true` (no limit, not conditions): % above the 200-day average and the 126-day return |
| NEWS | risk check | `HALAL-WATCH news` and `results news in the window`: the same `trader/news.json` headlines (Google News India, NSE corporate announcements incl. board-meeting notices, RSS feeds; tagged by news.py, inside its `--hours` window, default 72) that raise the risk check's WARNs. A headline: `ok: false`. None: `ok: true`. `ok: null` / UNKNOWN only when news was not fetched for the stock or its Google News or NSE source failed |
| PLAN | `tc.plan_trade` + risk check | stop % vs cap and method, stop in ATR, target R, time stop, net R:R vs `min_reward_risk`; when the % cap set the stop, a `stop capped` item with `stop_capped: true` and the note "chart invalidation Rs X (Y% away); stop capped at Z%" (the daily row has `stop_capped` too) |
| HISTORY | risk check | time-machine expectancy vs 0, past trades vs `daily.min_past_trades_for_rank` (under it: "information only, ranked by setup score") |
| RISK | risk check + sizing | hard rules, loss at stop, position, cash, open positions, heat, industry, plan expiry, list age, which limit set the quantity, and the final `result` with its first reason |

Rows that were not sized (or `FILTERED`) still have every group; the steps that did not run say so
with `ok: null`. The daily `.md` shows a compact `Why:` block (one line per group) under each top pick.
Scan candidates (`scan.json`), plans (`plan.json`), risk results (`risk.json`) and halal list records
carry their own `why[]` too.

### Settings snapshot

`tc.settings_snapshot(cfg) -> {hash, label, defaults_version, values, differs_from_default[], account_differs[]}`.
`differs_from_default` lists every decision-affecting setting whose value is not the default. Only
three keys are left out: `user_agent` (an HTTP header), `halal.loosen_note` (the banner text; the
looser thresholds it allows are recorded as values, and without it they fall back to TASIS) and
`halal.near_limit_pct` (display only). `halal.list_url` was removed in v0.1.7 (it was never read); a
config that still has it gets `CONFIG: halal.list_url removed: it was never used`. `halal.parent_list_url` (which stocks
are screened) and each `news.feeds.<name>` (which headlines can raise a WARN) are included. `hash` is the first 8 hex characters of the sha1 of the canonical JSON (sorted keys, no
spaces) of `{"defaults_version": DEFAULTS_VERSION, "differs": [[key, value], ...]}`: it depends only on
what you changed, so adding a key whose default keeps the old behaviour does not change it. `label` is
`default@<DEFAULTS_VERSION>` (now `default@4`) when nothing differs, otherwise the hash. **Account facts
(v0.1.8 review):** `capital`, `cash_available`, `broker`, `exchange`, `charges.*` and `brokers.*`
(`tc.ACCOUNT_KEYS`, `tc.is_account_key`) are facts about the user, not strategy: they stay in the hash
(they change quantities and charges, so a re-run with another capital is a different run), but a config
that differs from the defaults only in them is still labelled `default@N`, and they are listed in
`account_differs`. The dashboard says so ("Your own capital ₹2,50,000 and broker groww are kept: they are
not part of the settings label"). Version 2
(v0.1.7) added `daily.min_past_trades_for_rank = 8`, a behaviour change; lists made before it stay
`default@1` in the tracker.

`DEFAULTS_VERSION` (an integer in core) is bumped only when a default value changes behaviour.
`tests/fixtures/defaults_versions.json` records the defaults of each version, and
`test_defaults_version_bumped_when_a_default_changes` fails if a default changes without a bump. After
a bump (or after adding keys), run `python3 tests/baseline.py --defaults`; it refuses to change a
recorded value under the same version.

`daily/DATE.json` has `settings` (with the `--top` / `--picks` actually used), each new tracker row has
`settings_hash` (older rows: `pre-0.1.5`), and `tracker.py report`, `tracker.json` (`summary`,
`settings_split`) and the Excel Summary sheet split the results by label, saying what differed from
the defaults. Rows keep the hash they were recorded with; the split groups them by label
(`tracker.json` `settings{hash: {label, ...}}`), and `cf8b2136`, the default hash of the first v0.1.5
build, counts as `default@1`.

### Risk preview

`tc.risk_preview(cfg, stops_pct, entry)` and `daily.py --risk-preview [--stop-pct 5 ...] [--entry 1000] [--json]`:
the rupee loss per trade, the drawdown after 3, 5 and 10 losses in a row (each loss the risk % of what
is left), and for sample stop distances whether the risk % or the max position % sets the quantity
(they cross at `risk % / max position %`, 5% by default). Before charges. It runs nothing else.

## Dashboard (`tayyib-dashboard`, v0.1.7, settings and run v0.1.8, backtest v0.2.2)

`python3 tayyib-dashboard/dashboard.py [--port 8765] [--no-browser]` serves one page and a JSON API over
the files in `TAYYIB_DIR` (or `./trader`), and opens the browser unless `--no-browser`.

**Server and security:**
- `http.server.ThreadingHTTPServer` bound to **127.0.0.1** only (no option to change it).
- **GET and HEAD, plus exactly two POSTs** (`POST_ROUTES = ("/api/config", "/api/run")`). Every other
  method returns 405 with `Allow: GET, HEAD`; POST to any other path returns 405 too, and GET on a POST
  route returns 405 with `Allow: POST`. GETs never write: they read JSON and fetch price bars with
  `tc.get_daily_bars(..., save=False)` (they read the cache but never write it).
- **Every POST must pass, in this order:** the Host check (403); a known POST path (405); `Origin` equal
  to `http://127.0.0.1:<port>` or `http://localhost:<port>` (403); `X-Tayyib-Token` equal to the
  per-start token (`secrets.token_urlsafe(32)`, compared with `hmac.compare_digest`; 403); `Content-Type:
  application/json` (415); a `Content-Length` (411) of at most 64 KB (413); a JSON object body (400). The
  token is new each time the server starts and is written into the served page
  (`<meta name="tayyib-token">`); it is never sent in a URL, a cookie or a GET API response. A refused
  body is drained so the client gets the error, not a reset connection.
- **Host check** against DNS rebinding: a request whose `Host` header is not `127.0.0.1:<port>` or
  `localhost:<port>` gets 403.
- **No CORS headers.** Responses carry `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a Content-Security-Policy
  (`default-src 'none'`, `connect-src 'self'`, inline script and style only, `form-action 'none'`).
- **Whitelisted files only:** `/` and `/index.html` serve the page; every other path that is not an
  `/api/` route is 404, so there is no path to traverse. Query parameters are validated (`date`
  `YYYY-MM-DD`, `symbol` an NSE code) and never used as a file path.
- A missing file returns `{"missing": "<file>", "hint": "run tayyib-daily"}`. A server error returns
  `{"error": ...}` (500), never a stack trace.

**Python calculates, JavaScript draws:** the server formats every number (`₹1,00,000.00` with en-IN
grouping, signed R, `UNKNOWN` for null), computes statuses and verdicts, and computes the SVG coordinates
of every chart. The page builds DOM nodes with `textContent` (headlines cannot inject HTML) and only
issues same-origin GETs to `/api/...`.

| endpoint | returns |
|---|---|
| `/api/meta` | version, data folder, settings label and header ("Current settings: default@2"), the latest list's `banners[]`, the halal banner, config notes |
| `/api/dates` | the dates of every `daily/DATE.json`, newest first |
| `/api/today?date=` | that day's list (default the newest): rows with `display` strings, `why_view` (groups with ✓ / ✗ / UNKNOWN), `stop_capped`, `near_limit`, `ranked_by`, `expectancy_use`; top picks; `staleness {stale, reasons[]}` (not today's list, or `asof` before 15:30 IST) |
| `/api/tracker` | rows with a labelled `verdict` (TARGET = right, STOP = wrong, NOT TRIGGERED = no trade, TIME EXIT by the sign of R, OPEN / WAITING = pending, BREAKEVEN), `summary` from `tracker.summary()` (the function the Excel Summary sheet uses, so the numbers match), `settings_split`, the equity curve (cumulative R by exit date), and `noise_banner` until 30 closed trades |
| `/api/halal` | every stock with its current status (overrides applied), ratio bars against the limits in config, reported vs assumed-8% income, `near_limit[]`, override note and date, reasons; counts; the loosened-thresholds banner |
| `/api/tickets` | unplaced orders with status, expiry and the Kite and Groww steps from `tc.broker_steps` (the text `ticket.py show` prints); open and closed trades with totals; (v0.2.5) imported `holdings` and `unmatched_holdings` apart |
| `/api/import` | (v0.2.5) the Import holdings section: steps, `trader/import/`, its files and whether each was previewed |
| `/api/settings` | every editable key from `DEFAULT_CONFIG_DOCS` grouped as Risk, Plan, Selection, Broker & charges, Halal, Data & calendar: value, default, range, unit, `changed`, the per-key `CONFIG:` errors; `always_on` (the hard rules, not options); the halal loosened banner; the risk preview; `version` (sha1 of config.json) and the backups |
| `/api/risk-preview?change=` | `tc.risk_preview` for the config with the pending change (`{"set": {key: value}, "reset": [key]}`) applied, plus that change's `diff`, `errors` by key, the new settings label and the loosened banner. Writes nothing |
| `/api/config/backups`, `/api/config/backup-diff?name=` | the backups (newest first), and what restoring one would change |
| `/api/run/status` | `state` (idle / running / ok / failed), start time, elapsed, the last ~200 output lines, the exit code or error, and the before-15:30 `advice` |
| `/api/backtests` | the saved runs in `trader/backtest/` whose file names a backtest writes (`DATE_MODE_DATE_hex6`), newest first by `run_at` (file time for older runs): id, run time, window, mode, settings label, trades, CAGR, max DD and a `label` for the picker. No folder: `{"missing": "backtest", "hint": "run a backtest"}` |
| `/api/backtest?id=` | one run shaped for display, `order` = header, banners, cards, equity, breakdown, compare, trades, universe, footer (the page draws in this order, so the banners always come before any number): `header.items`, `banners[]` (verbatim), `cards` (strategy; Shariah BeES; Nifty 50 with `reference_only` and the label "not halal-screened, reference only"; UNKNOWN with the reason when a benchmark failed), `equity` (SVG coordinates of the three lines on one date axis from the capital, end labels, a drawdown strip with the worst drawdown's peak and trough marks), `breakdown` (overall, by mode, by setup, in- / out-of-sample; `too_few` rows carry "(too few to judge)"), `compare` (columns a, b, c), `trades` (display strings, R signed, `exit_kind`) with `filters`, `universe` (joined late, skipped, the late-joiner line), `footer`. An id must match the pattern and be one of the saved files |
| `/api/chart?bt=ID&n=K` | trade K of a saved backtest on the same chart view as a tracker row (signal, plan levels, fill, exit), from the cached bars the backtest used (else a read-only fetch; else "price data unavailable") |
| `/api/chart?symbol=&from=` | for one tracker row: daily bars around it, as SVG coordinates for the close line, the entry / stop / target lines and the fill / exit markers. Live fetch, else the last cached bars (labelled); else `{"status": "unknown", "message": "price data unavailable"}`. Never a guessed line |

**Labels (v0.1.7 review):** today's response has `made_with` ("This list was made with: default@1") next to
the header's current settings, `older_list` and `rank_note` ("Older list: ranked by expectancy only (made before
the thin-evidence rule)" for lists without `daily.min_past_trades_for_rank`; their rows never say "ranked (n
trades)"), `counts`, `date_long`, and per row `halal_badge` (within / near / over limit, or "compliant by your
override, ratio over limit"), `ladder` (stop / entry / target positions with R multiples) and, for top picks, a
60-day `sparkline` from the price cache (no network). Large money is `₹523.7 cr` / `₹12.5 lakh` (`inr_short`). The
tracker sends `kpis`, `ring` (closed of 30) and `result_counts`; with no closed trades every rate, R and P&L is
"no closed trades", and pending rows say "not yet" / "not closed". The halal response has `donut`, per stock
`over_limit[]` and `not_checked` (business-excluded: ratios "not checked (business excluded)", not UNKNOWN).
Tickets come as `ready` (PASS, then WARN) and `blocked` ("Blocked (not tickets)": BLOCK, expired, changed).
NEWS headlines are shown in full (older lists that stored them cut short are completed from `news.json`).

**Settings (`POST /api/config`, `actions.save_config`):** the body is `{"version", "set": {dotted key: value},
"reset": [dotted key], "loosen_note"?}` or `{"version", "restore": "<backup name>"}`. The base is the valid
part of the current `config.json`; the change is applied, then **`tc.validate_config` is the only judge**
(through `tc.clean_user_config` / `tc.config_errors`): any error refuses the whole save (400, the messages
keyed by setting) and nothing is written. Halal values looser than TASIS need `halal.loosen_note`, or
they are refused. A stale `version` (config.json changed since the page loaded) is 409. On success the
current file is copied to `trader/config_backups/config-YYYYmmdd-HHMMSS.json` (the newest 20 kept), the
new file is written atomically (`tc.write_json`: temp file + `os.replace`) under a lock, and the response
has the new settings label and "Changes apply from the next run." Restoring a backup goes through the same
path. The hard rules are code, not keys: the page lists them as "Always on".

**Reset (v0.1.8 review):** "Reset this section" (each group's `keys`) and "Reset all to defaults"
(`reset_all` from `/api/settings`: every editable key except the account facts; with "Also reset capital
and broker", `account_keys` too) only change the form. They are sent as `{"reset": [...]}` through the same
review, `POST /api/config`, validation, backup and atomic write as any edit, so they can be undone from
Backups. A Halal reset restores TASIS, turns `allow_review` off and clears the source note. A reset that
would leave looser thresholds without the note (resetting only the note) is refused like any other save.

**Wording:** the page never shows internal key names for the source note ("your source / scholar note")
and never the validator's fallback ("using 25"). The server adds `text` (under the field) and `full` (with
the setting's name) to each error, `needs_note` for a halal loosening, and `problems` to a refused save;
the validator's own `message` / `errors` are unchanged (the CLI and daily notes keep them). The key name
stays only in the small code line under each field.

**Test email (v0.2.3):** `POST /api/run` with exactly `{"email_test": true}` runs
`tayyib-email/email_report.py test` (`actions.email_argv()`), nothing else; it is refused with 400
`TAYYIB_SMTP_PASSWORD is not set: ...` before starting when the dashboard's environment has no password, and
it shares the one run slot (409 "a test email" while it runs). `status` gives `message` or the server's
error. `api_settings` adds `email` (`email_status()`: `password_set`, `password_text` "Password: set / not
set", the `setx` line, the last log entry); the value is never read out. The Email group renders the
`email.*` fields (types `email`, `emails`).

**First run (v0.2.3):** `/api/meta` has `first_run` (no `config.json`) and `setup` (`setup_view()`: capital,
broker Zerodha / Groww, risk presets 0.5 / 1 / 1.5 / 2 %, email status, the keys it saves). The page opens a
Welcome drawer that saves `capital, broker, max_risk_per_trade_pct, email.enabled, email.from, email.to`
through `POST /api/config` (validated like any save). No password field.

**Drawdown labels (v0.2.3):** `dd_marks()` gives each marker `label_x`, `label_y`, `anchor`, `y1`, `y2` and
its label `box`: the peak label has the top row, the trough label the bottom row, the lines run between
them, and a label that would pass the right edge is anchored at its end.

**Run (`POST /api/run`, `actions.Runner`):** the body is `{"skip_news": bool}` (→ tayyib-daily `--no-news`)
or (v0.2.2) `{"backtest": {"years": 3 | 5, "mode": "all" | "swing" | "delivery", "compare": bool}}` (→
`tayyib-backtest/backtest.py run --years N --mode M [--compare] --write`, built by `actions.backtest_argv`,
nothing else; `--write` writes only `trader/backtest/` and the price cache). Anything else is 400
(`actions.run_request`). Daily and backtest share the one run slot: a POST while either runs is 409 with
the reason. A backtest is `ok` only for exit code 0 and a new `backtest/*.json` (`backtest_id`); its
`status` adds `kind`, `command`, and `progress` (its last stderr progress line). It starts `tayyib-daily/daily.py` with `sys.executable`, the same `TAYYIB_DIR`, UTF-8 and
unbuffered output, no window on Windows. One run at a time: a second POST while running is 409. A reader
thread keeps the last 200 lines. The state is `ok` only for exit code 0 and a fresh `daily/<today>.json`;
otherwise `failed` with the error text (daily.py writes the list at the end, so a failed run leaves the
previous list). Before 15:30 IST on a weekday, or on a configured holiday, the page asks first ("Prices
aren't final yet, levels may change") and never blocks. When the run ends the Today tab reloads.

**Compliance cross-check:** every today row and every ticket is checked against the **current** universe
plus overrides. A stock that is no longer `compliant` is replaced by `{"halal_changed": true, "message":
"halal status changed since this list: re-check", "halal_now": <status>}` with no levels and no steps.

Tests: `tests/test_v018.py` (each POST rejection reason, no other path or method accepts POST, GETs
write nothing, settings grouping / save / invalid / halal note / stale 409 / 20 backups and restore, the
runner with fake scripts and a real offline run, the tracker re-run cases), `tests/test_v017.py` (every endpoint, 405s, bad Host 403, traversal, 127.0.0.1 bind, missing
files, null to UNKNOWN, the cross-check, tracker numbers equal `tracker.py report`, no write calls) and
`tests/test_safety.py` (no broker API hosts or order code in any `.py` or `.html`; the page has no
`XMLHttpRequest`, no `<form>`; one `fetch`, whose only POSTs go to the two routes).

### Tracker: same-day re-runs (v0.1.8)

The tracker key is `date|symbol|setup|settings_hash`. When `add --from-daily` brings a list whose settings
hash differs from earlier rows of the same date, those earlier rows that never filled become
**SUPERSEDED** (`superseded_by` = the new label): kept for audit, skipped by `update`, excluded from
`summary`, `settings_split`, the Excel Summary and the dashboard stats, and shown greyed ("not counted").
Rows that filled are never touched, and no new row is added for a pick that already has a filled row. A
re-run with the same settings adds nothing. Re-running the earlier settings restores its rows.

### Tracker: repeat listings (v0.1.11)

A stock is counted once while it is waiting or held. `tracker.overlap(store)` runs at the end of `update`
(after the rows are followed, so a fill on the new list's day is known) and as `tracker.py migrate` (no
prices). It walks the rows in list-date order; for each row N not already SUPERSEDED / REPLACED /
ALREADY_HELD, it looks at earlier-dated rows E of the same symbol (any setup, any settings) that are not
in those statuses, judged on N's list date:
- E held then (`filled <= N.date` and not `exited <= N.date`): N becomes **ALREADY_HELD**, `held_from` =
  the latest such E's date;
- otherwise each E still waiting then (not bought by N.date: WAITING, bought later, or NOT TRIGGERED
  with `valid_until >= N.date`) becomes **REPLACED**, `replaced_by` = N.date (`replaced_on` = when);
- E closed by then: N is a normal row.
Both statuses are kept for the record, skipped by `update` and excluded from `summary`, `settings_split`,
`tracker.json`, the Excel Summary and the dashboard Results (greyed, a status chip with a tooltip).
Marked rows are never re-judged, so it is idempotent. A REPLACED row whose replacing listing is gone (that
date's list was re-made without the stock) is restored to WAITING. Symbols with no prices in this run
are left for the next one. `filled()` treats both statuses as not bought, so a same-day re-run under
other settings can still supersede them. Excel: the Settings column shows the label (default@2,
default@1, pre-0.1.5 or the hash), and Win rate / Avg R / Total R / P&L are blank (`pnl_rs` None, not
0) while a group has no closed trades.

## Data endpoints (free, unofficial)

| data | endpoint |
|---|---|
| bars | `query1.finance.yahoo.com/v8/finance/chart/SYM.NS?range=2y&interval=1d` |
| fundamentals | `query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/SYM.NS` |
| universe | `niftyindices.com/IndexConstituent/ind_nifty500list.csv` |
| NSE | `/api/corporate-announcements`, `/api/corporates-pit`, `/api/historical/bulk-deals` and `block-deals` (asked honestly, no cookie warm-up; NSE usually refuses: the checks are then UNKNOWN) |
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
3. Tag `vX.Y.Z` and push the tag. The **Release** workflow (`.github/workflows/release.yml`) runs the
   tests on the tagged code and publishes the GitHub release, with notes from CHANGELOG.md
   (`tools/release_notes.py`: the tag's section plus any untagged versions before it). For a tag that
   already exists, go to **Actions → Release → Run workflow** and enter the tag.
   The **Tests** workflow runs the suite on Python 3.8 and 3.12 on every push.
