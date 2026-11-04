# Getting started (no coding needed)

This guide is for anyone you share tayyib-trader with. Pick **one** of the three ways below.
All three are free. None of them can place an order: you always place it yourself in your broker app.

Before you start you need:
- a computer (Windows, Mac or Linux)
- **Python 3.8 or newer**: download from https://www.python.org/downloads/ . On Windows, tick
  **"Add Python to PATH"** on the first screen of the installer.
- for Way A or B: a Claude account (https://claude.ai)

Check Python works: open **Terminal** (Mac/Linux) or **Command Prompt** (Windows) and type
`python3 --version`. On Windows, if that opens the Microsoft Store, type `py --version` instead and
use `py` wherever this guide says `python3`. You should see `Python 3.x.x`.

---

## Way A: Claude Code (easiest to talk to)

1. Install Claude Code: https://claude.com/claude-code
2. Make a folder for your trading data, open a terminal in it, and start Claude Code:
   ```
   mkdir my-trading
   cd my-trading
   claude
   ```
3. Inside Claude Code, add the skills (one time only):
   ```
   /plugin marketplace add R12Wan-Pat3l/tayyib-trader
   /plugin install tayyib-trader@tayyib-trader
   ```
4. Now just talk to it in plain English (or Hinglish):
   - **"Give me today's halal list"** (every trading day after 3:30 PM; this is the main one)
   - "Build my halal stock list" (first time; takes a few minutes)
   - "Scan for halal swing setups"
   - "Is ASIANPAINT halal?"
   - "Plan the best one, test it in the time machine, and size it for 1 lakh capital"
   - "Check the risk and give me the ticket"
   - "I bought ALFA at 1004.50" / "I sold ALFA at 1064" / "Show my positions"
   - "How much should I purify from my dividends this year?"

Claude will stop at the ticket and ask you. You place the order in Kite or Groww yourself.

## Way B: Claude Desktop app (or Cursor, or any MCP app)

1. Download the code: on https://github.com/R12Wan-Pat3l/tayyib-trader click the green **Code**
   button, then **Download ZIP**, and unzip it somewhere you'll remember (for example `Documents`).
2. Make a folder for your data, for example `Documents/my-trading`.
3. In Claude Desktop open **Settings, Developer, Edit Config** and paste this (change the two paths
   to your real folders; on Windows use `py` and paths like `C:\\Users\\you\\Documents\\...`):
   ```json
   {
     "mcpServers": {
       "tayyib-trader": {
         "command": "python3",
         "args": ["/Users/you/Documents/tayyib-trader-main/mcp/server.py"],
         "env": { "TAYYIB_DIR": "/Users/you/Documents/my-trading/trader" }
       }
     }
   }
   ```
4. Restart Claude Desktop. Ask: "Use tayyib-trader to check if TCS and ITC are halal."

## Way C: no AI, just the commands

1. Download and unzip as in Way B, step 1.
2. Open a terminal in your data folder and run the steps one by one (replace `T` with the path to
   the unzipped folder; on Windows use `py` instead of `python3`):
   ```
   python3 T/tayyib-halal/halal.py build
   python3 T/tayyib-scanner/scan.py --mode swing
   python3 T/tayyib-exit/exit.py plan SYMBOL --write
   python3 T/tayyib-timemachine/timemachine.py run --write
   python3 T/tayyib-budget/size.py --write
   python3 T/tayyib-risk/check.py
   python3 T/tayyib-broker/ticket.py show
   ```
   Every command explains itself with `--help`.

---

## Set your own numbers (do this once)

Copy `config.example.json` into the `trader` folder inside your data folder, rename it
`config.json`, and edit:
- `capital`: your trading money, in rupees
- `max_risk_per_trade_pct`: how much you accept losing on one trade (1 means 1% of capital)
- `broker`: `zerodha` or `groww`

## Good habits

- Rebuild the halal list every month and after results season: "Rebuild my halal list".
- Place the stop-loss (GTT) in your broker app as soon as a buy fills.
- Treat every result as a second opinion, not a signal. Not financial advice, not a fatwa.

## Stuck?

Open an issue: https://github.com/R12Wan-Pat3l/tayyib-trader/issues (click **New issue**, choose
**Bug report**). Never post your broker login, API keys, or your account numbers.
