# tayyib-trader

**13 AI skills for halal swing and delivery trading on Indian stocks (NSE/BSE).** Screen for
Shariah compliance, scan charts, read Indian market news, time the entry, plan the exit, replay the
trade 10,000 times, size it with real Indian charges, check the risk, get an order ticket you place
yourself, then track alerts, results, insider deals and dividend purification.

> *"O mankind, eat from whatever is on earth that is lawful and good (halalan tayyiban)."* (Al-Baqarah 2:168)

Free and MIT-licensed. You don't sign up for anything, need no API key and install nothing:
plain Python 3.8+ standard library, reading free public data (Yahoo Finance, NSE, Google News
India, Moneycontrol, ET Markets, Livemint). Works with Claude (as skills), any MCP client (Claude
Desktop, Cursor, ChatGPT and others), and any AI coding agent that can run a command (see
[AGENTS.md](AGENTS.md)).

**Nothing here can place an order.** There is no broker connection in this version. You get a
ticket in plain words, you say yes, and you place it in Kite or Groww yourself.

---

## Read this first

- **Not financial advice.** This is software that reads public data and does arithmetic. It does not
  know your situation and cannot see the future. SEBI's own studies have found that most individual
  intraday and F&O traders in India lose money. Swing trading is not a shortcut either. You can lose
  money.
