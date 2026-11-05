# Changelog

## v0.1.7 (2026-11-05)

Fixes from the live check of the pipeline, and a read-only dashboard.

### Added

- **New skill `tayyib-dashboard`: your dashboard in the browser.** Ask "show my dashboard" (or run
  `py tayyib-dashboard/dashboard.py`) and it opens `http://127.0.0.1:8765/` with four tabs:
  - **Today:** banners and staleness, top-pick cards, the full table (sort, filter by check and mode), and
    a **Why?** panel per row with ✓ / ✗ / UNKNOWN for every check. Capped stops and near-limit halal ratios
    are marked.
  - **Results:** every tracked pick with a labelled verdict (TARGET = right, STOP = wrong, NOT TRIGGERED =
    no trade), a price chart with the entry, stop and target, the summary by check, mode, setup and
    settings label (the same numbers as the Excel Summary), and the equity curve. Until 30 trades have
    closed it says "still noise: don't judge yet".
  - **Halal:** search, status filter, ratio bars against the limits, your overrides.
  - **Tickets:** unplaced tickets with Copy buttons for the Kite and Groww steps, and your positions.
- It is **read-only**: it runs on 127.0.0.1 only and answers GET only. It checks the Host header, sends
  no CORS headers, serves a fixed list of files and writes nothing. It cannot place, change or cancel an
  order. Every row and ticket is re-checked against the current halal list: a stock that is no longer
  compliant shows "halal status changed since this list: re-check" and no prices. Works offline, light
  and dark, and status is never shown by colour alone.
- Design system made with UI/UX Pro Max at development time: `design-system/tayyib/MASTER.md`.

### Behaviour change: ranking (default@1 → default@2)

- **Ranking on thin evidence.** A time-machine expectancy from one or two past trades no longer decides
  the order. Inside each PASS / WARN / BLOCK group, stocks with at least `daily.min_past_trades_for_rank`
  (new, default **8**) past trades of their setup come first, best expectancy first; the rest follow by
  setup score. The same order sets which tickets are sized first, so it also decides which ones your
  position, cash and total-risk limits block, and which are the top picks. The expectancy is still shown,
  labelled "information only (n trades)".
- On the 2026-11-05 live list, the top picks change from LAURUSLABS, ETERNAL, WELSPUNLIV to SAILIFE,
  ETERNAL, SHYAMMETL. LAURUSLABS (+2.47R from 2 past trades) is now sized after two other healthcare
  stocks and is BLOCKed by the 2-per-industry limit.
- `DEFAULTS_VERSION` is now 2, so lists made with the defaults are labelled `default@2`. Earlier lists keep
  `default@1` in the tracker, so the two can be compared.
- Set `daily.min_past_trades_for_rank` to 0 for the old order. A test proves that with 0 every decision is
  the same as v0.1.4.

### Changed

- **News source-failure banner.** When NSE announcements or Google News fail for any of today's stocks,
  the daily list (`.md` and `banners[]` in the `.json`) starts with one line, for example "NSE announcements
  unavailable today: HALAL-WATCH and results checks are incomplete for 10 of 10 stocks." Each row's NEWS
  reasons stay UNKNOWN. No verdict changes (tested).
- **More in why[]** (display only, no decision changes, tested):
  - **PLAN:** when the % cap set the stop, "chart invalidation Rs X (Y% away); stop capped at Z%"
    (`stop_capped: true`, also on the daily row).
  - **SETUP context:** % above the 200-day average and the 126-day return (information, not conditions).
  - **HALAL near limit:** a ratio at or above `halal.near_limit_pct` (new, default 90) of its limit is
    flagged `near_limit`, and the halal list records `near_limit[]` per stock.
- The past-trades check in HISTORY uses the new setting instead of a fixed 8.
- The Kite / Groww steps moved into the core (`tc.broker_steps`), so `ticket.py` and the dashboard show the
  same text.

### Removed

- **`halal.list_url`.** It was documented but never used. If your config still has it you will see
  `CONFIG: halal.list_url removed: it was never used`; nothing else changes. Any future import of an
  official Shariah list may only compare with the screen or make it stricter, never mark a stock compliant.

## v0.1.6 (2026-11-05)

- **Fix: crash/garbled text on Windows when output contains ₹ (cp1252); all scripts now print and read
  UTF-8.** On Windows, output sent to a pipe or a file is cp1252, which has no ₹. A news headline with
  a ₹ sign made the risk check crash (`UnicodeEncodeError`) and so stopped the daily list, and
  tayyib-daily and the MCP server read the scripts' output as cp1252, so ₹ came out as "â‚¹". The bug
  existed since v0.1.4. Every script now prints UTF-8, tayyib-daily and the MCP server read it as UTF-8,
  and a test forces cp1252 on every OS. No decision changes: the v0.1.4 baseline still matches.

