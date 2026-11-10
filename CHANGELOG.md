# Changelog

## v0.2.8 (2026-11-10)

The backtest gets a second option, **My stocks**: the same fixed strategy, run only on stocks you pick, compared
honestly with buying and holding those same stocks. No daily-list changes: settings label still **default@5**.

### Added: My stocks backtest

- **`backtest.py run --symbols SYM1,SYM2,...`** (1 to 20) or **`--holdings`** (the open trades and imported
  holdings in `positions.json`); not both. Without either, the run is exactly as before (same id).
- **One rule, checked before anything starts:** each symbol must match `^[A-Z0-9&-]{1,20}$` and be `compliant`
  on today's halal list (`tc.check_backtest_symbols` / `tc.check_holdings`). A review, excluded, unknown or
  unlisted symbol refuses the run with its name and status ("SUNPHARMA is review on today's halal list (...): only
  compliant stocks can be tested"); duplicates are removed; more than 20 is refused; nothing is dropped quietly.
- **Same simulation:** signals, plans, ranking, risk check, sizing, charges, max open trades, late joiners and
  no look-ahead are unchanged; only the universe is the basket. With every compliant stock chosen the result is the
  "all" run, trade for trade (test). `params.universe_mode` ("all" | "symbols" | "holdings") and `params.symbols`
  are recorded.
- **Buy & hold these stocks:** the capital split equally, each stock bought at the close of its first day in the
  test (a late joiner on its join day, its share waiting as cash), one buy and one sell charge, held to the end;
  total return, CAGR and max drawdown next to the strategy and the Shariah BeES. A stock with no prices is UNKNOWN,
  left out of the basket and named.
- **Your stocks table:** per stock: trades, wins, win rate, total R, P&L, the strategy's return on the stock's
  slice, the holding return, and better / worse / no trades. It adds up to the overall totals; under 30 trades a
  row is "(too few to judge)".
- **Banners first:** "You chose these stocks today, knowing how they did since. Results are likely better than
  reality (hindsight)." always; "Small basket: fewer stocks means fewer trades and more luck." under 10 stocks;
  "Buying and holding these same stocks did better." when it did. The four always-on banners stay.
- `--compare`, `--robust`, `--robust-compare` and `--no-late` work with a basket on the same bars (no new
  downloads). Ids gain `_sym<N>` / `_hold<N>`, and `list` shows "all 183" or "5 stocks: TCS, INFY, ...".

### Dashboard

- **Run backtest** offers: "All halal stocks (what the daily list does)" (the default), "My stocks" (a search
  over the compliant stocks only, chips, at most 20, "Pick at least 10 stocks for a fairer test.") and "Stocks I
  hold" (greyed with the reason when there is nothing held, or a held stock is not compliant).
- The action can add only `--symbols=...` (checked on the server with the same rule before the process starts; a
  bad symbol is HTTP 400 with the reason and starts nothing) or `--holdings`. Arguments are a list, never a shell.
  Still one run at a time, with the token, Origin and Host checks. New read-only `GET /api/backtest/choices`.
- A basket run shows the cards Strategy | Buy & hold these stocks | Shariah BeES, the basket's line on the equity
  chart (the Nifty 50 still dotted, reference only) and the sortable **Your stocks** table above the trades. The
  run picker shows the stocks of each run.

### MCP

- `backtest_run` takes `symbols` or `holdings`, checked the same way before anything starts; it still never
  passes `--write`.

### Docs (and the v0.2.7 review's leftovers)

- User guide: "Test on your own stocks" (how to pick, the hindsight warning in plain words, why at least 10, how to
  read strategy vs holding). FAQ: "Why did buying and holding beat the strategy on my stocks?" Technical guide,
  project brief, AGENTS.md and the skill page.
- FAQ: no more "looser with a note"; compliant = "passed every test"; review = not tradable. README: no mention of
  overrides. Settings: the Pullback switch has one short line like the other strategies; the long note is in the
  FAQ, "Why is pullback on?".
- Tests: `tests/test_v028.py`.

## v0.2.7 (2026-11-07)

Install and run from the docs alone: with or without Claude Code, on Windows, Mac or Linux. Then an owner
decision: **simple settings, and halal can't be changed**. Settings label **default@5**: with the same halal
list every decision equals default@4 (= default@2), proved by a new baseline snapshot.

### Changed: simple settings (owner decision)

- **The Settings page shows only:** Money & risk (capital, risk per trade 0.25–3%, max in one stock 5–40%, max
  open trades 1–20, with the rupee preview), Broker (Zerodha or Groww; the charges come from the built-in tables
  and can't be edited), Strategies (five switches with a line each: Trend (delivery), Breakout, Pullback,
  Oversold, Squeeze (swing); all on; at least one must stay on) and Holidays. Plus a read-only **Halal** card
  (the TASIS limits, "review stocks are blocked", "These rules can't be changed in the app.") and **Always on**.
  Plan, setup thresholds, liquidity, ranking, charges, halal fields, email, regime and data are gone from the page.
  Reset, backups and Review & save work as before for these fields. The Welcome screen asks only capital, broker
  and risk.
- **Fixed in code:** every halal threshold, `halal.method`, `halal.allow_review` (always off),
  `halal.parent_list_url`, every charge rate and broker table, and `user_agent`. A change from the page,
  `config.json`, the CLI or MCP is ignored with `CONFIG: <key> = <v> ignored: it is fixed and can't be changed`
  (the same value as the code is dropped silently). `halal.loosen_note` is removed. The broker `custom` is removed
  (`size.py --broker` too).
- **No halal overrides.** `halal_overrides.json` is never read or written (halal build, daily, risk, dashboard,
  MCP, tracker, backtest); `halal.py override`, `compare --accept-income-reviews` and the dashboard's override
  labels and filter are gone; `halal compare` stays, read-only. An old file gives one note: "halal_overrides.json
  is no longer used (v0.2.7): the automatic TASIS screen decides."
- **Advanced settings** (plan / stop / target / hold, setup thresholds, liquidity, ranking, `email.*`, `regime.*`,
  `news.*`) keep their defaults and stay valid in `config.json` with the same validation. The Settings page says
  "Advanced settings changed in config.json: N (see TECHNICAL.md)" and lists them. Email stays off by default;
  the CLI and the scheduled task still send it.
- **Backtest:** `--max-positions` defaults to `max_open_positions` (6), not 5, and the run records where it came
  from (`params.max_positions_from`).
- Tests: `tests/test_v027.py` `SettingsPage`, `LockedKeys`, `NoOverrides`, `BacktestMaxPositions`, `DefaultsV5`;
  `tests/fixtures/baseline_default5.json.gz`.
- Docs: user guide "Changing your settings", FAQ (the screen is automatic and strict: about 81% agreement with two
  Shariah funds, every difference on the strict side), technical guide, project brief, AGENTS.md, skill pages.

### Fixed (found by installing from scratch with the user guide, on 2026-11-07)

- **The first halal build failed for every new user.** niftyindices.com resets or stalls any request whose user
  agent contains a link, and ours did (`tayyib-trader/0.1 (+https://github.com/...)`). The Nifty 500 download now
  sends `tayyib-trader/<version>`: the same honest name, without the link (`tc.INDEX_HEADERS`). Existing users
  were not affected while their saved copy of the list lasted.
- **The dashboard hid why the first run failed.** It said only "no halal universe yet: run halal.py build first".
  It now shows the build's own message (for example "Could not get the Nifty 500 list ... save it as
  ...\ind_nifty500list.csv"), and the error text is no longer cut at 300 characters.
- **The Welcome screen came back after "Saved ✓".** Saving the suggested values wrote no `config.json` ("Nothing
  changed"), so the dashboard still thought it was the first run. On the first run the save now writes the file.
- A list made at the weekend (or on a holiday in your settings) before 3:30 PM no longer says "before the 3:30 PM
  close: levels can move": that day has no close.

### Added

- **`start.sh`** for Mac and Linux: the same as `start.bat`. It finds `python3` (3.8+), uses
  `~/tayyib-live/trader` unless `TAYYIB_DIR` is set, creates it and opens the dashboard. It runs nothing else.
  Executable in git, LF line endings kept by `.gitattributes`.
- **`tools/smoke_fresh.py`**: a fresh-install smoke test (standard library, offline). It copies the repo to a temp
  folder with an empty temp `TAYYIB_DIR`, runs `--help` on every skill script and `mcp/server.py`, checks the core
  copies, starts the dashboard on a free port and checks the page, `/api/meta` (version, the Welcome condition) and
  that every data tab answers with its "missing" hint, never a 500. The Tests workflow runs it on every push.
- `mcp/server.py --help` and `--version`.
- `tests/test_v027.py`: start.sh's default folder and that it starts only the dashboard (run with a fake
  `python3` on Linux CI), the same for start.bat, and a check that README, the user guide and How it works never
  call an older `default@N` the current default.

### Docs

- README **Start here**: three quick starts side by side: Claude Code, Windows without Claude Code (`start.bat`),
  Mac / Linux (`start.sh`).
- User guide, Option B: the first **Run today's list** also builds the halal list (about 5 minutes more); the ZIP
  unzips to `tayyib-trader-main` (move or rename it so `C:\tayyib-trader\start.bat` exists, with a "you should
  see..." check); the current Python installer wording ("Add python.exe to PATH", the py launcher).
- User guide, Part 2: every "ask Claude" step has its command without Claude Code (journal, stop, alerts,
  positions, purification), checked against each `--help`; where to find the ticket ID; the `TAYYIB_DIR` /
  data-folder rule, once.
- Troubleshooting: the Nifty 500 download refused (save `ind_nifty500list.csv` yourself), a busy port
  (`start.bat --port 8800`), tabs that say "run tayyib-daily", a scheduled task that did not run, "password not
  set".
- Technical guide: a developer quick start (clone, tests, smoke test, `TAYYIB_DIR`, daily, dashboard) with the
  network domains needed; `marketplace.json` in the release checklist.
- Labels: places that still called default@2 the current default now say default@4 (= default@2 in decisions).

## v0.2.6 (2026-11-06)

Pullback is back on by default, and the backtest can now show a range of results instead of one number.

### Changed (a default: default@4, which equals default@2)

- **Pullback is back on by default.** In v0.2.5 we turned it off because its own trades lost money over 5 years
  (46 trades, -0.21R). The whole-strategy backtest showed that this made things worse (5-year CAGR 8.0% -> 4.1%,
  3-year 7.9% -> 7.0%): other trades took its slots and did worse. So it is back on. `DEFAULTS_VERSION` is 4 and
  the label is **default@4**. Every default and every decision is exactly the default@2 one (a new test against
  the default@2 snapshot). default@3 stays a known label for old tracker rows; a config with only pullback off
  shows "same as default@3".
- **From now on, a default only changes with a `--robust-compare` verdict of 80% or more** (see below).
- If you never set pullback yourself, you are on default@4 with no change to your `config.json`, and the next daily
  list shows one banner: "Pullback is back on by default (v0.2.6): removing it made the whole strategy worse in 3-
  and 5-year backtests. You can still switch it off in Settings." If the v0.2.5 banner had not been shown yet, you
  see only the new one. If you set pullback yourself (on or off), nothing changes and there is no banner.
- The Settings note under the switch: "On by default. On its own it lost money in 5-year backtests (-0.21R over
  46 trades), but switching it off made the whole strategy worse (5-year CAGR 8.0% -> 4.1%), because other trades
  took its place."

### Added: the robustness test (tayyib-backtest)

- `backtest.py run --robust [N]` (20 by default, at most 50): the same window N times on the same prices (nothing
  downloaded again). Each seed changes only the order of signals that rank equal and moves the start by one
  trading day, and the result is the same every time for the same seed. Plus the plain run at max positions 3, 5
  and 8. The report gives median, 10th and 90th percentile, min and max of CAGR, expectancy, max drawdown and
  trades, overall and per mode and setup, and how many runs beat the Shariah ETF.
- `--robust-compare "A" "B"`: both settings on the same prices and seeds, compared seed by seed (B minus A). Each
  side is `default` or `KEY=VALUE` pairs over your config (`pullback=off`, `daily.top=8`,
  `regime=close_below_200dma:half_risk`), checked by the same validation as Settings. Verdict on CAGR: "B is
  better in X of N runs" (80%+), "B is worse in X of N runs" (B lost on 80%+), otherwise "No clear difference:
  don't change the default on this evidence".
- The Backtest tab shows a range bar per metric (10th to 90th percentile, median marked, lowest to highest), a
  sentence under each, the verdict line, and the by-mode / by-setup and max-positions tables.
- User guide and FAQ: "Why one backtest number isn't enough", with the pullback story.

### What the robustness test showed (your data, 5 years to 2026-11-06, mode all, 20 seeds)

- **default@4 (= default@2), `--robust 20`:** the plain run is 144 trades, CAGR 8.01%, exactly the v0.2.5 default@2
  run. Across the 20 seeds:

  | | median | 10th pct | 90th pct | min | max |
  |---|---|---|---|---|---|
  | CAGR | 6.21% | 4.49% | 7.58% | 3.44% | 8.56% |
  | expectancy | +0.234R | +0.155R | +0.314R | +0.112R | +0.370R |
  | max drawdown | -15.12% | -22.14% | -12.58% | -22.14% | -12.58% |
  | trades | 154 | 150 | 166 | 150 | 178 |

  CAGR is above the Shariah ETF in 20 of 20 runs (the ETF made 0.82% a year over this window). Swing alone loses
  money in most runs (median expectancy -0.07R); delivery trend carries the result (+0.75R). Max positions 3 / 5 / 8:
  CAGR 3.82% / 8.01% / 7.92%.
- **Pullback on (A) vs off (B):** "No clear difference: don't change the default on this evidence." B beat A in 15 of
  20 seeds (75%). Median B minus A: +0.54 pts CAGR, +0.18R expectancy, 49 fewer trades. Pullback off had a median CAGR
  of 7.24% (the single v0.2.5 run, 4.05%, was below all 20 seeds). The "8.0% -> 4.1%" behind this release was one
  lucky run against one unlucky one. The default stays on, because nothing reached 80% either way.
- **Regime off (A) vs close_below_200dma:half_risk (B):** "No clear difference: don't change the default on this
  evidence." B beat A in 7 of 20 seeds. Median -0.18 pts CAGR. The regime filter stays off.

## v0.2.5 (2026-11-06)

The pullback setup is off by default (an owner decision, from the backtests), your real holdings can be imported
from a Zerodha or Groww file so the halal re-check covers them, and small fixes.

### Changed (a default: default@3)

- **Pullback is off by default.** In the 5-year backtest its own trades lost money: 46 trades, -0.21R each on
  average after charges (3 years: 13 trades, +0.08R). Breakout, oversold, squeeze and delivery trend are
  unchanged. It is still there: Settings, Setups, Pullback (a switch, off, with the note "Off by default since
  v0.2.5: lost money in 5-year backtests (-0.21R over 46 trades). You can switch it on.").
- This is the only decision change. With pullback switched back on, every decision on the test fixtures is
  exactly the default@2 one (a new test, against a default@2 snapshot written with the v0.2.4 code); a default@3
  snapshot was added too. `DEFAULTS_VERSION` is 3 and the settings label is **default@3**. Tracker rows from
  earlier lists keep their default@2 label.
- If your `config.json` left the setups as they were (the old default), you follow the new default, with a
  one-time banner on the next daily list (and so on the dashboard): "Pullback is now off by default (see
  CHANGELOG v0.2.5). Turn it on in Settings if you want it." If it set pullback on explicitly with every other
  setup as default, that key is removed (your config is backed up first). Customised setups are left alone.
- **What the whole strategy did without pullback** (your data, the same windows ending 2026-11-06, all modes):

  | | 3 y default@2 | 3 y default@3 | 5 y default@2 | 5 y default@3 |
  |---|---|---|---|---|
  | trades | 66 | 69 | 144 | 115 |
  | win rate | 48.5% | 43.5% | 41.0% | 33.0% |
  | expectancy | +0.43R | +0.33R | +0.34R | +0.22R |
  | CAGR | 7.90% | 6.96% | 8.01% | 4.05% |
  | max drawdown | -12.41% | -14.80% | -21.11% | -18.02% |
  | swing: trades / expectancy | 30 / +0.11R | 19 / +0.10R | 90 / -0.03R | 38 / -0.23R |

  Leaving pullback out did not improve the strategy as a whole in these runs: other trades took the slots it
  freed. The default follows the owner's decision; the numbers are here so you can judge for yourself.

### Added

- **Import your holdings** (`ticket.py import FILE [--broker zerodha|groww|auto] [--yes] [--map ISIN=SYMBOL]`):
  the Zerodha Console / Kite holdings export and the Groww holdings export, CSV or XLSX (read with the standard
  library: zipfile + xml, first sheet only). Columns are found by their header names (symbol / instrument /
  trading symbol / ISIN, quantity / qty, average price / avg cost); if they are not there it refuses and prints
  the headers it found. Zerodha Console's pledged quantities are added to "Quantity Available".
- Without `--yes` only a preview: per holding the quantity, average price, the matched NSE symbol (by ISIN when
  present), halal status now and the alert level, and add / update / leave. With `--yes`: `positions.json` is
  backed up to `positions.backup-<timestamp>.json`, then holdings are written as kind "holding", source
  "import:<broker>:<date>", status at purchase "unknown (imported)".
- **Holdings are not trades**: no stop, target or tracker row; left out of sizing, the risk check, stop / target
  alerts, `ticket.py positions` totals, the dashboard's trade totals, the tracker and the backtest. They count
  for the held-stock halal re-check, "skip stocks I already hold", purification (and later zakat). Re-importing
  updates quantities; a holding missing from a newer file is marked "not in latest import" (kept); journal
  positions are never changed (shares that are a journal trade are not imported twice). Unmatched rows (not on
  NSE, an unknown ISIN, SME / BSE-only) are listed as "could not match" and kept in `positions.json`, never
  dropped silently and never shown as compliant.
- Dashboard, Tickets: an **Import holdings** section: the steps (menu names may change), the folder
  `trader/import/` and its files, **Preview** and **Import** through the existing run mechanism and token. Only
  a plain file name inside `trader/import/` (no folders, no "..", no links), and Import needs a Preview of the
  same file (same contents). No file upload over HTTP. A Holdings table lists them apart from your trades.
- Backtest: the **risk-off date ranges** (start, end, trading days) per rule in the JSON, the `.md` and the
  Backtest tab (collapsible), to check against a chart.

### Fixed

- A held stock whose status at purchase is not known (backfilled, or imported) that does not pass now says
  **"Not compliant now (status at purchase unknown)"**, not "No longer compliant" (kept only when the status at
  purchase was recorded and compliant).
- The example screenshots with made-up holdings carry a visible "EXAMPLE DATA" label, and their captions say so.
- README: a 6-step "Quick start without Claude Code" next to the Claude Code one; in the User guide "Start
  without Claude Code" is now an equal option in Part 1.

## v0.2.4 (2026-11-06)

A warning when a stock you hold stops being halal, an optional market-regime filter (OFF by default, tested in
the backtest first), and three fixes. With default settings no daily-list decision changes (still default@2;
the baseline is unchanged).

### Added

- **Held-stock halal re-check** (`halal.py held [--write]`, run by every daily list). Open positions are
  screened again with the same screen when their screen is older than `halal.held_recheck_days` (7); the rest
  keeps the 30-day rebuild; overrides win. Compared with the status at buy time (now stored on each position
  when placed; older positions backfilled from the list and marked "backfilled") and the last known status.
  Levels: **No longer compliant** (excluded or review: which test failed, old vs new ratios, data date and
  source), **Near a limit** (WARN) and **Could not verify** (UNKNOWN with the reason; never compliant or
  non-compliant). One alert per symbol per status change, kept open until resolved; resolved when you record
  the sale (`ticket.py close`).
- Shown at the top of the daily `.md` / `.json` (`held_alerts[]`), as a red banner on the dashboard Today tab,
  in a Tickets section, at the top of the email (replacing v0.2.3's simple list) and in `alerts.json`.
- It offers, never acts: a **SELL ticket** for the full quantity (CNC sell of a held position, manual, the Kite
  / Groww steps) and a **purification estimate** (`purify.py estimate SYMBOL --since DATE`: dividends while
  holding x the non-compliant ratio, plus any gain since the change; "estimate: confirm with your scholar").
  `halal.exit_grace_days` (0) changes only the wording.
- **Market-regime filter** (`regime.*`, OFF): index `^NSEI` (or `SHARIABEES.NS`), rule `close_below_200dma` or
  `sma50_below_sma200`, action `no_new_swing`, `no_new_trades` or `half_risk`, applied at the plan / size
  stage with a why[] line "MARKET: Nifty 50 below its 200-day average → no new swing trades". Index data
  missing: UNKNOWN, a banner, no effect. The Today header shows the regime even when the filter is off.
- Backtest: `--regime off|RULE:ACTION` and `--regime-compare` (five variants on the same bars, causal: the
  index's bars up to each day only): trades, win rate, expectancy, CAGR, max drawdown, worst year, swing and
  pullback expectancy. Shown in the Backtest tab. Settings: a Regime group.

### Fixed

- **Why ordering** (email, dashboard, `.md`): decision lines first, then information-only lines (grey, an
  "info" mark, never a red cross), then UNKNOWN lines last with their "check yourself" links.
- **Time machine label**: "+0.81R (1 past trade: too few to judge)" under `daily.min_past_trades_for_rank`.
- **Market closed**: after 3:30 PM IST, when no scanned stock has a bar for today (a holiday missing from your
  settings), no new list, no email, logged "market closed (no bars for today)"; `--force` runs anyway. The
  "stale" email is only for a real failure.

## v0.2.3 (2026-11-06)

Today's halal list by email, from your own computer, every trading day, without running anything. For your
own inbox only. No pick, plan or verdict changes in the daily list (still default@2; the baseline is
unchanged).

### Added

- **tayyib-email** (the 18th skill): `email_report.py test` (a short test email, with the exact SMTP error if
  it fails) and `send [--date D] [--dry-run]`. The email: anything wrong first (a failed run; a stock you
  hold that is no longer compliant, in red), every banner of the list, the top PASS picks as cards (entry,
  stop, target, quantity, position, loss at the stop, time machine, the first lines of Why), the other rows
  with their check, the paper tracker (open trades, this month's results, win rate by PASS / WARN / BLOCK)
  and the footer "Generated on your computer by tayyib-trader vX. You place orders yourself in your broker
  app. Not financial advice, not a fatwa." HTML with a plain-text alternative, inline CSS, nothing loaded
  from the web; the list attached as `.md`.
- Subjects: `tayyib: 3 picks for 6 Nov 2026 (PASS 3 · WARN 2)`, `tayyib: no picks today`, or `tayyib: run
  FAILED / data stale`. A missing, stale (not that day's completed session) or failed list sends the FAILED
  email saying what is missing, never older picks. Weekends and holidays in your settings: nothing sent
  ("market closed"). Every attempt is logged in `trader/email/log.json`, with no addresses and no secrets.
- Settings `email.*`: enabled (off), smtp_host (smtp.gmail.com), smtp_port (465 SSL or 587 STARTTLS),
  from, to (at most 3; empty = yourself), send_when (always / picks_only), attach_md. Not part of the
  settings label.
- **The password is read only from the environment variable `TAYYIB_SMTP_PASSWORD`.** Never stored in
  config.json (any password-like setting is refused), never logged, printed, shown on the dashboard or sent
  to the MCP server. Without it: a clear message ("TAYYIB_SMTP_PASSWORD is not set: see User guide, Get the
  list by email"), `--dry-run` still works, and the scheduled run still makes the list and logs "email
  skipped: password not set".
- `tayyib-daily --email`: the list exactly as without it, then the email; a failed list sends the FAILED
  email.
- `tools/schedule_windows.py show | install --yes | remove --yes | status`: one Windows task, `tayyib-daily`,
  weekdays at 16:20 IST, with the full path to py.exe. `show` changes nothing; install and remove refuse
  without `--yes`.
- `start.bat`: finds Python, uses `%USERPROFILE%\tayyib-live\trader` unless `TAYYIB_DIR` is set, creates it,
  opens the dashboard.
- First-run setup in the dashboard when there is no config.json: capital, broker, risk per trade (presets),
  email address and on / off, saved through the same validated Settings save. No password field: the `setx`
  line instead.
- Settings, **Email**: the fields, "Password: set / not set" (never the value) and **Send test email**
  (through `POST /api/run`, same token and checks, one run at a time; it can only run `email_report.py
  test`).

### Fixed

- Backtest drawdown chart: the "peak" and "trough" labels each have their own row and the marker lines run
  between the rows, so the labels never cross a line or each other, however close the dates; a label at the
  right edge is anchored at its end.

### Personal use only

Sending the list to other people can count as publishing stock recommendations, which in India may need
SEBI Research Analyst registration. Team members should run their own copy. Not financial advice. Not a
fatwa.

## v0.2.2 (2026-11-06)

A Backtest tab in the dashboard, and two engine fixes. No pick, plan or verdict changes in the daily list
(still default@2; the baseline is unchanged).

### Added

- **Backtest tab.** A picker of your saved runs (newest first) and a header (window, capital, risk, max
  positions, settings, WARN taken or not); every banner first, before any number; cards for the strategy
  (CAGR, max drawdown, expectancy, trades, win rate) next to the Shariah BeES and the Nifty 50 ("not
  halal-screened, reference only"); the equity of all three from your capital with a drawdown strip that
  marks the worst drawdown's dates; the breakdown by mode, setup and in- / out-of-sample (groups under 30
  trades greyed and marked "(too few to judge)"); the compare columns; every trade, sortable and filtered
  by setup, mode and exit reason, each with its price chart; the universe (joined late, skipped, the
  late-joiner P&L share). Read-only `GET /api/backtests` and `/api/backtest?id=`.
- **Run backtest** button: years (3 or 5), mode, compare. It goes through the existing `POST /api/run`
  (same token, Origin, Host and one-run-at-a-time rule as "Run today's list") and can only start
  `tayyib-backtest/backtest.py run --years N --mode M [--compare] --write`, which writes only
  `trader/backtest/` and the price cache. Progress shows while it runs; the run list refreshes when it ends.
- `--no-late`: leave out the stocks that joined late (listed during the window).
- `--compare` adds a third column, (c) as run without late joiners (same prices, no new download).
- Every run says "Late joiners: N stocks, contributing X% of total P&L" (JSON `late_joiners`, and the .md).
- Saved runs carry `run_at` and the benchmarks' equity (`benchmarks.*.curve`) for the chart.
- MCP `backtest_run` takes `late`.

### Changed

- **Repeatable by default:** without `--to`, the window ends on the last completed session: today after
  15:30 IST on a trading day, otherwise the previous trading day. A run in market hours no longer uses a
  half-made bar. `params.end_rule` and `window.end_rule` say which.

## v0.2.1 (2026-11-06)

The backtest is closer to what the live pipeline would really have done. Engine only (no dashboard tab yet).

No pick, plan or verdict changes in the daily list (still default@2; the baseline is unchanged).

### Changed

- **The risk check is replayed.** At each close every sized plan goes through the same tayyib-risk check as
  live, against the simulated book (held positions, waiting plans and the plans approved earlier that day):
  portfolio heat, max open positions, 2 per industry, net reward:risk, loss at the stop, max position %,
  cash, halal status, plan expiry and the time-machine WARN. BLOCK is never placed. WARN is placed by
  default, as you can live; `--no-take-warn` places PASS only. `counts.risk_blocked` / `risk_warned` count
  the reasons, and the `.md` shows them.
- News / HALAL-WATCH and the halal list's age cannot be replayed for past dates: they are skipped and
  counted, and a new banner is always shown: "News and HALAL-WATCH checks can't be replayed for past
  dates; live results may differ."
- **Recent listings join when they are ready**: a stock enters on the first day it has 250 bars of history
  (no signals before), listed in `joined_late[]`. Only stocks that never get there are skipped.
- **Sale proceeds pay for fills from the next trading day**, not the same day.
- **Honest labels**: every setup, mode, in-sample and out-of-sample group with fewer than 30 trades has
  `too_few: true` and shows "(too few to judge)". A banner says when the Nifty 50 (not halal-screened,
  price only) beat the strategy: "for reference only, not as a halal option".

### Added

- `--compare`: the same window twice, side by side: (a) as run and (b) ranked by setup score only, to show
  what the time-machine ranking adds. Same bars, no new downloads, deterministic.
- MCP `backtest_run` takes `take_warn` and `compare` (still never `--write`).
- `marketplace.json` carries the version too, checked by the version test.

### Changed (no behaviour change)

- tayyib-risk's `check_order` and `news_why` moved into core (`tc.risk_check_order`, `tc.risk_news_why`) so
  the backtest runs the live check; `check.py` calls them under their old names. Two optional arguments,
  `today` and `replay`, are used only by the backtest; with the defaults the check is the live one.

## v0.2.0 (2026-11-06)

A new 17th skill, **tayyib-backtest**: "if I had run this strategy every day for the last N years across
the halal list with my capital and settings, what happened?" Engine, command line and MCP tools in this
release; a dashboard tab follows in v0.2.1.

No pick, plan or verdict changes (still default@2; the baseline is unchanged).

### Added

- `py tayyib-backtest/backtest.py run [--mode swing|delivery|all] [--setups ...] [--years 3]
  [--from --to] [--capital N] [--max-positions 5] [--split DATE] [--write] [--json]`, plus `list` and
  `show ID`. With `--write` it saves `trader/backtest/<id>.json` and `.md`, and nothing else: never the
  tracker, tickets, positions, daily lists or settings.
- It replays tayyib-daily on every trading day with **the same functions**: setups, liquidity, the exit
  plan, the daily pick and ranking (with the time machine), sizing (1% risk incl. charges, 20% max
  position), the paper tracker's outcome rules (gap through the stop at the open, stop first when both are
  touched, breakeven at +1R, time stop) and Zerodha delivery charges on every buy and sell.
- **No look-ahead**: each day uses only the bars up to that day; fills come later. One cash account, never
  below zero, one position per stock, at most `--max-positions` held or waiting.
- Today's compliant stocks only (your overrides win). Stocks without a year of history before the window
  are listed in `skipped[]` with the reason; missing prices are never filled in.
- Metrics overall, per setup and per mode (trades, win rate, average and expectancy R, profit factor,
  total return, CAGR, max drawdown with its dates, longest losing streak, exposure, charges), in-sample vs
  out-of-sample side by side, and buy-and-hold of **Nippon India ETF Shariah BeES** and the **Nifty 50**
  (UNKNOWN with the reason when they cannot be fetched, never 0).
- **Banners** on every result: today's halal list is applied to the past; survivorship bias (results are
  likely better than reality); past results are no promise. Plus, when they apply: too few trades (under
  30), out-of-sample much weaker (possibly overfit), holding the Shariah ETF did better.
- MCP tools `backtest_run` (saves nothing) and `backtest_list` (20 tools, none place orders).
- Docs: User guide (how to run and read it), FAQ "Can I trust a backtest?", Technical guide.

### Changed (no behaviour change)

- Sizing (`tc.size_trade`), the daily pick (`tc.choose_candidates`) and the time machine (`tc.tm_history`,
  `tc.tm_monte_carlo`, `tc.tm_walk`) moved into core so the backtest uses the live code; the scripts call
  them under their old names. `detect_all` now calls the new `tc.detect_at`. The v0.1.4 baseline test
  passes unchanged.

## v0.1.11 (2026-11-05)

Tracker accounting change: repeat listings of a held or waiting stock are no longer counted twice.

No pick, plan or verdict changes (still default@2; the baseline is unchanged).

### Changed

- **One stock, counted once.** When a later list shows a stock that an earlier tracker row has (any setup):
  - the earlier row still waiting for its buy price becomes **REPLACED** (by the newer list's date), like
    a new ticket replacing one you never placed;
  - if the earlier row already holds it (bought on paper, not exited), the new row is **ALREADY_HELD**;
  - if the earlier row is closed, the new row counts as usual.
  Both are kept for the record, not followed and left out of every summary (tracker.json, the Excel
  Summary, the dashboard Results), and shown greyed with a status chip and a tooltip.
- Existing rows are sorted out on the next run (or `tracker.py migrate`), in list-date order; running it
  again changes nothing.
- Excel: the **Settings** column shows the label (default@2, default@1, pre-0.1.5, or the code for your
  own settings) instead of the hash. **P&L, win rate and average R are blank, not 0,** while a group has
  no closed trades. The "Read me" sheet explains the new statuses.

## v0.1.10 (2026-11-05)

Clearer NEWS: what was checked, and what you need to check yourself. Display only: no decision changes
(still default@2; the baseline is unchanged).

### Changed

- **NEWS is two lines** in Why?, on the cards, on the tickets and in the daily `.md`:
  - **Media news** (Google News and the RSS feeds): ✓ none flagged, ✗ flagged (with the headline), or
    UNKNOWN when Google News failed for the stock or no media source answered.
  - **Exchange filings (NSE)**: ✓ none flagged, ✗ flagged, or, when NSE refuses automated access (most
    days), **Not available: NSE blocks automated access → check yourself**, with a neutral "–" mark
    (never a ✓), the NSE company page link and Copy ISIN next to it.
- UNKNOWN now means a real failure of a source that normally answers (a timeout, a server error), not
  NSE's usual refusal.

### Added

- FAQ: "Why does Exchange filings say Not available?".

## v0.1.9 (2026-11-05)

Honest requests, and clear about what it could not check. No decision changes (still default@2).

### Changed

- **No browser imitation.** Requests to NSE now say who they are (`tayyib-trader/0.1.9` with a link to
  this project): no browser user agent, no browser headers, no homepage cookie visit. NSE usually refuses
  automated requests; when it does, the NEWS checks are UNKNOWN, as before. After the first refusal in a
  run the tool stops asking NSE (one polite attempt per run).
- **Clearer banner:** "Exchange filings unavailable today (NSE refused automated access). HALAL-WATCH and
  results checks are incomplete for 10 of 10 stocks: check the announcements yourself for any stock you
  plan to buy."
- **Why? names its sources:** the NEWS lines say which sources answered (Google News, NSE announcements,
  the RSS feeds) and which failed and why.

### Added

- **Check announcements yourself** links: on every top-pick card, every ticket card, in the Why panel's
  NEWS section and under each top pick in the daily `.md`. The stock's NSE company page, and BSE: its page
  when the scrip code is known, otherwise BSE's search with the ISIN to type in. They open in a new tab;
  the tool never reads them.
- **Copy ISIN** button next to the BSE search link ("Copied ✓"), on the cards, the tickets and the Why panel.
- **Nifty 500 list without a browser disguise:** niftyindices.com now gets the honest user agent too. Every
  good download is kept in `trader/cache/`. If the download is refused, the halal build uses that copy
  (and says how old it is: build notes, daily notes, the dashboard's Halal tab), then an
  `ind_nifty500list.csv` you saved in your data folder, and otherwise stops and tells you how to download
  it. It never builds from a partial or made-up list, and your existing halal list is kept.
- FAQ: "Why do news checks often say UNKNOWN?". TECHNICAL: an audit of every request and its headers.

## v0.1.8 (2026-11-05)

Change your settings and run today's list from the dashboard, safely.

### Added

- **Settings tab** (the fifth tab, sliders icon). Every setting you can change, grouped as Risk, Plan,
  Selection, Broker & charges, Halal (and Data & calendar), each with its default, allowed range and unit.
  Sliders with number boxes, on / off switches for each setup, a "changed" marker with Reset, and errors
  next to the field as you type.
  - **What this means in rupees:** the loss per trade, the drawdown after 3, 5 and 10 losses in a row and
    which limit sets the quantity, updated as you change a value. Above 2% a trade it warns you.
  - **Review & save** shows every change (old → new) and the new settings label first. The server checks
    everything with the same validator the skills use; anything invalid is refused with its message and
    nothing is partly saved. "Changes apply from the next run."
  - **Backups:** each save keeps your old `config.json` in `trader/config_backups/` (the last 20). Restore
    one from the Backups section, after seeing what it changes.
  - **Halal:** stricter values save freely. Looser than TASIS needs a "Source / scholar" note, shows the
    loosened banner in the preview, and is refused without it.
  - The hard rules (CNC only, BUY to open, cash equities only, your yes for every order, compliant stocks
    only) are listed under **Always on**: they are not settings.
- **Run today's list** button on the Today tab. Runs `tayyib-daily` on your computer with the same data
  folder, with a "Skip news" option and live output. One run at a time. Before 3:30 PM IST on a weekday,
  or on a holiday in your settings, it asks first ("Prices aren't final yet, levels may change"). When it
  ends the Today tab reloads; a failure shows the error and keeps the old list.
- The risk preview in `daily.py --risk-preview` also prints the warning above 2%.
- **Back to the defaults:** Reset per field, **Reset this section** per group, and **Reset all to
  defaults** at the top, which keeps your capital and broker unless you tick "Also reset capital and
  broker". A Halal reset restores TASIS, turns review off and clears your source / scholar note. A reset
  only changes the form: it goes through the same review, confirmation, validation and backup as any
  edit, so it can be undone from Backups.

### Changed

- **Settings label:** your own capital, cash and broker (with its charges) no longer make the label a
  hash: with nothing else changed it stays `default@2`, and the dashboard says they were kept. They still
  count in the stored hash.
- **Plain words on the Settings page:** no internal key names ("your source / scholar note", not
  `halal.loosen_note`), and a looser halal value says "Add your source / scholar note below to save this,
  or reset to 25%." The CLI and daily-list notes keep their wording.

- **Tracker: same-day re-runs.** Running the list again on the same day with different settings no longer
  loses the new picks. The earlier unfilled rows become **SUPERSEDED** (kept for audit, greyed in Results,
  not counted in any summary, the Excel Summary or the dashboard stats) and the new rows are added. Filled
  rows are never touched. The same settings twice adds nothing. The Excel sheet has a "Superseded by"
  column.
- The dashboard is no longer GET-only: it has exactly two write endpoints, `POST /api/config` and
  `POST /api/run`. Each needs the right Host and Origin, a secret token that is new at every start, a JSON
  body and at most 64 KB. Nothing in it places, changes or cancels an order.
- The header says "Current settings: default@2" and "change them in the Settings tab". Large rupee amounts
  read `₹1,000 cr`.

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
  - **Halal:** a donut of compliant / review / excluded / unknown, search and filters (compliant
    first), each ratio as a small gauge against its limit (within / near / over, always in words), your
    overrides. Stocks the business screen excluded show "not checked (business excluded)", not UNKNOWN.
  - **Tickets:** PASS and WARN tickets first, with Copy buttons ("Copied ✓") for the Kite and Groww
    steps; blocked ones collapsed under "Blocked (not tickets)"; your positions.
  - Designed as a product, not an admin page: a calm teal and warm off-white palette with a designed dark
    mode, a serif for headings, KPI tiles, price ladders (stop, buy above and target with their R
    multiples), 60-day sparklines, a Why? drawer (a bottom sheet on a phone), a bottom tab bar on a phone,
    skeleton loading and empty states that say what to run. No sideways scrolling from 375px up.
  - Labels say what is true: "no closed trades" instead of ₹0.00, "Triggered (paper)" instead of
    "Bought", "Current settings: default@2" next to "This list was made with: default@1", and lists made
    before v0.1.7 say "Older list: ranked by expectancy only". Large money reads ₹523.7 cr.
  - Switching tabs (click, keyboard, link or back / forward) always starts at the top of the page.
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
  - **HALAL near / over limit:** a ratio from `halal.near_limit_pct` (new, default 90) of its limit up to
    the limit is flagged `near_limit`; at or over the limit it is `over_limit` (a separate flag and label,
    never "near"). The halal list records `near_limit[]` and `over_limit[]` per stock.
  - **NEWS:** headlines are kept in full in why[] (they were cut at 70 / 90 characters). The risk
    reasons are unchanged.
- The past-trades check in HISTORY uses the new setting instead of a fixed 8.
- Day and session counts are pluralised everywhere ("1 day ago", "1 session"), via `tc.plural`.
- The Kite / Groww steps moved into the core (`tc.broker_steps`), so `ticket.py` and the dashboard show the
  same text.
- **Fix: a ticket could keep an earlier day's signal.** The exit planner preferred a `tayyib-entry`
  record (`entries.json`) over today's scan even when that record was only WAITING and the scan had a
  newer signal for the same setup. On the 2026-11-05 list this kept WELSPUNLIV on the 2026-11-04 signal
  (ticket `WELSPUNLIV-2026-11-04-trend`, trigger ₹268.00, valid until 2026-11-11) instead of planning
  from 2026-11-05. A newer scan signal now wins; an entry record still wins once the setup has
  TRIGGERED (the plan then starts from that fill), or when the scan has nothing newer. This only
  happened when `tayyib-entry` had been run on an earlier day; the baseline is unaffected.

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
