# FAQ

**Halal screen**
- [What makes a stock "halal" in this tool?](#what-makes-a-stock-halal-in-this-tool)
- [Which businesses are excluded?](#which-businesses-are-excluded)
- [What are the financial ratio tests?](#what-are-the-financial-ratio-tests)
- [What do compliant, review, excluded and unknown mean?](#what-do-compliant-review-excluded-and-unknown-mean)
- [How do I check the halal list is right?](#how-do-i-check-the-halal-list-is-right)
- [A stock I know is halal is blocked. What do I do?](#a-stock-i-know-is-halal-is-blocked-what-do-i-do)
- [How often is the halal list updated?](#how-often-is-the-halal-list-updated)
- [Why no intraday, F&O or short selling?](#why-no-intraday-fo-or-short-selling)
- [What is purification?](#what-is-purification)

**Data and trading**
- [Where does the data come from?](#where-does-the-data-come-from)
- [How does it pick stocks?](#how-does-it-pick-stocks)
- [What do PASS, WARN and BLOCK mean?](#what-do-pass-warn-and-block-mean)
- [What is "R"?](#what-is-r)
- [Can I trust the time machine?](#can-i-trust-the-time-machine)
- [How do I know if the daily list actually works?](#how-do-i-know-if-the-daily-list-actually-works)
- [Does it place orders? Can it connect to Zerodha or Groww?](#does-it-place-orders-can-it-connect-to-zerodha-or-groww)
- [How accurate are the charges?](#how-accurate-are-the-charges)
- [When should I run it?](#when-should-i-run-it)
- [Where is my data stored? Is it private?](#where-is-my-data-stored-is-it-private)
- [Is it free?](#is-it-free)

---

## Halal screen

### What makes a stock "halal" in this tool?
Two checks, in order, both automatic:
1. **Business screen:** is the company's main business permissible?
2. **Financial screen:** three ratios from its latest annual accounts (TASIS method, the same one
   NSE uses for its Nifty Shariah indices).

There is no per-stock override (since v0.2.7): the automatic screen decides, and it errs on the strict
side.

Only stocks marked **compliant** reach the scanner, and the risk check blocks orders for anything
else. This is an automated approximation, not a fatwa.

### Which businesses are excluded?
- **Interest-based finance:** every company in NSE's "Financial Services" industry (banks, NBFCs,
  insurers, lenders).
- **Known impermissible businesses:** ITC, Godfrey Phillips, VST (tobacco); United Breweries, United
  Spirits, Radico Khaitan, Tilaknagar, Globus Spirits (alcohol); Delta Corp (casinos).
- **Names that say so:** bank, insurance, assurance, brewery, distiller, spirits, liquor, wine, blender,
  tobacco, cigarette, casino.
- **Sent to review** (blocked unless you allow it): media and entertainment, and names containing
  finance, financial, capital, credit, invest, hotel, resort, entertainment, media, film, gaming,
  leisure. These need a human look: "Tube Investments" is an engineering company, for example.

### What are the financial ratio tests?
From the latest annual numbers (Yahoo Finance):

| test | limit | why |
|---|---|---|
| Borrowings / total assets | under 25% | limits dependence on interest-bearing debt |
| Non-compliant income / total income | under 3% | interest and similar income must be a small part |
| (Cash + receivables) / total assets | under 90% | the share must represent a real business, not money |

For the income test the tool shows two figures:
- **reported interest:** what the company declared.
- **+ assumed 8%:** TASIS also assumes an 8% return on the company's short-term investments
  (liquid and debt funds). This often pushes a stock over 3% even when its real interest is low.

If the reported interest passes and only the assumption tips it over, the stock goes to **review**
with that reason. The annual report's "Other income" note shows the real figure. When we checked 9
such stocks against their FY26 annual reports, all 9 were under 3%.

Other methods use different limits. AAOIFI, for example, allows up to 5% non-compliant income and
measures debt against market value. The tool does not offer an AAOIFI option: the free data it reads
has no share count, so it cannot compute market value, and it will not guess. The limits are fixed in
the code (since v0.2.7): they can't be changed in Settings or in config.json.

### What do compliant, review, excluded and unknown mean?
| status | meaning | can it be traded? |
|---|---|---|
| compliant | passed every test | yes |
| review | a near miss or a business that needs a human look | no |
| excluded | failed the business screen, or a ratio by a clear margin | no |
| unknown | the data needed is missing | no |

### How do I check the halal list is right?
Compare it with stocks that Shariah-screened funds actually hold, for example the monthly portfolios of
Nippon India ETF Shariah BeES and Tata Ethical Fund:
1. Put their holdings in a CSV with a `Symbol` column (NSE symbols) in your data folder, named `trusted.csv`.
2. Ask: **"compare my halal list with trusted.csv"**.
3. The result has three groups:
   - **We say compliant, they don't:** check these first. There should be none.
   - **They say compliant, we block:** the safe side, usually the assumed-8% income test.
   - **Not in our universe:** outside the Nifty 500.

In November 2026 the automatic screen agreed with those two Shariah funds on about 81% of stocks, and
every difference was on the strict side: stocks they hold that we block, never the other way round.
Comparing is read-only: it changes nothing.

### A stock I know is halal is blocked. What do I do?
1. Ask "is SYMBOL halal?" to see which test it fails, and by how much. Usually it is the assumed 8% on
   short-term investments, which the annual report would settle.
2. The tool will still not trade it. The screen is automatic and strict on purpose, and since v0.2.7 there
   is no override: the about 19% of differences with Shariah funds are all stocks we block that they hold,
   never stocks we pass that they don't. Missing a few halal stocks costs little; trading a non-compliant
   one is the mistake this tool exists to avoid.
3. If you are sure, and your scholar agrees, you can still buy it yourself, outside the tool.

### Can I change the halal rules?
No. The TASIS limits (debt under 25% of total assets, non-compliant income under 3%, cash + receivables
under 90% of assets, an assumed 8% on short-term investments), the rule that "review" stocks are blocked,
and the Nifty 500 list are fixed in the code since v0.2.7. The Settings page shows them as a read-only
card. If `config.json` tries to change one, the tool ignores it with a `CONFIG:` line saying it "is fixed
and can't be changed". An old `halal_overrides.json` is no longer read; the daily list says so once.

### How often is the halal list updated?
Company accounts change only once a quarter, so a daily rebuild would add nothing. The daily list
**rebuilds it automatically when it is 30 days old** (about 5 minutes), and you can rebuild it any time
with "build my halal list". After each results season, and every few months, compare it with a fund's
holdings as above.

### Why no intraday, F&O or short selling?
- **Intraday:** the shares are sold before delivery (T+1), so you never take possession. The Prophet ﷺ
  said: *"Whoever buys foodstuff should not sell it until he has taken possession of it"* (Sahih
  al-Bukhari 2133, Sahih Muslim 1525). Many Hanafi scholars and Darul Iftas in the subcontinent hold
  intraday trading impermissible for this reason. Others allow it, on the view that ownership and
  constructive possession pass when the contract is made. This is a real difference of opinion, and the
  tool takes the cautious side.
- **Futures, options, short selling, margin:** most contemporary scholars hold these impermissible.
  They involve selling what you don't own, interest-bearing borrowing, or excessive uncertainty
  (gharar). See AAOIFI Shariah Standard 21 and Mufti Muhammad Taqi Usmani's writings on shares.

These rules are written into the code. They cannot be turned on from the config.

### What is purification?
Even a compliant company earns a little non-compliant income, such as bank interest. Many scholars hold
that this share of your dividend should be given to charity, and some advise doing the same for gains
as a precaution. Ask "how much should I purify for 2026?" and the tool multiplies your dividends (and
gains, if you choose) by each company's non-compliant income %. For stocks you checked in the annual
report, record dividends with the report's ratio. The ruling itself is your scholar's.

---

## Data and trading

### Where does the data come from?
All free and public. No sign-up, no API key.

| data | source |
|---|---|
| daily prices | Yahoo Finance (NSE symbols, `.NS`) |
| company finances for the halal ratios | Yahoo Finance fundamentals |
| list of companies | NSE's Nifty 500 list (niftyindices.com) |
| company announcements, insider trades, bulk deals | nseindia.com |
| news | Google News India, Moneycontrol, Economic Times Markets, Livemint |

These sources are free but unofficial, so they can lag or block automated requests. NSE often does. When
a source fails, the tool says so: insider data shows "UNKNOWN", never zero. It never fills gaps with
guesses. Check anything important in your broker app.

The tool always says who it is when it asks (`tayyib-trader/<version>` with a link to this project). It
never pretends to be a web browser to get past a site's checks.

**If niftyindices.com refuses the Nifty 500 list:** every successful download is kept in
`trader\cache\`. If the download is refused, the halal build uses that saved copy and says how old it is
(in the build notes, the daily notes and the dashboard's Halal tab). With no saved copy, it uses an
`ind_nifty500list.csv` you downloaded yourself into your data folder (`tayyib-live`). With neither, it
stops and tells you how to get it: on niftyindices.com open Nifty 500 and download the index constituents
CSV, save it as `ind_nifty500list.csv` in your data folder, and run it again. It never builds a list from
part of a file or from memory, and your existing halal list stays as it was.

### Why do news checks often say UNKNOWN?
Because NSE (and BSE) usually refuse automated requests for company announcements, and we don't get around
that: the tool asks honestly, and if the exchange says no, the check is **UNKNOWN**, not "no news". A
missing announcement could be the one that matters (new borrowing, results tomorrow), so the tool never
treats "couldn't look" as "nothing there".

What you see:
- a banner at the top of the list, for example "Exchange filings unavailable today (NSE refused automated
  access). HALAL-WATCH and results checks are incomplete for 10 of 10 stocks: check the announcements
  yourself for any stock you plan to buy.";
- in each stock's **Why?** and on the cards, two NEWS lines: **Media news** (Google News and the RSS feeds)
  and **Exchange filings (NSE)**, each naming the sources that answered and the ones that failed;
- **Check announcements yourself** links on every top pick, every ticket and in the Why panel: the stock's
  NSE company page and BSE (the BSE link opens BSE's search: press **Copy ISIN** next to it and paste it
  there). They open in your browser; the tool never reads those pages.

Before you buy, open those links and look at the last few days of announcements and any board meeting
coming up. A read-only broker API may give us announcements and results dates later.

### Why does "Exchange filings" say Not available?
Because NSE refused the tool's request. NSE blocks automated access to its announcements, and the tool
asks honestly and doesn't try to get around that. So it can't tell you whether the company filed
something, and it says so with a neutral "–" mark: **Not available: NSE blocks automated access → check
yourself**. It is never a ✓, because nobody looked.

Next to it are the stock's **NSE company page** link and **Copy ISIN** for BSE's search: open them and look
at the latest announcements and any board meeting (results) coming up.

"Not available" is different from **UNKNOWN**:
- **Not available**: NSE said no to automated requests. That's expected most days.
- **UNKNOWN**: a source that normally answers failed this time (Google News timed out, NSE returned a
  server error). Try again later or check yourself.

The **Media news** line is still checked when NSE refuses: Google News and the RSS feeds answer as usual.
This changes only what you see; a stock's PASS / WARN / BLOCK is decided as before.

### How does it pick stocks?
Every day it looks at every compliant stock that trades at least Rs 2 crore a day on average:
- **Swing setups:**
  - breakout: close to its 20-day high, in an uptrend
  - pullback: a dip to its 20-day average in an uptrend
  - oversold bounce
  - squeeze: a tight range before a move
- **Delivery setup:** a long-term uptrend near its 52-week high.

The best one per stock is planned, tested and sized. With "all" modes, it alternates swing and delivery
ideas. Rows are ranked PASS first, then WARN, then BLOCK; inside each group, see the next question. The
top 3 PASS rows are shown as **today's top picks**. A setup is a chart pattern, not a prediction.

### Why is the top pick ranked first?
Inside PASS (and inside WARN and BLOCK), stocks are ranked in two blocks:
1. Stocks whose setup has appeared **at least 8 times before** on that stock (the time machine's "past
   trades"): best time-machine expectancy first.
2. Then the rest, by **setup score** (how cleanly today's chart fits the setup).

Why: an expectancy from 1 or 2 past trades is mostly luck. Ranking by it put a stock with +2.47R from two
trades ahead of everything else. Now that number is still shown, labelled "information only (2 trades)",
but it no longer decides the order. The same order decides which tickets are sized first, so it also
decides which ones get blocked when you reach your open-positions, cash or total-risk limit.

The 8 is a setting: `daily.min_past_trades_for_rank` (0 to 50). Set it to 0 to get the old order
(expectancy only, as before v0.1.7). Lists made with the new rule are labelled `default@2` in the
tracker, so you can compare them with the older `default@1` lists.

### Why was this stock picked?
Every row of the daily list carries its reasons, recorded at the moment each check was made, with the
number measured and the limit it was compared with:
- **HALAL:** status, the three ratios (debt, reported interest and the assumed
  8% part, cash + receivables) against their limits, and the date of the accounts.
- **LIQUIDITY:** the price and the average daily traded value.
- **SETUP:** each chart condition, for example "1.2% under the 20-day high (limit 3%)".
- **NEWS:** HALAL-WATCH or results headlines in the last 72 hours (Google News, NSE announcements
  including board-meeting notices, Moneycontrol, ET Markets, Livemint). UNKNOWN if the news step didn't
  run or a source for that stock failed.
- **PLAN:** stop % against its cap, the target in R, net reward:risk against your minimum.
- **HISTORY:** the time machine's expectancy and how many past trades it is based on ("too few" under 8).
- **RISK:** each limit (loss at stop, position, cash, open positions, total risk, industry) and the final
  PASS / WARN / BLOCK with its reason.

Under each top pick, the daily list shows a short **Why:** block. The full list is in
`trader/daily/DATE.json`, or ask Claude **"why was SYMBOL picked?"**. Anything the tool did not have is
shown as UNKNOWN, never as zero.

### What do PASS, WARN and BLOCK mean?
- **PASS:** within all your limits and rules.
- **WARN:** allowed, but read the reason. For example, there's results news in the last few days (prices can jump), there's a
  HALAL-WATCH news item (new borrowing could change its halal status), or the time machine is negative.
- **BLOCK:** do not take it. For example, it would exceed your open positions, total risk, cash or loss
  limit, the plan has expired, it isn't halal, or it breaks a hard rule.

### What is "R"?
R is the amount you risk on a trade: entry price minus stop, times the number of shares. "+2R" means
you made twice what you risked, and "-1R" means the stop was hit. It lets you compare trades of any
size.

### Can I trust the time machine?
Treat it as a reality check, not a forecast. It replays the plan 10,000 times using the stock's own last
two years of daily moves, plus every past time the same setup appeared on that stock. If there are fewer
than 8 past trades, it says "too few". Results days, news and market crashes can do things the last two
years never did.

### Can I trust a backtest?
Only as a rough guide, and never as a promise. `tayyib-backtest` replays the daily list over the past
years with the same rules, your capital and real charges, and it is careful never to peek at the future.
But three things make it look better (or simply different) than real life, and every result says so:

1. **Halal status is today's.** We do not have the halal screen as it stood in 2023 or 2024, so today's
   list is applied to every past day. A company that was not halal back then (more debt, say) may have
   been "traded" anyway, and one that was halal then but not now is left out.
2. **Survivorship bias.** The list is made of companies that are still in the Nifty 500 today, so it is
   full of companies that did well enough to stay. The ones that fell out, often after a bad fall, are
   missing, and so are the losses you would have taken on them. Real results are likely worse.
3. **The past does not repeat.** A strategy can fit the last three years by luck. That is why the
   backtest splits the years: the first two thirds ("in-sample") and the last third ("out-of-sample").
   If the last third is much weaker, it says the strategy may be overfit. With fewer than 30 trades it
   says there are too few to judge.
4. **News can't be replayed.** The live list warns you about HALAL-WATCH headlines (new borrowing, a move
   into an impermissible business) and results days. We have no record of the news as it was on each past
   day, so the backtest cannot apply those checks: some trades it took, you would have been warned about.
   Every other check of the live risk step (heat, 2 per industry, reward:risk, cash and so on) is replayed.

**Recent listings (late joiners).** Some companies on today's halal list were listed on the exchange
during the years tested (HYUNDAI, SWIGGY, WAAREEENER...). The backtest lets each one in once it has a year
of prices, which is fair, but it only knows about the new listings that are still on today's list. The
ones that disappointed and dropped off are not there to lose money in the replay. That is survivorship
bias again, and it can be strong with new listings. So every result says how much of its profit came
from them ("Late joiners: N stocks, contributing X% of total P&L"). If that share is large, be careful:
`--compare` shows the same years without them in column (c), and `--no-late` runs without them.

**Small groups are noise.** The result is also split by setup (breakout, pullback, trend...) and by swing /
delivery. A group with only 10 or 15 trades can look great or terrible by luck alone: two lucky trades can
turn it from a loss into a win. Any group with fewer than 30 trades is marked "(too few to judge)": don't
switch a setup on or off because of it.

It also compares the result with simply buying and holding the Shariah ETF (Nippon India ETF Shariah
BeES) and the Nifty 50 over the same years. If holding the ETF did better, it says so: that is a real
choice you have, with much less work. The Nifty 50 is shown for reference only: it is not halal-screened
(it holds banks, for example) and counts the price only, without dividends. Not financial advice, not a
fatwa.

### Why did buying and holding beat the strategy on my stocks?
The "My stocks" backtest (v0.2.8, `--symbols` or `--holdings`) often shows "Buying and holding these same
stocks did better." That is common, and it is not a fault in the test. Three reasons:

1. **Hindsight.** You picked stocks you know today, and you know them partly because they rose. Holding a
   basket of past winners is hard to beat: the strategy steps in and out, and every exit can miss the next
   leg up. The test says so at the top ("Results are likely better than reality (hindsight)"), and the
   holding line gets the most help from it.
2. **The strategy is not always invested.** It buys only on a signal, risks about 1% of your capital per
   trade, holds at most your max open trades, and keeps the rest in cash. A basket that is always fully
   invested in rising stocks grows faster in a rising market. The strategy's case is the bad years, where
   it can stay out: look at the max drawdown next to the return.
3. **A small basket means few trades.** With under 10 stocks there are few signals, and a few trades decide
   the result ("Small basket" line). Under 30 trades a stock's row is marked "(too few to judge)".

How to read the "Your stocks" table: "better / worse" compares the strategy's P&L on a stock, as a share of
that stock's equal slice of your capital, with holding that slice for the whole window. "No trades" means
the strategy never bought it. It is a rough comparison, and the daily list is not built for it: it chooses
from all compliant stocks each day. For the honest test of the daily list, use "All halal stocks". If
simply holding a few halal stocks suits you better, that is a real choice with much less work; ask your
scholar about the stocks and your adviser about the money. Not financial advice, not a fatwa.

### How do I know if the daily list actually works?
Open `trader/tracker.xlsx`. Every stock each list showed is followed on the real prices afterwards,
using the same rules as the plan (buy only if the price reaches "buy above", stop first if both are
touched on one day, charges included). The Summary sheet gives the win rate and average R, split by
PASS / WARN / BLOCK, so you can also see whether the risk check helped. It is a paper record: nothing
is bought. A few weeks are noise, so judge it after 30 or more closed trades.

### Why is pullback on?
On its own it lost money in 5-year backtests (-0.21R over 46 trades), but switching it off made the whole
strategy worse (5-year CAGR 8.0% to 4.1%), because other trades took its place. The longer story:

On, by default. In v0.2.5 it was switched off because its own trades lost money in the 5-year backtest (46
trades, -0.21R each on average, after charges). But the whole strategy did worse without it (5-year CAGR 8.0% to
4.1%, 3 years 7.9% to 7.0%): other trades took the freed slots. So v0.2.6 put it back on. With it on, every
decision is exactly what v0.2.4 made. You can still switch it off in Settings, Setups, Pullback; check it with
`--robust-compare "pullback=on" "pullback=off"` first (see below).

### Why one backtest number isn't enough
A backtest gives one number, for example "CAGR 8.0%". That number comes from one run. Small choices that mean
nothing decide part of it: which of two equally good stocks was picked first on a busy day, or whether the test
started on a Monday or a Tuesday. Change one of those and a different trade fills a slot, the next trades
change, and the number moves. If it moves a lot, one run can't tell you whether a change to the strategy helped.

**The pullback story.** In v0.2.5 we turned the pullback setup off because, in a 5-year backtest, its own trades
lost money (46 trades, -0.21R on average). But the whole strategy then did worse: 5-year CAGR 8.0% -> 4.1%,
3-year 7.9% -> 7.0%. Its slots were taken by other trades that did worse still. Looking at one setup's own
number was misleading, so v0.2.6 put pullback back on.

Then we ran the new robustness test on the same 5 years (20 seeds each, 2026-11-06). The single run had been
unlucky in both directions. With pullback on, the median CAGR was 6.2% (8 in 10 runs between 4.5% and 7.6%), so
8.0% was near the top. With pullback off, the median was 7.2% (6.9% to 7.7%), so 4.1% was below every seeded run.
Seed by seed, "off" beat "on" in 15 of 20 runs: 75%, short of the 80% needed. The verdict was "No clear
difference", so the default stays as it has been since v0.1.7 (pullback on). The whole-strategy comparison that
reversed v0.2.5 was itself one lucky and one unlucky run. That is exactly why one number isn't enough.

**What the tool does now.** `--robust` runs the same window 20 times (up to 50) on the same prices. Each run
changes only the meaningless things: the order of signals that rank equal, and the start, moved one trading day.
It also runs max positions 3, 5 and 8. You get a range for CAGR, expectancy, max drawdown and trades (the
middle value and the band where 8 in 10 runs fall), and how often the strategy beat the Shariah ETF.

`--robust-compare "A" "B"` runs both settings with the same seeds and compares them seed by seed:

```
py tayyib-backtest/backtest.py run --years 5 --mode all --robust-compare "pullback=on" "pullback=off" --write
```

- "B is better in X of N runs": B beat A on at least 8 runs in 10.
- "B is worse in X of N runs": B lost on at least 8 in 10.
- Anything in between: "No clear difference: don't change the default on this evidence".

From v0.2.6 on, a default only changes with an 80% verdict like that. The Backtest tab shows each range as a
bar, with the verdict line and a sentence under each bar. It is still a replay of the past with today's halal
list: not a promise, not financial advice.

### Can I import the shares I already hold?
Yes: download the holdings file from Zerodha Console / Kite or Groww, save it in `trader\import\`, then
Preview and Import on the Tickets tab. It only reads the file. See the [User guide](USER_GUIDE.md#import-your-holdings-zerodha--groww).

### Why is the regime filter off by default?
Because it has to earn its place. A "don't trade when the market is falling" rule sounds sensible, but it
also skips the trades that start right at the bottom. We switch it on only if the backtest shows it helps,
on more than one window (for example both 3 and 5 years), not because it sounds right. Run
`backtest.py run --years 5 --regime-compare --write` and look at the Market regime compare table in the
Backtest tab. With the filter off, the Today header still shows the regime as information.

### What happens if a stock I hold stops being halal?
You get one alert ("No longer compliant") at the top of the list, the email and the dashboard, with the
ratios then and now, a SELL ticket you place yourself and a purification estimate. Nothing is sold for you.
See the [User guide](USER_GUIDE.md#when-a-stock-you-hold-stops-being-halal).

### Does it place orders? Can it connect to Zerodha or Groww?
No. There is no broker connection, and no code that places orders. You get a ticket with the exact steps,
and you place the order yourself. A read-only connection (to see your holdings) is on the roadmap.
Placing orders will always need your explicit yes for each one.

### Can I email the list to my friends?
No. The email is for **your own inbox** (at most 3 addresses, all yours). Sending stock picks with entry,
stop and target to other people can count as publishing research or recommendations, and in India that may
need registration with SEBI as a Research Analyst. It also changes what the list is: a tool you use for
yourself, with your capital and your settings, becomes advice to someone else, whose money and situation
the tool knows nothing about.

If friends or team members want it, each of them installs their own copy, with their own settings, and
gets their own email on their own computer. The tool is free, so that costs them nothing.

### Is my email password safe?
The password is never stored by the tool. You keep it in a Windows environment variable,
`TAYYIB_SMTP_PASSWORD` (set once with `setx`), and the tool reads it only when it sends. It is never written
to `config.json` (which refuses any password-like setting), never logged, never shown on the dashboard (only
"Password: set" or "not set") and never given to the MCP server. Use a Gmail **App Password**, not your
normal one: you can delete it any time and the email simply stops.

### Is it safe that the page can save settings?
Yes. It is built so that only you, on your computer, can do it, and only within safe limits:
- The dashboard listens on `127.0.0.1` only: other computers, and your phone, cannot reach it.
- It accepts exactly two kinds of change: saving your settings and running today's list. Everything
  else can only be read. Neither can place, change or cancel an order, and it has no broker connection.
- Each change must come from the dashboard page itself: the server checks the address, where the request
  came from and a secret code that is new every time the dashboard starts. Another website open in your
  browser cannot send one.
- Every value goes through the same check as everywhere else (allowed ranges, at least one strategy
  on). The halal rules, charges and the rest of the advanced settings can't be changed from the page. Anything invalid is refused and nothing is partly saved.
- Before saving it shows you every change, it keeps a backup of your old settings (the last 20), and you
  can restore any of them.
- The rules that keep it halal and cash-only (CNC only, no short selling, no F&O, no margin, compliant
  stocks only, your yes for every order) are in the code, not in the settings.

### How accurate are the charges?
For Zerodha delivery, they match Zerodha's published rates to the paisa: STT, NSE transaction charge,
SEBI fee, stamp duty, GST and DP charge. For Groww, the brokerage is set to 0.1% (minimum Rs 5, maximum
Rs 20 per order). Rates change, so check your broker's charges page now and then. The charges are fixed in the code (they
are not settings since v0.2.7); a new release updates them when the rates change.

### When should I run it?
After 3:30 PM IST on a trading day, once the day's prices are final. If you run it during market hours it
still works, but it warns you that the levels can change (the dashboard's **Run today's list** button asks
first). You can schedule it: see the
[User guide](USER_GUIDE.md#part-3-optional-run-it-automatically-every-day).

### Where is my data stored? Is it private?
In the `trader/` folder in your own data folder, on your computer. Nothing is uploaded. The only network
requests are to the public data sources above, and there are no broker logins or keys.

### Is it free?
Yes. It is MIT-licensed open source: free to use, change and share. You need Python, and Claude Code
if you want to talk to it instead of typing commands.
