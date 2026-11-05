# Changelog

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
