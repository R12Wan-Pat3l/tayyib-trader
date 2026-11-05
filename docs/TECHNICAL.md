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
| Any MCP client | `python3 mcp/server.py` over stdio. 18 tools, none of which place orders. Config below |
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
| halal | `tayyib-halal/halal.py build \| check \| list \| compare \| override` | Nifty 500 CSV, Yahoo fundamentals | `halal_universe.json`, `halal_overrides.json` |
| scan | `tayyib-scanner/scan.py --mode swing\|delivery\|all` | universe, Yahoo daily bars | `scan.json` |
| news | `tayyib-news/news.py --symbols A,B` | RSS, Google News, NSE | `news.json` |
| entry | `tayyib-entry/entry.py check SYM [--mode]` | scan, bars | `entries.json` (the exit planner uses a record only once TRIGGERED, or when the scan has no newer signal) |
| exit | `tayyib-exit/exit.py plan SYM [--setup] [--mode] --write` | scan/entries | `plan.json` |
| time machine | `tayyib-timemachine/timemachine.py run [SYMS] --write` | plans, bars | `sim.json` |
| size | `tayyib-budget/size.py [SYMS] --write` | plans, positions | `orders.json` |
| risk | `tayyib-risk/check.py [SYMS]` | orders, positions, universe, news, sim | statuses in `orders.json`, `risk.json` |
| ticket / journal | `tayyib-broker/ticket.py show \| placed \| stop \| close \| positions` | orders | `positions.json` |
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
  `banners[]` (`.json`) and at the top of the `.md`: "NSE announcements unavailable today: HALAL-WATCH and
  results checks are incomplete for N of M stocks." Per row, the NEWS `why[]` items stay UNKNOWN. No
  verdict changes.
- It then risk-checks the whole orders file, so its statuses always match a plain `check.py`.
- Earlier unplaced tickets are removed, and it reports which ones. Placed orders are never touched.
- Finally it records the list in the tracker, follows every unfinished earlier row (`tc.trade_outcome`)
  and writes the Excel file. Use `--no-track` to skip this. The `.xlsx` file is written with the standard
  library (zipfile plus SpreadsheetML), with 3 sheets: Tracker, Summary and Read me.

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
`default@<DEFAULTS_VERSION>` (now `default@2`) when nothing differs, otherwise the hash. **Account facts
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

## Dashboard (`tayyib-dashboard`, v0.1.7, settings and run v0.1.8)

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
| `/api/tickets` | unplaced orders with status, expiry and the Kite and Groww steps from `tc.broker_steps` (the text `ticket.py show` prints); open and closed positions with totals |
| `/api/settings` | every editable key from `DEFAULT_CONFIG_DOCS` grouped as Risk, Plan, Selection, Broker & charges, Halal, Data & calendar: value, default, range, unit, `changed`, the per-key `CONFIG:` errors; `always_on` (the hard rules, not options); the halal loosened banner; the risk preview; `version` (sha1 of config.json) and the backups |
| `/api/risk-preview?change=` | `tc.risk_preview` for the config with the pending change (`{"set": {key: value}, "reset": [key]}`) applied, plus that change's `diff`, `errors` by key, the new settings label and the loosened banner. Writes nothing |
| `/api/config/backups`, `/api/config/backup-diff?name=` | the backups (newest first), and what restoring one would change |
| `/api/run/status` | `state` (idle / running / ok / failed), start time, elapsed, the last ~200 output lines, the exit code or error, and the before-15:30 `advice` |
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

**Run (`POST /api/run`, `actions.Runner`):** the only option is `{"skip_news": bool}` (→ `--no-news`); any
other key is 400. It starts `tayyib-daily/daily.py` with `sys.executable`, the same `TAYYIB_DIR`, UTF-8 and
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
3. Tag `vX.Y.Z` and push the tag. The **Release** workflow (`.github/workflows/release.yml`) runs the
   tests on the tagged code and publishes the GitHub release, with notes from CHANGELOG.md
   (`tools/release_notes.py`: the tag's section plus any untagged versions before it). For a tag that
   already exists, go to **Actions → Release → Run workflow** and enter the tag.
   The **Tests** workflow runs the suite on Python 3.8 and 3.12 on every push.