- **Not a fatwa.** The halal screen is an automated approximation of a published methodology (TASIS,
  the screen behind NSE's Shariah indices). Data can be wrong or stale. For a ruling, ask a qualified
  scholar or a recognised Shariah board, and record their ruling with `tayyib-halal override`.
- **Free data is unofficial.** Yahoo's and NSE's endpoints can lag, change or block automated use.
  Check anything that matters in your broker app or on the exchange.

## What is different here

| | |
|---|---|
| **Halal first** | Every scan starts from a Shariah-screened universe. A stock that isn't `compliant` never reaches the scanner, and the risk manager blocks any order for it. |
| **Swing and delivery only** | Positions are held for days (swing) or months (delivery), as CNC. Intraday is left out on purpose (see [the fiqh note](#why-no-intraday-fo-or-short-selling)). |
| **Hard rules in code** | CNC only. BUY to open; never sell more than you hold. No futures, options, margin or MTF. These cannot be switched off from the config. |
| **Indian costs** | STT, stamp duty, exchange and SEBI fees, GST and DP charges, plus Zerodha or Groww brokerage, are counted in sizing, reward:risk and every backtest. |
| **Purification** | Works out how much of your dividends (and, if you choose, gains) to give away for the company's non-compliant income. |

## The thirteen

| skill | job | what it does |
|---|---|---|
| `tayyib-halal` | Halal Screener | Builds the Shariah-screened universe: business screen, plus TASIS-style ratios (debt < 25% of assets, non-compliant income < 3%, cash + receivables < 90% of assets), or loads an official list. Your overrides win. |
| `tayyib-scanner` | Chart Scanner | Scans halal stocks for swing setups (breakout, pullback to the 20 EMA, oversold bounce, squeeze) and delivery setups (long-term trend), with liquidity filters. |
| `tayyib-news` | News Monitor | Google News India, NSE announcements, Moneycontrol, ET, Mint. Tags each headline and flags **HALAL-WATCH** items (new debt, entering an impermissible business). |
| `tayyib-entry` | Entry Timer | Reports WAITING, TRIGGERED, EXTENDED (don't chase), INVALIDATED or EXPIRED against the setup's buy-stop trigger. |
| `tayyib-exit` | Exit Planner | Sets the stop, target, time stop and trailing rules before you buy. |
| `tayyib-timemachine` | Time Machine | Runs 10,000 simulated futures from the stock's own history, plus every past time the setup fired, in R after charges, with an honest verdict. |
| `tayyib-budget` | Budget Manager | Sizes in whole shares so the loss at the stop, including charges, stays within your limit. |
| `tayyib-risk` | Risk Manager | Returns PASS, WARN or BLOCK, covering the hard rules, halal status, per-trade risk, position size, cash, portfolio heat, industry concentration and net reward:risk. |
| `tayyib-broker` | Order Ticket | Gives a plain-words ticket with Zerodha and Groww steps, and keeps your journal (placed, stop, close, positions). Places nothing. |
| `tayyib-alerts` | Price Alerts | Rings once at an entry trigger, stop, target or time stop. |
| `tayyib-results` | Results Analyst | Shows quarterly revenue, profit and EPS growth, plus how the halal ratios moved year on year. |
| `tayyib-insider` | Insider Tracker | Shows SEBI insider-trading (PIT) disclosures, promoter buying and pledges, and NSE bulk and block deals. |
| `tayyib-purify` | Purification | Gives the charity amount for dividends and gains from non-compliant income. |

## How a trade flows

```
halal -> scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker (you place it)
while holding: alerts, broker stop/close            on a schedule: news, results, insider, halal rebuild
year end: purify
```

Everything is written to a `trader/` folder in your working directory, and each skill reads what the
previous one wrote. With Claude you just talk ("scan for halal swing setups", "plan ALFA", "how many
shares", "is it OK?", "give me the ticket"), and it runs the commands below.

```bash
python3 tayyib-halal/halal.py build                   # monthly: ~500 stocks screened (takes a few minutes)
python3 tayyib-scanner/scan.py --mode swing           # -> trader/scan.json
python3 tayyib-news/news.py                           # headlines for the candidates
python3 tayyib-entry/entry.py check ALFA
python3 tayyib-exit/exit.py plan ALFA --write         # -> trader/plan.json
python3 tayyib-timemachine/timemachine.py run --write
python3 tayyib-budget/size.py --write                 # -> trader/orders.json
python3 tayyib-risk/check.py                          # PASS / WARN / BLOCK
python3 tayyib-broker/ticket.py show                  # you place it in Kite / Groww
python3 tayyib-broker/ticket.py placed ALFA-2026-10-30-breakout --price 1004.50
python3 tayyib-alerts/alerts.py add --from-positions
python3 tayyib-broker/ticket.py close ALFA --price 1064.10 --reason target
python3 tayyib-purify/purify.py report --year 2026 --include-gains
```

Here is example output from the offline test data. **ALFA is an invented company with synthetic prices**,
so the numbers only show what the tools report:

```
ALFA  swing/breakout  entry 1003.00  stop 972.45  target 1064.10
  10000 simulated futures (seed 7, from 499 real sessions):
    target first 37.7%  stop first 36.0%  breakeven 22.7%  time stop 3.6%
    expectancy +0.34R after charges, median 7.0 sessions
  history: 10 past trades: 1 target, 5 stop, 0 breakeven, 4 time; win 50%, +0.01R each
  verdict: close to a coin flip after charges

  ALFA  BUY 19 (CNC) trigger 1003.00 limit 1008.05 = Rs 19,057.00 (19.1% of capital)
        stop 972.45 -> lose Rs 637.60 incl. charges; target 1064.10 -> gain Rs 1,101.95; 1.73 : 1 net
```

A 2R target nets about 1.7R once charges are counted, so the default minimum net reward:risk is 1.5.

## Install

**New here, or sharing this with someone who doesn't code?** Start with
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md): three simple ways to use it, step by step.


**Claude Code (plugin):**

```
/plugin marketplace add R12Wan-Pat3l/tayyib-trader
/plugin install tayyib-trader@tayyib-trader
```

Installed as a plugin, the skills appear as `/tayyib-trader:tayyib-scanner` and so on. If you'd rather have
plain names, copy the folders instead; each one is self-contained:

```bash
git clone https://github.com/R12Wan-Pat3l/tayyib-trader.git
cp -r tayyib-trader/tayyib-* ~/.claude/skills/
```

**Any MCP client** (Claude Desktop, Cursor, ChatGPT connectors and others): add the stdio server. It
exposes 16 tools for analysis, planning and checks. None of them place orders.

```json
{
  "mcpServers": {
    "tayyib-trader": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/tayyib-trader/mcp/server.py"],
      "env": { "TAYYIB_DIR": "/ABSOLUTE/PATH/TO/your-trading-folder/trader" }
    }
  }
}
```

**Other AI agents** (Codex, Gemini CLI, Aider, Copilot and others): point them at [AGENTS.md](AGENTS.md).
**No AI at all**: run the scripts yourself. Every one has `--help` and `--json`.

## Configure

Copy `config.example.json` to `trader/config.json` and set your own numbers:

| key | default | meaning |
|---|---|---|
| `capital` | 100000 | your trading capital in rupees |
| `max_risk_per_trade_pct` | 1.0 | loss at the stop, including charges, as % of capital |
| `max_position_pct` | 20 | the most you put into one stock |
| `max_open_positions` | 6 | |
| `max_portfolio_heat_pct` | 6 | total open risk across all positions |
| `max_positions_per_industry` | 2 | |
| `min_reward_risk` | 1.5 | net of charges |
| `modes.swing.max_stop_pct` | 10 | widest swing stop, % below entry (delivery: 15) |
| `broker` | zerodha | `zerodha`, `groww` or `custom` (sets brokerage and DP charge) |
| `holidays` | [] | NSE trading holidays, `"YYYY-MM-DD"` |
| `halal.allow_review` | false | let `review` stocks through, with a warning |
| `halal.max_*` | 25 / 3 / 90 | the three TASIS-style thresholds |

Charges are approximate 2026 rates for equity delivery. Check your broker's charges page.

## Halal method

1. **Business screen.** These are excluded: interest-based finance (NSE's "Financial Services" industry: banks,
   NBFCs, insurers), alcohol, tobacco and gambling businesses, and company names that clearly say so.
   Media and entertainment, and names with words such as finance, capital or hotel(s), go to **review**,
   which stays blocked unless you allow it.
2. **Financial screen**, using the TASIS methodology that NSE's Nifty Shariah indices are screened with:
   borrowings < 25% of total assets; interest income plus an assumed 8% return on interest-bearing
   investments < 3% of total income; cash + receivables < 90% of total assets. A stock that fails
   only the income test, by less than twice the limit, goes to **review** rather than excluded:
   free data often counts treasury or other income as interest, so that case needs a human check.
3. **Overrides**: your ruling (or your scholar's) on any stock, which wins over everything else.

Self-screening uses Yahoo's fundamentals, which have gaps for Indian companies. If you have an official
list (for example the Nifty 500 Shariah constituents, or an export from a TASIS-based screener), use
`halal.py build --official list.csv`. Rebuild monthly and after each results season. `tayyib-results`
flags ratios drifting toward a limit, and `tayyib-news` flags new borrowing.

### Why no intraday, F&O or short selling

- **Intraday.** In an intraday trade the shares are sold before delivery (T+1), so they never come into your
  possession. The Prophet ﷺ said: *"Whoever buys foodstuff should not sell it until he has taken
  possession of it"* (Sahih al-Bukhari 2133, Sahih Muslim 1525). Many Hanafi scholars and Darul Iftas
  in the subcontinent therefore hold intraday trading impermissible. Others allow it on the view that
  ownership and constructive possession pass when the contract is made. This is a real difference of
  opinion, and this project takes the cautious side.
- **Futures and options, short selling, margin.** Most contemporary scholars hold these impermissible:
  they involve selling what one does not own, interest-bearing borrowing, or excessive uncertainty
  (gharar). See AAOIFI Shariah Standard 21 (Financial Paper) and Mufti Muhammad Taqi Usmani's writings on
  shares.
- **Purification.** Many scholars hold that the non-compliant share of a dividend must be given to
  charity. Some recommend doing the same for capital gains as a precaution. `tayyib-purify` does the
  arithmetic; the ruling is your scholar's.

## Data sources

| data | source | notes |
|---|---|---|
| daily prices | Yahoo Finance chart API (`.NS`) | free and unofficial; cached per day |
| fundamentals | Yahoo fundamentals-timeseries | gaps for Indian companies |
| Nifty 500 list | niftyindices.com constituent CSV | the default universe to self-screen |
| announcements, insider (PIT), bulk/block deals | nseindia.com JSON | needs a cookie (handled); often HTTP 403 for scripts, reported as UNKNOWN, never as zero |
| news | Google News India RSS, Moneycontrol, ET Markets, Livemint RSS | feeds are editable in config |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The 77 tests run offline on **synthetic fixtures**: invented companies, seeded price walks, and real
data formats (Yahoo, NSE CSV and JSON, RSS). They cover the indicators, the charges arithmetic, the halal
screens, every hard rule, a full trade from screen to purification, and the MCP server. To regenerate
the fixtures, run `tests/make_fixtures.py`. For live checks against real data, see [TESTING.md](TESTING.md).

## Roadmap

- Broker connections: Zerodha Kite (official MCP) and Groww, read-only first (holdings, positions),
  with order placement only behind an explicit per-order yes
- Automatic import of the official Nifty Shariah constituent lists
- BSE-only stocks, weekly-bar setups for delivery, NSE holiday calendar
- Zakat on holdings (a calculator, alongside purification)

## Contributing

Only the maintainer can change this repository. Suggestions come as pull requests from a fork and
are merged only after review. See [CONTRIBUTING.md](CONTRIBUTING.md) for the rules every change must keep,
and [SECURITY.md](SECURITY.md) to report a problem privately.

## Credits

The structure (a pipeline of skills sharing a `trader/` folder, a Time Machine replay, risk checks
before any ticket, and no trade without your yes) follows
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) by Jake Schincariol (MIT).
This project rewrites it for Indian markets, halal screening and swing/delivery trading. Its code is
new, and its license keeps Jake's copyright notice.

MIT. Made by [Rizwan Patel](https://github.com/R12Wan-Pat3l).
