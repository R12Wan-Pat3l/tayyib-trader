# tayyib-trader: project brief

Context for any new chat or AI session working on this project (for example a UI). Read this first,
then [TECHNICAL.md](TECHNICAL.md) for details. Last updated: 2026-11-05 (v0.1.4).

## What it is

A free, open-source (MIT) tool that gives a **daily list of halal (Shariah-screened) NSE stocks**
with entry, stop-loss, target, quantity and a PASS / WARN / BLOCK risk check. It is built as 15
Claude Code skills (plain Python 3.8+, standard library only), an MCP server, and a paper-trading
tracker in Excel. It **never places orders**: the user places them in Zerodha or Groww after an
explicit yes.

- Repo: https://github.com/R12Wan-Pat3l/tayyib-trader (owner and maintainer: Rizwan Patel)
- Latest release: **v0.1.4** (tags v0.1.0, v0.1.1, v0.1.2, v0.1.4; v0.1.3 is folded into v0.1.4)
- Tests: 115 offline tests; CI on Python 3.8 and 3.12; releases published automatically when a `v*` tag is pushed

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
| `daily/YYYY-MM-DD.json` | `date, capital, broker, scanned, top_picks[], notes[], rows[]`. Each row: `symbol, name, mode, setup, score, entry, stop, stop_pct, target, valid_until, max_hold_days, qty, position_rs, loss_at_stop_rs, gain_at_target_rs, rr_net, expectancy_r, past_trades, verdict, risk (PASS/WARN/BLOCK), reasons[] ("BLOCK: ..." / "WARN: ..."), order_id`. Also `tracker{all, earlier[]}` |
| `tracker.json` | `rows[]`: list date, symbol, mode, setup, check, entry, stop, target, qty, risk_rs, valid_until, expectancy_r, plus the outcome: `status` (WAITING, NOT TRIGGERED, OPEN, TARGET, STOP, BREAKEVEN, TIME EXIT), `filled, fill, exited, exit, days, r, pnl_rs, last, checked` |
| `halal_universe.json` | `updated, source, stocks{SYM: {name, industry, status, reasons[], ratios{debt_to_assets_pct, interest_income_pct, noncompliant_income_pct, assumed_return_pct, cash_receivables_to_assets_pct}}}` |
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
- **Releases:** bump `plugin.json`, the core `VERSION`, the MCP server version and the top CHANGELOG entry
  together. A test enforces this, and `claude plugin update` depends on it.

## The user's setup (Rizwan, Windows)

- Repo clone: `C:\Code\Trader\tayyib-trader` (remote URL pinned to the `R12Wan-Pat3l` account for pushes)
- Data folder: `%USERPROFILE%\tayyib-live` (the real `trader/` lives here; `trusted.csv` too)
- Claude Code with the plugin installed (`claude plugin update tayyib-trader@tayyib-trader`)
- Live testing is done by pasting a prompt into Claude Code on that machine and sharing the report

## Open ideas / roadmap

- **UI** (next): a local dashboard over the `trader/` JSON files. It would show today's list, top picks,
  the tracker (equity curve, win rate by PASS/WARN/BLOCK), halal status with ratios, and tickets with
  Kite/Groww steps. Read-only; no order placement.
- Scheduled daily run (Windows Task Scheduler steps are already in the User guide)
- Read-only Zerodha / Groww connection (holdings, positions)
- Zakat calculator; automatic import of the official Nifty Shariah lists; NSE holiday calendar
