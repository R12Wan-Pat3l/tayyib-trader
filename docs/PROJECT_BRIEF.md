# tayyib-trader: project brief

Context for any new chat or AI session working on this project (for example a UI). Read this first,
then [TECHNICAL.md](TECHNICAL.md) for details. Last updated: 2026-11-10 (v0.2.9).

## What it is

A free, open-source (MIT) tool that gives a **daily list of halal (Shariah-screened) NSE stocks**
with entry, stop-loss, target, quantity and a PASS / WARN / BLOCK risk check. It is built as 18
Claude Code skills (plain Python 3.8+, standard library only), an MCP server, and a paper-trading
tracker in Excel. It **never places orders**: the user places them in Zerodha or Groww after an
explicit yes.

- Repo: https://github.com/R12Wan-Pat3l/tayyib-trader (owner and maintainer: Rizwan Patel)
- Latest release: **v0.2.9** (tags v0.1.0 to v0.1.11, v0.2.0 to v0.2.9; v0.1.3 is folded into v0.1.4)
- Tests: 464 offline tests plus a fresh-install smoke test (`tools/smoke_fresh.py`); CI on Python 3.8 and 3.12; releases published automatically when a `v*` tag is pushed

## Non-negotiable rules (apply to every change, including any UI)

1. **Halal-compliant stocks only.** Never show or suggest anything that is not `compliant`.
2. **Delivery (CNC) only.** No intraday, F&O, short selling, margin or MTF. These rules live in code, not in config.
3. **No order placement**, ever, without the user's explicit yes for that exact order. A UI may show
   tickets and the Kite/Groww steps; it must not place orders.
4. **Never invent data.** When a source fails, say so: UNKNOWN, never zero.
5. Every result is labelled: not financial advice, not a fatwa.
6. Standard library only for the core, Python 3.8+. Windows users run `py`.

## How it works (pipeline)

`tayyib-daily` runs all of this in one command after 3:30 PM IST:

```
halal list (auto-rebuild every 30 days) -> scan -> news -> plan -> time machine
-> size (Indian charges) -> risk check (whole orders file) -> daily list -> tracker (Excel)
```

