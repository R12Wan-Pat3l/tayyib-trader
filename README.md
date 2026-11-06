# tayyib-trader

**A free tool that gives you a daily list of halal Indian stocks to trade, with the buy price,
stop-loss, target and how many shares to buy.** You run one command (or ask Claude) after the
market closes. You decide, and you place the order yourself.

> *"O mankind, eat from whatever is on earth that is lawful and good (halalan tayyiban)."* (Al-Baqarah 2:168)

## What it does

- **Halal only.** Every stock is screened for Shariah compliance first. Anything that fails is never shown.
- **Finds trade setups** on NSE stocks every day: swing trades (days to weeks) and delivery (months).
- **Plans each trade:** where to buy, where to cut the loss, where to take profit, and when to give up.
- **Sizes it for you:** how many shares, so one bad trade loses at most 1% of your money, after all
  Indian charges (STT, stamp duty, GST, DP).
- **Tests it on the past** before you risk anything, and tells you honestly if the odds are poor.
- **Keeps score in Excel.** Every pick is followed afterwards: did it reach the buy price, then the target
  or the stop? So you can check the list honestly before using real money.
- **Never places an order.** You get the steps for Zerodha or Groww and do it yourself.

## Is it safe to use?

- **Delivery (CNC) only:** no intraday, no F&O, no short selling, no margin. These are built into the
  code and cannot be switched on.
- **Not financial advice.** Most retail traders lose money. Paper trade first.
- **Not a fatwa.** The halal screen is an automated version of a published method (TASIS, used by
  NSE's Shariah indices). Ask your scholar for rulings, and record them in the tool.

## Start here

| You are... | Read |
|---|---|
| New, not technical | **[User guide](docs/USER_GUIDE.md)**: install, first run, daily routine, step by step |
| Curious how it works | **[How it works](docs/HOW_IT_WORKS.md)**: the whole thing in plain words |
| Asking "how do you decide halal?", "where is the data from?" | **[FAQ](docs/FAQ.md)** |
| A developer | **[Technical guide](docs/TECHNICAL.md)**: architecture, files, commands, config, tests |
| An AI session joining the project | **[Project brief](docs/PROJECT_BRIEF.md)**: what exists, decisions made, data files |

## Quick start (Claude Code)

1. Install [Python](https://www.python.org/downloads/) and [Claude Code](https://claude.com/claude-code).
2. In Claude Code, add the tool (one time):
   ```
   /plugin marketplace add R12Wan-Pat3l/tayyib-trader
   /plugin install tayyib-trader@tayyib-trader
   ```
3. Every trading day after 3:30 PM, ask: **"Give me today's halal list"**.
4. Pick a stock you like, ask **"show me the ticket for SYMBOL"**, and place it yourself in Kite or Groww.
5. Open `tayyib-live\trader\tracker.xlsx` any time to see how every earlier pick did, or ask
   **"show my dashboard"** to see everything in your browser, change your settings safely and run today's list.

The first run builds the halal list (about 5 minutes). After that it refreshes itself every month.

## The 18 skills

| skill | in one line |
|---|---|
| `tayyib-daily` | **The one you use:** today's halal list with entry, stop, target, quantity and PASS/WARN/BLOCK |
| `tayyib-tracker` | **Excel record:** did each earlier pick hit its target or its stop? Win rate and average result |
| `tayyib-dashboard` | **Your dashboard** in the browser (on your own computer, places no order): today's list with the why, results, halal ratios, tickets, settings, a run button |
| `tayyib-email` | **Today's list in your own inbox** every trading day, sent from your computer (for you only; the password stays in Windows) |
| `tayyib-halal` | Builds and checks the halal (Shariah-screened) stock list |
| `tayyib-scanner` | Finds trade setups on halal stocks |
| `tayyib-news` | Indian market news per stock, with HALAL-WATCH flags |
| `tayyib-entry` | Has the buy price been reached yet? |
| `tayyib-exit` | Sets the stop-loss, target and time limit |
| `tayyib-timemachine` | Replays the trade 10,000 times on the stock's own history |
| `tayyib-backtest` | **"How did this strategy do?"** Runs the daily list every day of the last 3 years on your capital, with honest warnings |
| `tayyib-budget` | How many shares, after Indian charges |
| `tayyib-risk` | PASS / WARN / BLOCK against your limits and the hard rules |
| `tayyib-broker` | The order ticket you place yourself, and your trade journal |
| `tayyib-alerts` | Rings when a price, stop, target or date is hit |
| `tayyib-results` | Quarterly results and halal ratio changes |
| `tayyib-insider` | Promoter buying/selling and bulk deals (NSE) |
| `tayyib-purify` | How much of your dividends to give in charity (purification) |

## Licence and credits

Licence: **MIT** (free to use, change and share; keep the copyright notice). Made by
[Rizwan Patel](https://github.com/R12Wan-Pat3l). The design follows
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) by Jake Schincariol (MIT),
rewritten for Indian markets, halal screening and swing/delivery trading.
Changes: [CHANGELOG](CHANGELOG.md). Contributing: [CONTRIBUTING](CONTRIBUTING.md). Security: [SECURITY](SECURITY.md).
