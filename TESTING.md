# Testing tayyib-trader on live data

The unit tests (`python3 -m unittest discover -s tests`) are offline and use synthetic data. This
guide checks the parts the offline tests can't reach: the real Yahoo, NSE and news endpoints, the
skills inside Claude Code, and the MCP server in a real client. Run it on your own machine. It
places no orders and needs no broker login.

Budget about 30 minutes. Write down anything that fails in the report template at the end.

## 0. Setup

```bash
git clone https://github.com/R12Wan-Pat3l/tayyib-trader.git
cd tayyib-trader
python3 --version                                 # 3.8 or newer
# Windows: if python3/python open the Microsoft Store, use `py` instead everywhere below
python3 -m unittest discover -s tests             # expect: Ran 82 tests ... OK
mkdir -p ~/tayyib-live && cd ~/tayyib-live        # your data folder; trader/ is created here
export T=~/tayyib-trader                          # wherever you cloned it (Windows: set T=...)
```

## 1. Prices (Yahoo)

```bash
python3 $T/tayyib-scanner/scan.py --help >/dev/null && python3 -c "
import sys; sys.path.insert(0, '$T/core'); import tayyib_core as tc
b, m = tc.get_daily_bars('TCS'); print(len(b), b[-1], m.get('currency'))"
```

Expect about 490 bars for 2 years, with the last date being the latest trading day and the currency INR.
If you get HTTP 429, wait a minute and try again. If the request fails outright, Yahoo may have changed its endpoint, so open an issue.

## 2. Halal universe

```bash
python3 $T/tayyib-halal/halal.py build --limit 40          # quick: first 40 of the Nifty 500
python3 $T/tayyib-halal/halal.py check TCS,ITC,HDFCBANK,ASIANPAINT,UNITDSPR
```

Expect ITC, HDFCBANK and UNITDSPR to be `excluded` (tobacco, finance, alcohol), and large IT companies to be `compliant`
unless their data is missing. Then compare 5 to 10 of the `compliant` stocks against a Shariah list
you trust, such as the NSE Nifty 500 Shariah factsheet or a TASIS-based app, and note any disagreements.
Those mismatches are the most useful thing you can report.

If the Nifty 500 CSV download fails (niftyindices.com sometimes blocks scripts), download it in your
browser and run `halal.py build --parent ind_nifty500list.csv`.

Full build, which makes about 500 requests and takes 4 to 6 minutes: `python3 $T/tayyib-halal/halal.py build`

## 3. Scanner, news, entry, exit

```bash
python3 $T/tayyib-scanner/scan.py --mode all --top 15
python3 $T/tayyib-news/news.py --market
python3 $T/tayyib-entry/entry.py check <a symbol from the scan>
python3 $T/tayyib-exit/exit.py plan <same symbol> --write
```

Check these:
- Every candidate is `compliant` in `halal.py list --status compliant`.
- Each setup is visible on a real chart (Kite or TradingView): the trigger is just above a recent high, and the invalidation is under a recent low.
- News times are in IST and the headlines are about the right company. Note any sources listed as failed.
- Run during market hours (9:15 AM to 3:30 PM IST), `entry.py check` also uses the live price.

## 4. Time machine, budget, risk, ticket

```bash
python3 $T/tayyib-timemachine/timemachine.py run --write
cp $T/config.example.json trader/config.json      # then edit capital / risk / broker
python3 $T/tayyib-budget/size.py --write
python3 $T/tayyib-risk/check.py
python3 $T/tayyib-broker/ticket.py show
```

Check these:
- The time machine finishes in a few seconds, and the probabilities add up to about 100%.
- Charges: for one order, compare `buy_charges_rs` (from `size.py --json`) with your broker's brokerage calculator.
- Risk: change `max_risk_per_trade_rs` to 10 in `trader/config.json` and rerun. Every order should BLOCK.
- The ticket steps match what you see in Kite or Groww. Note any button or menu names that are wrong.

## 5. Research and insider

```bash
python3 $T/tayyib-results/results.py TCS
python3 $T/tayyib-insider/insider.py TCS --days 180
```

Compare one quarter's revenue and net profit with the result on NSE or BSE. Yahoo usually gives consolidated figures but does not label them. Growth is matched by date, so a quarter missing from the feed shows `-` rather than a wrong number.

NSE often answers scripts with HTTP 403, depending on the network and time of day. The insider tool then says UNKNOWN (not zero), and news falls back to Google News and the RSS feeds. Try again later or from another network (a phone hotspot often works).

## 6. Skills in Claude Code

```
/plugin marketplace add R12Wan-Pat3l/tayyib-trader
/plugin install tayyib-trader@tayyib-trader
```

Then, in your data folder, ask Claude:
1. "Build my halal universe from the first 50 Nifty 500 stocks"
2. "Scan for halal swing setups"
3. "Plan the best one, replay it in the time machine, size it for 2 lakh capital, and check the risk"
4. "Give me the ticket"

Expect Claude to stop at the ticket and ask whether you want to place it. Also ask "buy NIFTY options for me" and
"short ITC". It should refuse both, and the risk check should block them.

## 7. MCP in Claude Desktop (or Cursor)

Add the block from the README with your real paths, restart the app, and ask: "Use tayyib-trader to check
whether TCS and ITC are halal". You should see 16 tools listed, and none of them place orders.

## Report template

```
OS / Python:
1 prices:      ok / fail (error)
2 halal:       mismatches vs <your trusted list>:
3 scan/news:   failed sources:
4 charges:     ours Rs __ vs broker calculator Rs __
5 results:     consolidated or standalone? matches filing?
6 Claude Code: stopped at ticket? refused F&O / short?
7 MCP:         tools visible?
```

Open an issue with this report, or paste it into a Claude chat to get the fixes made.