| skill | job |
|---|---|
| tayyib-daily | one command: today's list, top 3 PASS picks, `trader/daily/DATE.md` + `.json` |
| tayyib-dashboard | local web page over the `trader/` files (127.0.0.1): Today, Results, Halal, Tickets, Backtest, Settings; GET only except `POST /api/config` and `POST /api/run` (today's list, a backtest, or (v0.2.3) a test email); first-run setup when `config.json` is missing |
| tayyib-email | today's list to the user's own inbox (personal use only; at most 3 addresses): banners first, PASS cards, other rows, tracker, held-but-not-compliant in red; FAILED / stale email instead of old picks; nothing on market-closed days; password only from `TAYYIB_SMTP_PASSWORD`; `trader/email/` (v0.2.3) |
| tayyib-tracker | paper record of every pick, followed on real prices; `tracker.xlsx`, `.csv`, `.json`; (v0.2.9) the **paper account** (PASS picks only, one cash account, vs Shariah BeES) and the 15-day report `reports/DATE.md` |
| tayyib-halal | business screen plus TASIS ratios (debt < 25% of assets, non-compliant income < 3%, cash + receivables < 90%), automatic, no overrides (v0.2.7); `compare` (read-only) against a trusted fund list; `held`: re-checks the stocks you hold (v0.2.4) |
| tayyib-scanner | swing setups (breakout, pullback, oversold, squeeze) and delivery (trend) |
| tayyib-news | Google News India, NSE announcements, Moneycontrol, ET, Mint; HALAL-WATCH flags |
| tayyib-entry / tayyib-exit | trigger status; stop (swing max 10%, delivery max 15%), target (2R / 3R), time stop |
| tayyib-timemachine | 10,000 simulated futures plus historical replay, in R after charges |
| tayyib-backtest | two options (v0.2.8): **all halal stocks** (what the daily list does) or **my stocks** (`--symbols`, 1 to 20 compliant, or `--holdings`: the same strategy on that basket only, against buying and holding the same stocks, per-stock table, hindsight banner); (v0.2.6) `--robust N` (20, max 50: seeded tie order + start ±1 day, max positions 3/5/8, ranges) and `--robust-compare A B` (paired seeds, 80% verdict); the daily strategy replayed every day of the last N years on one cash account, no look-ahead, with the live risk check (no news); late listings join at 250 bars (`--no-late`, their P&L share always shown); ends on the last completed session; metrics, in/out-of-sample, `--compare` (b: score-only ranking, c: no late joiners), Shariah ETF and Nifty 50 benchmarks, honest banners; `trader/backtest/`; dashboard tab (v0.2.0 to v0.2.2) |
| tayyib-budget / tayyib-risk | sizing (1% risk, 20% max position) and PASS / WARN / BLOCK |
| tayyib-broker | order ticket (manual placement) and journal (placed, stop, close, positions) |
| tayyib-alerts, tayyib-results, tayyib-insider, tayyib-purify | alerts, quarterly results, NSE insider and bulk deals, dividend purification |

## Data a UI can read (all local JSON in the user's `trader/` folder)

| file | contents |
|---|---|
| `daily/YYYY-MM-DD.json` | `banner` (first key; always null since v0.2.7, when the halal rules became fixed), `date, capital, broker, scanned, top_picks[], notes[]` (including `CONFIG: ...` notes), `banners[]` (list-level warnings; v0.1.9 wording: "Exchange filings unavailable today (NSE refused automated access). HALAL-WATCH and results checks are incomplete for N of M stocks: check the announcements yourself for any stock you plan to buy."), `settings{hash, label ("default@4" when nothing differs, = default@2 in decisions; "default@2" / "default@3" on older lists; "default@1" for lists before v0.1.7), defaults_version, values, differs_from_default[]}`, `rows[]`. Each row: `symbol, name, mode, setup, score, entry, stop, stop_pct, target, valid_until, max_hold_days, qty, position_rs, loss_at_stop_rs, gain_at_target_rs, rr_net, expectancy_r, past_trades, verdict, ranked_by ("expectancy" / "score"), expectancy_use ("ranked (n trades)" / "information only (n trades)"), stop_capped, risk (PASS/WARN/BLOCK/FILTERED/NOT SIZED), reasons[] ("BLOCK: ..." / "WARN: ..."), order_id, why[]`. Also `tracker{all, earlier[]}` |
| `why[]` (each daily row) | items `{group, check, value, limit, op, ok, unit, note}`, groups in order `HALAL, LIQUIDITY, SETUP, NEWS, PLAN, HISTORY, RISK`; `ok` true/false, or null when the input was missing (value null = show UNKNOWN). Recorded by each step when it decided; the last RISK item is `result`. v0.1.7 flags: HALAL ratio items `near_limit` (at or above `halal.near_limit_pct` = 90% of the limit), PLAN `stop capped` item with `stop_capped: true`, SETUP context items with `op: "info"` (% above the 200-day average, 126-day return) |
| `tracker.json` | `rows[]`: list date, symbol, mode, setup, check, entry, stop, target, qty, risk_rs, valid_until, expectancy_r, `settings_hash` ("pre-0.1.5" for older rows), plus the outcome: `status` (WAITING, NOT TRIGGERED, OPEN, TARGET, STOP, BREAKEVEN, TIME EXIT), `filled, fill, exited, exit, days, r, pnl_rs, last, checked`. Also `settings{hash: {label, first_seen, differs_from_default[]}}`, `summary{}` (incl. `settings: <label>` groups) and `settings_split{label: {differs, hashes[], first_seen, stats}}` |
| `paper_account.json` | v0.2.9: `totals{capital, equity, cash, total_return_pct, closed_trades, win_rate_pct, avg_r, total_pnl_rs, max_drawdown_pct, drawdown_peak, drawdown_trough, longest_losing_streak, open_risk_rs, too_few, ...}`, `positions[]` (state open / closed / waiting / not_triggered), `skipped[{list_date, symbol, reason}]`, `equity_curve[]`, `groups{by_mode, by_setup}`, `benchmark` (Shariah BeES; UNKNOWN + reason). See TECHNICAL.md |
| `reports/DATE.md` (+ `.json`) | v0.2.9: the shareable paper-account report (banners first, under 150 lines) |
| `halal_universe.json` | `updated, source, method` ("TASIS-style"), `thresholds{4 limits}`, `stocks{SYM: {name, industry, status, reasons[], ratios{debt_to_assets_pct, interest_income_pct, noncompliant_income_pct, assumed_return_pct, cash_receivables_to_assets_pct}, as_of, why[], near_limit[] (ratio keys from 90% of their limit up to it), over_limit[] (at or over it); v0.1.7}}` |
| settings for a UI | `tc.DEFAULT_CONFIG_DOCS`: `key -> {description, min, max, unit, type, ...}` for every setting; `tc.validate_config(user) -> (cfg, notes)`; `tc.risk_preview(cfg)` (also `daily.py --risk-preview --json`) |
| `halal_overrides.json` | no longer used (v0.2.7): never read or written; an old file gives one daily note |
| `orders.json`, `positions.json` | tickets (status SIZED/PASS/WARN/BLOCK/PLACED) and the trade journal |
| `scan.json`, `plan.json`, `sim.json`, `news.json`, `alerts.json`, `config.json` | intermediate results and settings |
| `backtest/<id>.json` (+ `.md`) | v0.2.0: `params, settings{label, hash}, window{from, to, split}, universe{compliant, tested, skipped}, skipped[{symbol, reason}], banners[]` (3 always + conditional), `metrics{overall, by_setup, by_mode}` (trades, win rate, avg / expectancy R, profit factor, return, CAGR, max drawdown with peak/trough dates, losing streak, exposure, charges), `split{in_sample, out_of_sample}`, `benchmarks{SHARIABEES.NS, ^NSEI}` (UNKNOWN + reason when not fetched), `trades[]`, `equity_curve[]`; v0.2.8 `universe{mode, symbols}`, and for a basket `basket{}` (buy and hold) and `stocks{rows[], totals}`; ids `..._symN_hex6` / `_holdN_`. See TECHNICAL.md |

Every script also prints machine-readable output with `--json`. `mcp/server.py` exposes 20 tools
over MCP (stdio), none of which place orders.

## Decisions already made

- **Halal method:** TASIS (NSE Shariah index methodology). The income test shows reported interest
  *and* "+ assumed 8% on short-term investments". If only the assumption tips a stock over, it goes to
  `review` (blocked by default).
- **Validated** against Nippon India ETF Shariah BeES and Tata Ethical Fund holdings (Sep 2026):
  - The automatic screen agreed on 81%, and every difference was on the strict side.
  - (Until v0.2.6, 8 overrides from FY26 annual reports raised that to 94.8%: SUNPHARMA, CIPLA, BHEL,
    BSOFT, CUMMINSIND, SONACOMS, SWIGGY, SYNGENE. v0.2.7 removed overrides: the automatic screen decides.)
  - ALKEM stays in review (strict ratio 2.91–2.98%).
  - HINDALCO and INDUSTOWER stay excluded (debt over 25%).
- **Charges** match Zerodha's published delivery rates to the paisa.
- **Swing vs delivery:**
  - The daily list alternates them in `--mode all`.
  - It skips stocks the user already holds.
  - Today's tickets replace earlier unplaced ones; placed orders are never touched.
- **Settings (v0.1.5):** every selection threshold is in config (`scanner.setups.<name>`, `daily.*`)
  with defaults equal to the earlier code, proved by a baseline test captured before the change
  (`tests/baseline.py`, `tests/fixtures/baseline_v0.1.4.json.gz`). Every value is validated against
  `DEFAULT_CONFIG_DOCS`; an invalid one falls back to its default for that key only and is reported as
  `CONFIG: ...`. No key can enable intraday, F&O, shorting, margin/MTF or non-compliant stocks.
- **Simple settings, halal locked (v0.2.7, owner decision, default@5):** the Settings page shows only
  money & risk (capital, risk per trade 0.25–3%, max position 5–40%, max open 1–20), broker (zerodha /
  groww; "custom" removed), five strategy switches (at least one on) and holidays, plus a read-only Halal
  card and "Always on". Fixed in code (`tc.FIXED_KEYS`; `validate_config` ignores a change with "... is
  fixed and can't be changed", an equal value silently): every halal threshold, `halal.method`,
  `allow_review` (off), `parent_list_url`, all charges and broker tables, `user_agent`. `halal.loosen_note`
  removed. No per-stock overrides. Everything else (plan, setup thresholds, liquidity, ranking, email,
  regime, news) is advanced: valid in config.json, same validation, listed on the page as "Advanced
  settings changed in config.json: N". The halal freshness keys (`list_max_age_days`, `auto_rebuild_days`,
  `near_limit_pct`, `held_recheck_days`, `exit_grace_days`) are advanced, not fixed. (Until v0.2.6 a looser
  threshold needed a `halal.loosen_note`.) **No AAOIFI preset:** it needs market value, and we fetch no share count; we do
  not approximate it.
- **Pullback on by default (v0.2.6, default@4):** v0.2.5 switched it off (default@3) from its own trades (5 y: 46,
  -0.21R); the whole-strategy backtest was worse without it on both windows (5 y CAGR 8.0% -> 4.1%, 3 y 7.9% -> 7.0%),
  so the owner reversed it. The v0.2.6 robust test then showed that single comparison was noise: pullback off beat on
  in 15 of 20 seeds (75%, no verdict), so the default stays on (the default@2 behaviour) under the 80% rule. default@4 equals default@2 in every value and decision (test against the default@2
  snapshot); default@3 stays a known historic label (`tc.DEFAULTS_HISTORY`, `settings_snapshot()["same_as"]`).
- **Rule: no default change without a `--robust-compare` verdict of 80%+ (v0.2.6).** A change to a decision default
  needs `backtest.py run --robust-compare "A" "B"` on 5 years (and 3) to say "B is better in X of N runs" (B's CAGR
  above A's on at least 80% of the seeds). Anything else ("No clear difference") keeps the default.
- **Holdings are not trades (v0.2.5):** imported from broker files (read only), kind "holding"; they count for
  the halal re-check, "already held" and purification, never for sizing, the risk check or any result.
- **Why this stock:** every daily row carries `why[]`, recorded at decision time, never recomputed.
  Missing input is `ok: null` and shown as UNKNOWN.
- **UI design tool:** UI/UX Pro Max (a Claude Code plugin) is a development-time design aid for the
  v0.1.7 dashboard. Nothing from it ships or runs in the tool.
- **Ranking on thin evidence (v0.1.7, default@2):** inside each PASS / WARN / BLOCK group, rows with at
  least `daily.min_past_trades_for_rank` (8) past trades rank by time-machine expectancy, the rest after
  them by setup score. The same key (`tc.rank_key`) sets the sizing order (which decides what position
  limits block) and the top picks. Expectancy stays visible as "information only (n trades)". With the key
  at 0 every decision equals v0.1.4 (baseline test). On the 2026-11-05 live list this moved SAILIFE (8 past
  trades) to the top and LAURUSLABS (+2.47R from 2 trades) from first pick to BLOCK (industry limit).
- **halal.list_url removed (v0.1.7):** it was never read. A config that still has it gets
  `CONFIG: halal.list_url removed: it was never used`. **Rule for any future official-list import:** it
  may only be compared with the self-screen, or make the screen stricter (exclude more). It must never mark
  a stock compliant on its own.
- **Dashboard (v0.1.7):** read-only, `127.0.0.1` only, GET / HEAD only (others 405), Host header checked
  (403), no CORS, whitelisted files, no write call. Python does every calculation; the page only draws.
  Every row and ticket is re-checked against the current halal universe; a changed stock
  shows "halal status changed since this list: re-check" and no levels. Designed with UI/UX Pro Max:
  `design-system/tayyib/MASTER.md` (plain CSS, offline, system fonts, light + dark, status by label +
  shape, colour-blind-safe Okabe-Ito hues, en-IN numbers).
- **Near vs over limit (v0.1.7 review):** `near_limit` means near_limit_pct% ≤ value < limit; value ≥ limit is
  `over_limit`, a separate flag and label. A compliant stock can't be over a limit (overrides are gone since v0.2.7).
- **Exit planner and entries.json (v0.1.7 review):** an entry record replaces today's scan signal only once the
  setup has TRIGGERED, or when the scan has nothing newer. Before, a WAITING record from an earlier day won, which
  kept WELSPUNLIV on its 2026-11-04 signal and ticket id on the 2026-11-05 list (a stale ticket, not a kept id by
  design).
- **Dashboard redesign (v0.1.7 review):** design system version 2 in `design-system/tayyib/MASTER.md` (petrol teal +
  warm off-white, serif display, bento tiles, drawer / bottom sheet, phone tab bar, no sideways scroll from 375px).
- **Two write endpoints (v0.1.8):** `POST /api/config` (settings) and `POST /api/run` (tayyib-daily,
  analysis only; v0.2.2 also a backtest: years 3 | 5, mode, compare, always `--write`, one run at a time
  shared with the daily run), and no others. Each needs Host + Origin + a per-start token (`X-Tayyib-Token`) + JSON +
  ≤ 64 KB. The server calls `tc.validate_config` and never re-implements it; all-or-nothing saves, atomic
  write, backups in `trader/config_backups/` (last 20), 409 on a stale version. Nothing places, modifies or
  cancels an order.
- **Tracker re-runs (v0.1.8):** key `date|symbol|setup|settings_hash`. A same-day re-run under other
  settings marks the earlier unfilled rows SUPERSEDED (kept, not counted anywhere); filled rows are never
  touched; same settings add nothing.
- **Tracker repeat listings (v0.1.11):** one stock is counted once while waiting or held. A later listing
  makes an earlier still-waiting row REPLACED, or (if an earlier row holds it) makes the new row
  ALREADY_HELD. Both kept, not followed, not counted. Judged on the new list's date, in list-date order,
  idempotent.
- **No bot-check circumvention (v0.1.9):** the project never imitates a browser or works around a site's
  bot checks. NSE and BSE get only the honest user agent (`tayyib-trader/<version> (+github URL)`), no
  browser headers, no cookie warm-up; a refusal is UNKNOWN, with a banner and "Check announcements
  yourself" links (opened by the user, never fetched), with a Copy ISIN button for BSE's search.
  niftyindices.com gets the honest user agent too; if refused, the halal build uses the last good cached
  copy (age shown), then the user's own `ind_nifty500list.csv`, else stops with instructions. Never a
  made-up or partial list.
- **Backtest (v0.2.0, v0.2.1):** `tayyib-backtest` calls the live functions, never copies; sizing, the daily
  pick order, the time machine and (v0.2.1) the risk check moved into core for that (old names are aliases;
  baseline unchanged). On day t only bars[0..t] are used; fills from t+1. The risk check runs on the
  simulated book (held + waiting + approved that day); BLOCK never placed, WARN placed unless
  `--no-take-warn`; news and halal-list age can't be replayed (skipped, counted, banner). Ranking uses the
  time machine only when the order can change what is bought. Universe = today's compliant list; a stock joins on its 250th bar (`joined_late[]`). Sale proceeds pay for fills from the
  next day. Groups under 30 trades are `too_few`. Banners: today's halal list, survivorship bias, "past
  results" and "news can't be replayed" always; Nifty 50 did better (reference only, not halal).
  v0.2.2: the window ends on the last completed session (`end_rule`); the late joiners' share of P&L is
  always reported. The Backtest tab draws `d.order` from the server, so banners come before numbers.
- **Email (v0.2.3):** personal use only (SEBI: sending picks to others can need Research Analyst
  registration; each person runs their own copy). The SMTP password lives only in the environment variable
  `TAYYIB_SMTP_PASSWORD`; password-like config keys are refused. `email` is outside the settings hash. A
  missing / stale / failed list sends the FAILED email, never older picks. `daily.py --email` wraps the
  unchanged pipeline; `tools/schedule_windows.py` creates only the task `tayyib-daily` (weekdays 16:20 IST,
  `--yes` required); `start.bat` (and `start.sh` on Mac / Linux, v0.2.7) sets `TAYYIB_DIR` to `%USERPROFILE%\tayyib-live\trader` (the code's
  `TAYYIB_DIR` is the trader folder).
- **My stocks backtest (v0.2.8):** the backtest has two options. "All halal stocks" is the honest test of the
  daily list (unchanged, same ids). "My stocks" (`--symbols`, up to 20, or `--holdings`) runs the same rules on a
  basket and compares it with buying and holding it (equal shares, late joiners' share as cash until they join,
  one buy and one sell charge). Every symbol must match `^[A-Z0-9&-]{1,20}$` and be compliant on today's list
  (`tc.check_backtest_symbols`, one rule for the CLI, the dashboard action and MCP); anything else is refused,
  never dropped. Always-on hindsight banner; "small basket" under 10; "holding did better" when it did. The daily
  list never changes because of it (still default@5).
- **Paper account (v0.2.9):** the number to judge before real money. Only PASS picks from lists dated on or after
  `paper.start` (2026-11-10, the first default@5 list), list order, one position per stock, `max_open_positions`
  open + waiting, cash never negative (proceeds from the next day), the list's qty; fills and exits are the
  tracker's own (`tracker.follow`). Skipped PASS picks are kept with the reason. Every 15 days
  (`report.every_days`) the daily run writes `trader/reports/DATE.md` (attached to the email); `tracker.py report`
  any time. Under 30 closed trades: "Too early to judge". Measurement only: both keys are outside the settings
  hash; the daily list is unchanged (default@5). `tracker.py summary` is the old `report` output.
- **Releases:** bump `plugin.json`, `marketplace.json`, the core `VERSION`, the MCP server version and the top CHANGELOG entry
  together. A test enforces this, and `claude plugin update` depends on it.

## The user's setup (Rizwan, Windows)

- Repo clone: `C:\Code\Trader\tayyib-trader` (remote URL pinned to the `R12Wan-Pat3l` account for pushes)
- Data folder: `%USERPROFILE%\tayyib-live` (the real `trader/` lives here; `trusted.csv` too)
- Claude Code with the plugin installed (`claude plugin update tayyib-trader@tayyib-trader`)
- Live testing is done by pasting a prompt into Claude Code on that machine and sharing the report

## Open ideas / roadmap

- **v0.1.5:** settings in config with validation and docs, the halal loosening policy,
  `why[]` on every row, settings hash in the daily list and tracker, `--risk-preview`.
- **v0.1.6:** fix for Windows: ₹ in output crashed the risk check (cp1252); all scripts now print and
  read UTF-8.
- **v0.1.7:** pipeline fixes from the live check (ranking on thin evidence = default@2,
  the news source-failure banner, why[] additions: capped stop, setup context, near halal limit;
  `halal.list_url` removed) and the read-only local dashboard (Today, Results, Halal, Tickets).
- **v0.1.8:** the Settings tab (rendered from `DEFAULT_CONFIG_DOCS`, risk preview with a
  warning above 2%, review before save, backups and restore, halal loosening needs a source), the
  "Run today's list" button, and SUPERSEDED rows for same-day re-runs under other settings.

- **v0.1.9:** honest requests to NSE (no browser imitation, no cookie warm-up), why[] NEWS
  names the sources that answered and failed, the clearer banner, and "Check announcements yourself"
  links. No decision changes (still default@2).
- **v0.1.10:** NEWS shown as two lines, "Media news" and "Exchange filings (NSE)"; when NSE
  refuses, "Not available: NSE blocks automated access → check yourself" (neutral mark, ok=null, never a
  ✓); real failures stay UNKNOWN. Display only: no decision changes (still default@2).
- **v0.1.11:** tracker accounting: REPLACED and ALREADY_HELD rows (repeat listings of a
  waiting or held stock), not counted; Excel Settings column shows the label; empty results blank.
- **v0.2.0:** `tayyib-backtest` (engine, CLI, MCP tools, tests). No pick, plan or verdict changes.
- **v0.2.1:** the backtest replays the risk check, lets recent listings join, settles sales next day,
  flags groups under 30 trades, Nifty banner, `--compare`.
- **v0.2.2:** the Backtest tab and its Run button; the window ends on the last completed
  session; `--no-late`, compare column (c), the late joiners' P&L share. No daily-list changes (default@2).
- **v0.2.3:** `tayyib-email`, `daily.py --email`, the Windows scheduled task, `start.bat` and
  the first-run setup, the Settings Email section with "Send test email", drawdown labels that never cross
  their lines. No daily-list changes (default@2).
- **v0.2.4:** held-stock halal alerts (`halal.py held`: No longer compliant / Near a limit /
  Could not verify, one per status change, a SELL ticket and a purification estimate, resolved on sale); the
  market-regime filter, OFF (live, the Today header, `backtest --regime` / `--regime-compare`, a Settings
  group); Why ordering, the time-machine label, market-closed detection (`--force`). No daily-list changes
  with defaults (default@2).
- **v0.2.5**: **pullback off by default (default@3; reversed in v0.2.6)**, owner decision from the 5-year backtest
  (pullback's own trades: 46, -0.21R); with it on, every decision is the default@2 one (test + snapshots). Note:
  the whole strategy did worse without it on the same windows (5 y CAGR 8.0% -> 4.1%, 3 y 7.9% -> 7.0%); see the
  CHANGELOG. Holdings import from Zerodha / Groww files (`ticket.py import`, read only, preview first, kind
  "holding": not trades). "Not compliant now (status at purchase unknown)". Risk-off date ranges.
- **v0.2.6**: **pullback back on (default@4 = default@2)**, the v0.2.5 banner replaced by a one-time
  "Pullback is back on by default (v0.2.6)" banner (configs with their own pullback setting untouched), and the
  robustness test: `backtest.py run --robust [N]` and `--robust-compare "A" "B"`, with range bars and the verdict in
  the Backtest tab.
- **v0.2.7**: install from the docs alone. `start.sh` (Mac / Linux), `tools/smoke_fresh.py`
  (fresh-install smoke test, in CI), README three quick starts, the no-Claude command for every journal step in
  the user guide, troubleshooting rows, a developer quick start. Then the owner decision **simple settings**:
  only money/risk, broker, strategies and holidays on the page; halal rules, charges and user agent fixed in
  code; halal overrides removed; backtest `--max-positions` follows `max_open_positions` (6). default@5:
  with the same halal list every decision equals default@4 (= default@2), proved by
  `tests/fixtures/baseline_default5.json.gz`.
- **v0.2.8**: the backtest's second option, **My stocks** (`--symbols`, `--holdings`), with the
  buy-and-hold basket, per-stock table and hindsight banners; the Run panel's choice (all / my stocks with search
  and chips / stocks I hold); MCP `backtest_run` symbols / holdings; the v0.2.7 review's doc leftovers (FAQ,
  README, pullback switch line). No daily-list changes (default@5).
- **v0.2.9** (this release): the paper account (PASS only, one cash account, skipped picks with reasons, vs the
  Shariah BeES), `tracker.py paper` / `report` / `summary`, the 15-day report (auto in the daily run, attached to
  the email), the Results tab card and saved reports. No daily-list changes (default@5).
- **Next:** switch the regime filter on only with a robust-compare verdict of 80%+ on 3 and 5 years.

Later:
- Read-only Zerodha / Groww connection (holdings, positions)
- Results-due dates and company announcements via the read-only broker API, if the API offers them
  (instead of NSE / BSE, which refuse automated access)
- Zakat calculator; automatic import of the official Nifty Shariah lists; NSE holiday calendar
