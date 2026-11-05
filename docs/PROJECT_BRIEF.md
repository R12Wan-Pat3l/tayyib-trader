# tayyib-trader: project brief

Context for any new chat or AI session working on this project (for example a UI). Read this first,
then [TECHNICAL.md](TECHNICAL.md) for details. Last updated: 2026-11-05 (v0.1.5).

## What it is

A free, open-source (MIT) tool that gives a **daily list of halal (Shariah-screened) NSE stocks**
with entry, stop-loss, target, quantity and a PASS / WARN / BLOCK risk check. It is built as 15
Claude Code skills (plain Python 3.8+, standard library only), an MCP server, and a paper-trading
tracker in Excel. It **never places orders**: the user places them in Zerodha or Groww after an
explicit yes.

- Repo: https://github.com/R12Wan-Pat3l/tayyib-trader (owner and maintainer: Rizwan Patel)
- Latest release: **v0.1.5** (tags v0.1.0, v0.1.1, v0.1.2, v0.1.4, v0.1.5; v0.1.3 is folded into v0.1.4)
- Tests: 162 offline tests; CI on Python 3.8 and 3.12; releases published automatically when a `v*` tag is pushed

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
| tayyib-tracker | paper record of every pick, followed on real prices; `tracker.xlsx`, `.csv`, `.json` |
| tayyib-halal | business screen plus TASIS ratios (debt < 25% of assets, non-compliant income < 3%, cash + receivables < 90%), plus user overrides; `compare` against a trusted fund list |
| tayyib-scanner | swing setups (breakout, pullback, oversold, squeeze) and delivery (trend) |
| tayyib-news | Google News India, NSE announcements, Moneycontrol, ET, Mint; HALAL-WATCH flags |
| tayyib-entry / tayyib-exit | trigger status; stop (swing max 10%, delivery max 15%), target (2R / 3R), time stop |
| tayyib-timemachine | 10,000 simulated futures plus historical replay, in R after charges |
| tayyib-budget / tayyib-risk | sizing (1% risk, 20% max position) and PASS / WARN / BLOCK |
| tayyib-broker | order ticket (manual placement) and journal (placed, stop, close, positions) |
| tayyib-alerts, tayyib-results, tayyib-insider, tayyib-purify | alerts, quarterly results, NSE insider and bulk deals, dividend purification |

## Data a UI can read (all local JSON in the user's `trader/` folder)

| file | contents |
|---|---|
| `daily/YYYY-MM-DD.json` | `banner` (first key, only when halal thresholds are looser than TASIS), `date, capital, broker, scanned, top_picks[], notes[]` (including `CONFIG: ...` notes), `settings{hash, label ("default@1" when nothing differs), defaults_version, values, differs_from_default[]}`, `rows[]`. Each row: `symbol, name, mode, setup, score, entry, stop, stop_pct, target, valid_until, max_hold_days, qty, position_rs, loss_at_stop_rs, gain_at_target_rs, rr_net, expectancy_r, past_trades, verdict, risk (PASS/WARN/BLOCK/FILTERED/NOT SIZED), reasons[] ("BLOCK: ..." / "WARN: ..."), order_id, why[]`. Also `tracker{all, earlier[]}` |
| `why[]` (each daily row) | items `{group, check, value, limit, op, ok, unit, note}`, groups in order `HALAL, LIQUIDITY, SETUP, NEWS, PLAN, HISTORY, RISK`; `ok` true/false, or null when the input was missing (value null = show UNKNOWN). Recorded by each step when it decided; the last RISK item is `result` |
| `tracker.json` | `rows[]`: list date, symbol, mode, setup, check, entry, stop, target, qty, risk_rs, valid_until, expectancy_r, `settings_hash` ("pre-0.1.5" for older rows), plus the outcome: `status` (WAITING, NOT TRIGGERED, OPEN, TARGET, STOP, BREAKEVEN, TIME EXIT), `filled, fill, exited, exit, days, r, pnl_rs, last, checked`. Also `settings{hash: {label, first_seen, differs_from_default[]}}`, `summary{}` (incl. `settings: <label>` groups) and `settings_split{label: {differs, hashes[], first_seen, stats}}` |
| `halal_universe.json` | `updated, source, method` ("TASIS-style" or "custom"), `thresholds{4 limits}`, `loosened` (the note, or null), `stocks{SYM: {name, industry, status, reasons[], ratios{debt_to_assets_pct, interest_income_pct, noncompliant_income_pct, assumed_return_pct, cash_receivables_to_assets_pct}, as_of, why[]}}` |
| settings for a UI | `tc.DEFAULT_CONFIG_DOCS`: `key -> {description, min, max, unit, type, ...}` for every setting; `tc.validate_config(user) -> (cfg, notes)`; `tc.risk_preview(cfg)` (also `daily.py --risk-preview --json`) |
| `halal_overrides.json` | `{SYM: {status, note, date}}`: the user's rulings, which always win |
| `orders.json`, `positions.json` | tickets (status SIZED/PASS/WARN/BLOCK/PLACED) and the trade journal |
| `scan.json`, `plan.json`, `sim.json`, `news.json`, `alerts.json`, `config.json` | intermediate results and settings |