## v0.1.5 (2026-11-05)

Groundwork for the dashboard. With the default settings every decision is identical to v0.1.4: same
stocks, setups, entries, stops, targets, quantities and verdicts. A baseline captured before the
change (2,986 signals across all fixtures, plus five full daily runs) proves it.

- **Thresholds in config.** Every setup threshold (distances to highs and averages, RSI levels, range
  widths, moving-average lengths, lookbacks, minimum scores) is now `scanner.setups.<name>`, each with
  `enabled`. There are also `scanner.liquidity_days`, `daily.top`, `daily.picks` (the `--top` /
  `--picks` flags still win) and `daily.min_expectancy_r` (default off; skipped rows show `FILTERED`).
- **Validated settings.** Every value is checked against `DEFAULT_CONFIG_DOCS` (a description, range
  and unit for each, ready for a settings screen). An invalid value falls back to its default for that
  key only and is reported: `CONFIG: <key> = <value> invalid (range a–b), using default <d>`. Unknown
  keys are reported and ignored. No key can enable intraday, F&O, shorting, margin or non-compliant
  stocks (see Safety fixes below).
- **Halal loosening policy.** Stricter than TASIS: allowed. Looser (debt > 25%, income > 3%, cash +
  receivables > 90%, assumed return < 8%, or `allow_review`) needs `halal.loosen_note` (your scholar or
  source), or the tool reports an error and keeps TASIS. With the note, every daily list and halal list
  output starts with "Halal thresholds are looser than TASIS (your setting): <note>". There is no
  AAOIFI preset: it needs market value, which our data cannot give.
- **Why this stock.** Every daily row has `why[]` (HALAL, LIQUIDITY, SETUP, NEWS, PLAN, HISTORY, RISK),
  with each check's value and limit as recorded when it was decided. Missing input is UNKNOWN, never 0.
  The daily `.md` shows a compact **Why:** block under each top pick. See the [FAQ](docs/FAQ.md).
- **Settings snapshot.** The daily `.json` records `settings`: what differs from the defaults and a
  hash of only those differences plus `DEFAULTS_VERSION` (1). With no changes the label is
  `default@1`. Adding a new key with a behaviour-preserving default leaves the hash alone; a test fails
  if a default changes without bumping `DEFAULTS_VERSION`. Each tracker row records its
  `settings_hash` (older rows: `pre-0.1.5`), and the tracker report, `tracker.json` and the Excel
  Summary sheet split results by label.
- **NEWS in why[].** The NEWS items use the same headlines that raise the risk check's HALAL-WATCH and
  "results news in the window" WARNs (Google News, NSE announcements, RSS); UNKNOWN only when the news
  step did not run for the stock or one of its sources failed. No new data source.
- **Risk preview.** `daily.py --risk-preview` shows the loss per trade, the drawdown after 3, 5 and 10
  losses in a row, and whether risk % or max position % sets the quantity for sample stops.
- **Breaking for `--json` readers:** `halal.py list` and `halal.py check --json` (and the MCP tools
  `halal_list` and `halal_check`) now always return `{"banner": null | "<text>", "stocks": [...]}`
  instead of a bare list. `banner` is null unless the halal thresholds are looser than TASIS. Read
  `stocks`.
- Docs: "Changing your settings" in the [User guide](docs/USER_GUIDE.md), new FAQ answers, and the
  Technical guide, AGENTS.md and the project brief updated. 162 tests (47 new).

### Safety fixes

- **`halal.require_compliant` is locked to true.** In v0.1.4, `require_compliant: false` let stocks
  with an `unknown` halal status through the risk check. The risk check now always blocks any stock
  that is not compliant (`review` passes only with `allow_review` and a `loosen_note`). A v0.1.4 config
  with `require_compliant: false` is now ignored, with the note
  `CONFIG: halal.require_compliant = false ignored: it is a hard rule and stays true`.
- **The exit planner no longer plans excluded or unknown stocks when `allow_review` is on.** In
  v0.1.4, `allow_review` opened the exit planner to every non-compliant status, not just `review`.
  Now only compliant stocks are planned, plus `review` stocks when `allow_review` is on.

## v0.1.4 (2026-11-04)

- New skill `tayyib-tracker`: a paper record in **Excel**. Every stock each daily list shows (PASS,
  WARN and BLOCK) is followed on the real prices with the plan's own rules: did it reach the buy
  price, then the target or the stop first? Result in R and rupees after charges. Writes
  `trader/tracker.xlsx` (Tracker, Summary and Read me sheets; standard library only) and `tracker.csv`.
- The daily list records itself in the tracker, follows earlier rows and shows "How earlier lists
  did" at the bottom (`--no-track` to skip).
- MCP tool `tracker_report` (18 tools, none place orders). Docs updated.

## v0.1.3 (2026-11-04)

