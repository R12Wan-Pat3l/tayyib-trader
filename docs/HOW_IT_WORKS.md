# How tayyib-trader works

## In one minute (for everyone)

Think of it as a careful assistant who does your homework every evening:

```
1. Halal filter      Which of the Nifty 500 companies are Shariah-compliant?        (once a month)
2. Chart scan        Which of those have a good-looking chart today?
3. News              Anything in the news that changes the picture?
4. Plan              Buy above X, sell if it falls to Y, take profit at Z.
5. Time machine      How did this kind of trade do on this stock in the past?
6. Size              How many shares, so you lose at most 1% if it goes wrong?
7. Safety check      Does it break any of your limits or rules?  PASS / WARN / BLOCK
8. Ticket            The exact steps to place it in Zerodha or Groww. YOU decide and place it.
9. Tracker           Every later day: did each earlier pick reach its buy price, then target or stop?
                     Saved in Excel (trader/tracker.xlsx).
```

Steps 1 to 7 and 9 run automatically when you ask for **today's halal list**. Step 8 is always yours.

**What a row in the list means**

| column | meaning |
|---|---|
| entry | buy only if the price rises to this (a "buy-stop"), within the next few days |
| stop | if it falls to this after you buy, sell: this is your maximum loss |
| target | where you plan to take profit |
| qty | how many shares to buy |
| risk Rs | what you lose, including charges, if the stop is hit |
| time machine | how this plan did on the stock's past data, in R (1R = the amount you risk) |
| check | PASS (fine), WARN (fine but read the warning), BLOCK (do not take it) |

**What it never does:** buy or sell for you, trade intraday or F&O, short sell, use margin, or show a
stock that failed the halal screen.

## Two trade styles

- **Swing:** hold for days to a few weeks (up to 20 trading days). Stop at most 10% below the buy price.
- **Delivery:** hold for months. Stop at most 15% below. Reviewed at the target rather than sold automatically.

Both are CNC (delivery) trades: the shares come into your demat account. See the [FAQ](FAQ.md) for why
intraday is left out.

## For developers: what happens underneath

Every step is a small Python script (standard library only) in its own folder, `tayyib-*/`. They talk
to each other through JSON files in a `trader/` folder in your working directory:

```
tayyib-halal      -> trader/halal_universe.json   (+ your trader/halal_overrides.json)
tayyib-scanner    -> trader/scan.json
tayyib-news       -> trader/news.json
tayyib-exit       -> trader/plan.json
tayyib-timemachine-> trader/sim.json
tayyib-budget     -> trader/orders.json
tayyib-risk       -> statuses in trader/orders.json, trader/risk.json
tayyib-broker     -> trader/positions.json (your journal)
tayyib-tracker    -> trader/tracker.json, trader/tracker.xlsx, trader/tracker.csv
tayyib-daily      -> runs all of the above, writes trader/daily/DATE.md and .json
```

Each skill has a `SKILL.md` that tells Claude when and how to run it, and `AGENTS.md` does the same
for other AI tools. `mcp/server.py` exposes the same tools to any MCP app. Shared code lives in
`core/tayyib_core.py` and is copied into each folder so every skill also works on its own.
Details: [Technical guide](TECHNICAL.md).