Every script also prints machine-readable output with `--json`. `mcp/server.py` exposes 18 tools
over MCP (stdio), none of which place orders.

## Decisions already made

- **Halal method:** TASIS (NSE Shariah index methodology). The income test shows reported interest
  *and* "+ assumed 8% on short-term investments". If only the assumption tips a stock over, it goes to
  `review` (blocked by default).
- **Validated** against Nippon India ETF Shariah BeES and Tata Ethical Fund holdings (Sep 2026):
  - The automatic screen agreed on 81%, and every difference was on the strict side.
  - Agreement rose to 94.8% after 8 overrides checked against FY26 annual reports: SUNPHARMA, CIPLA,
    BHEL, BSOFT, CUMMINSIND, SONACOMS, SWIGGY, SYNGENE.
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
- **Halal loosening policy:** stricter than TASIS is always allowed. Looser (debt > 25, income > 3,
  cash + receivables > 90, assumed return < 8, or `allow_review`) needs a written `halal.loosen_note`
  (the user's scholar or source); without it the tool reports an error and keeps TASIS. With it, every
  daily list and halal list output starts with "Halal thresholds are looser than TASIS (your
  setting): <note>". **No AAOIFI preset:** it needs market value, and we fetch no share count; we do
  not approximate it.
- **Why this stock:** every daily row carries `why[]`, recorded at decision time, never recomputed.
  Missing input is `ok: null` and shown as UNKNOWN.
- **UI design tool:** UI/UX Pro Max (a Claude Code plugin) is a development-time design aid for the
  v0.1.6 dashboard. Nothing from it ships or runs in the tool.
- **Run button: not before v0.1.7.** The v0.1.6 dashboard is read-only. v0.1.7 may add a button that
  runs `tayyib-daily` locally (analysis only); it will never place, modify or cancel an order.
- **Releases:** bump `plugin.json`, the core `VERSION`, the MCP server version and the top CHANGELOG entry
  together. A test enforces this, and `claude plugin update` depends on it.

## The user's setup (Rizwan, Windows)

- Repo clone: `C:\Code\Trader\tayyib-trader` (remote URL pinned to the `R12Wan-Pat3l` account for pushes)
- Data folder: `%USERPROFILE%\tayyib-live` (the real `trader/` lives here; `trusted.csv` too)
- Claude Code with the plugin installed (`claude plugin update tayyib-trader@tayyib-trader`)
- Live testing is done by pasting a prompt into Claude Code on that machine and sharing the report

## Open ideas / roadmap

- **v0.1.5** (this release): settings in config with validation and docs, the halal loosening policy,
  `why[]` on every row, settings hash in the daily list and tracker, `--risk-preview`.
- **v0.1.6:** a local, read-only dashboard over the `trader/` JSON files (designed with UI/UX Pro Max
  at development time): today's list with each row's `why[]`, top picks, the tracker (equity curve,
  win rate by PASS/WARN/BLOCK and by settings hash), halal status with ratios, tickets with the
  Kite/Groww steps, and a settings screen rendered from `DEFAULT_CONFIG_DOCS` with the risk preview.
- **v0.1.7:** a run button for `tayyib-daily` from the dashboard (local, analysis only, no orders).

Later:
- Scheduled daily run (Windows Task Scheduler steps are already in the User guide)
- Read-only Zerodha / Groww connection (holdings, positions)
- Zakat calculator; automatic import of the official Nifty Shariah lists; NSE holiday calendar