- Daily list builds the halal list on the first run and rebuilds it automatically when it is 30 days
  old (`halal.auto_rebuild_days`; `--no-rebuild` to skip).
- Daily list shows **today's top picks**: the best 3 PASS stocks with buy, stop, target and shares (`--picks N`).
- Docs rewritten: a short README, plus a [User guide](docs/USER_GUIDE.md) (non-technical, step by step,
  including running it automatically with Windows Task Scheduler), [How it works](docs/HOW_IT_WORKS.md),
  a [FAQ](docs/FAQ.md) (halal criteria, data sources, PASS/WARN/BLOCK, R, privacy) and a
  [Technical guide](docs/TECHNICAL.md). The old GETTING_STARTED guide is folded into the User guide.

## v0.1.2 (2026-11-04)

- Packaging only: the plugin version is bumped so `claude plugin update` delivers the v0.1.1 risk and
  daily-list fixes to anyone who installed 0.1.1 before they landed (`check.py`, `daily.py`,
  `size.py` and the daily SKILL.md). No behaviour change from the v0.1.1 tag.
- A test now fails if `plugin.json`, the core VERSION, the MCP server version and the top CHANGELOG
  entry disagree, so a release can't ship without a version bump.

## v0.1.1 (2026-11-04)

- New skill `tayyib-daily`: one command for today's halal trade list. It runs scan, news, plan, time
  machine, sizing and the risk check for the best candidates (only today's stocks; earlier plans and
  placed orders are left alone) and prints one table with entry, stop, stop %, target, quantity, rupee
  risk, verdict and PASS / WARN / BLOCK, with every reason (HALAL-WATCH first). Saved to
  `trader/daily/DATE.md`. Warns when run during market hours or when the halal list is due a rebuild.
- The daily list's PASS / WARN / BLOCK always matches a plain `tayyib-risk` run: it risk-checks the
  whole orders file (open positions and placed orders count), sizing best expectancy first. Today's
  tickets replace earlier unplaced ones and it says which; placed orders are never touched.
- `--mode all` alternates the best swing and delivery ideas instead of showing only delivery.
- Budget: a new ticket never reuses a placed order's id (adds -2, -3); it says when it replaces an
  earlier unplaced ticket for the same stock.
- Risk: a negative time-machine expectancy is a WARN. A second ticket for a signal that is already
  placed is a BLOCK. `check.py SYMBOL` now counts every other ticket toward the limits and only
  reports and saves the ones asked for.
- Daily list skips stocks you already hold or have placed (it says so); its notes say which tickets
  were removed and which were replaced; each reason is labelled BLOCK or WARN.
- MCP tool `daily` (17 tools, still none that place orders).
- Plugin version 0.1.1, so `claude plugin update` picks this up.

## v0.1.0 (2026-11-04)

First release. 13 skills for halal swing and delivery trading on NSE/BSE, an MCP server, and
91 offline tests. Validated on live data (Windows, Python 3.13) over several runs.

**Halal screen**
- Business screen (finance, alcohol, tobacco, gambling; plural names; NSE placeholder rows dropped)
  plus TASIS-style ratios: debt < 25% of assets, non-compliant income < 3%, cash + receivables < 90%.
- The income test shows reported interest and the assumed 8% return on short-term investments side
  by side; total income = revenue + interest + other income, as Indian annual reports define it.
- `compare` against a trusted Shariah list; `--accept-income-reviews` for income-only cases; user
  overrides kept across rebuilds; build summary shows counts before and after overrides.
- Live check vs Nippon Shariah BeES + Tata Ethical holdings (Sep 2026): the automatic screen agreed on
  81.0% of stocks, all differences on the strict side (we block, the funds allow); no stock we mark
  compliant is non-compliant on those lists. After checking 8 of the differences against their FY26
  annual reports and recording them as user overrides, agreement is 94.8%.

**Trading**
- Swing (breakout, pullback, oversold, squeeze) and delivery (trend) setups with liquidity filters.
- Stops capped at 10% (swing) and 15% (delivery), configurable; caps are strict.
- Time machine: 10,000 simulated futures + historical replay in R after charges; verdict warns when
  a loss is the most likely single outcome.
- Indian delivery charges match Zerodha's published rates to the paisa (GST on IPFT included).
- Hard rules in code: CNC only, no short selling, no F&O, no margin; no order is ever placed.

**Data**
- Yahoo (.NS), NSE announcements / PIT / bulk-block deals (reported UNKNOWN, never zero, when NSE
  blocks), Google News India, Moneycontrol, ET Markets, Livemint. News tags from headlines only,
  pick-lists recognised, near-repeats merged only with identical numbers within 12h.

**Works with**
- Claude Code (plugin or copied skill folders), any MCP client (`mcp/server.py`, 16 tools, none
  place orders), any agent via AGENTS.md. Windows: `py` fallback documented in every skill.
