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
- [Does it place orders? Can it connect to Zerodha or Groww?](#does-it-place-orders-can-it-connect-to-zerodha-or-groww)
- [How accurate are the charges?](#how-accurate-are-the-charges)
- [When should I run it?](#when-should-i-run-it)
- [Where is my data stored? Is it private?](#where-is-my-data-stored-is-it-private)
- [Is it free?](#is-it-free)

---

## Halal screen

### What makes a stock "halal" in this tool?
Three checks, in order:
1. **Business screen:** is the company's main business permissible?
2. **Financial screen:** three ratios from its latest annual accounts (TASIS method, the same one
   NSE uses for its Nifty Shariah indices).
3. **Your overrides:** your own (or your scholar's) ruling on any stock, which always wins.

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
measures debt against market value. You can change the thresholds in your config.

### What do compliant, review, excluded and unknown mean?
| status | meaning | can it be traded? |
|---|---|---|
| compliant | passed every test (or you approved it) | yes |
| review | a near miss or a business that needs a human look | no, unless you allow review stocks or approve that one |
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

In November 2026 the automatic screen agreed on 81% of stocks, and every difference was on the strict
side. That rose to 94.8% after checking 8 of the differences in their annual reports.

### A stock I know is halal is blocked. What do I do?
1. Ask "is SYMBOL halal?" to see which test it fails, and by how much.
2. Check the annual report, a Shariah fund's holdings, or ask your scholar.
3. If you agree it is compliant, record it: **"override SYMBOL as compliant, note: <your source>"**.

Overrides are kept when the list is rebuilt. To undo one: "clear the override for SYMBOL". It works
the other way too: you can exclude a stock that the screen passes.

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

### How does it pick stocks?
Every day it looks at every compliant stock that trades at least Rs 2 crore a day on average:
- **Swing setups:**
  - breakout: close to its 20-day high, in an uptrend
  - pullback: a dip to its 20-day average in an uptrend
  - oversold bounce
  - squeeze: a tight range before a move
- **Delivery setup:** a long-term uptrend near its 52-week high.

The best one per stock is planned, tested and sized. With "all" modes, it alternates swing and delivery
ideas. Rows are ranked PASS first, then by time-machine expectancy. The top 3 PASS rows are shown as
**today's top picks**. A setup is a chart pattern, not a prediction.

### What do PASS, WARN and BLOCK mean?
- **PASS:** within all your limits and rules.
- **WARN:** allowed, but read the reason. For example, results are due (prices can jump), there's a
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

### Does it place orders? Can it connect to Zerodha or Groww?
No. There is no broker connection, and no code that places orders. You get a ticket with the exact steps,
and you place the order yourself. A read-only connection (to see your holdings) is on the roadmap.
Placing orders will always need your explicit yes for each one.

### How accurate are the charges?
For Zerodha delivery, they match Zerodha's published rates to the paisa: STT, NSE transaction charge,
SEBI fee, stamp duty, GST and DP charge. For Groww, the brokerage is set to 0.1% (minimum Rs 5, maximum
Rs 20 per order). Rates change, so check your broker's charges page now and then.

### When should I run it?
After 3:30 PM IST on a trading day, once the day's prices are final. If you run it during market hours it
still works, but it warns you that the levels can change. You can schedule it: see the
[User guide](USER_GUIDE.md#part-3-optional-run-it-automatically-every-day).

### Where is my data stored? Is it private?
In the `trader/` folder in your own data folder, on your computer. Nothing is uploaded. The only network
requests are to the public data sources above, and there are no broker logins or keys.

### Is it free?
Yes. It is MIT-licensed open source: free to use, change and share. You need Python, and Claude Code
if you want to talk to it instead of typing commands.
