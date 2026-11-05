# User guide (no coding needed)

This guide takes you from nothing to your first daily halal list, then shows the routine. It uses
**Claude Code** on Windows. Mac and Linux are the same, with `python3` in place of `py`.

Nothing in this tool can place an order. You always place it yourself, after you decide.

---

## Part 1: One-time setup (about 20 minutes)

### 1. Install Python
1. Go to https://www.python.org/downloads/ and download Python 3 (any 3.8 or newer).
2. Run the installer. On the first screen, tick **"Add Python to PATH"**, then click Install.
3. Open **Command Prompt** and type `py --version`. You should see `Python 3.x.x`.

### 2. Install Claude Code
Follow https://claude.com/claude-code and sign in with your Claude account.

### 3. Make a folder for your trading data
In Command Prompt:
```
mkdir %USERPROFILE%\tayyib-live
cd %USERPROFILE%\tayyib-live
claude
```
Everything the tool saves (your halal list, plans, journal) stays in this folder on your computer.

### 4. Add the tool to Claude Code
Inside Claude Code, type these two lines (one at a time):
```
/plugin marketplace add R12Wan-Pat3l/tayyib-trader
/plugin install tayyib-trader@tayyib-trader
```
Then close and reopen Claude Code (in the same folder).

### 5. Set your own numbers
Ask Claude: **"Create my tayyib config: capital 1,00,000, risk 1% per trade, broker Zerodha"**
(use your real numbers, and Groww if that's your broker).

The important settings:
| setting | default | meaning |
|---|---|---|
| capital | 1,00,000 | money set aside for trading |
| risk per trade | 1% | the most you lose on one trade (Rs 1,000 on 1 lakh) |
| max position | 20% | the most you put in one stock |
| max open positions | 6 | how many trades at once |
| broker | zerodha | `zerodha` or `groww` (sets the charges) |

### 6. Build your halal list (first time only)
Ask: **"Build my halal stock list"**. It checks about 500 companies and takes about 5 minutes.
After this, the daily list refreshes it automatically every 30 days.

---

## Part 2: Every trading day (about 5 minutes)

1. **After 3:30 PM**, open Claude Code in your `tayyib-live` folder and ask:
   **"Give me today's halal list"**
2. Read the **top picks** and the table. Read every WARN and BLOCK reason.
   - No picks today is normal. Not trading is also a decision.
3. For a stock you like, ask: **"Show me the ticket for SYMBOL"**. You get the exact Kite or Groww steps.
4. If you decide to take it, **place it yourself** in Kite or Groww:
   - Buy, **CNC** (delivery), order type SL or GTT at the entry price.
   - When it fills, add the **stop-loss and target** (in Kite: GTT, OCO).
5. Tell Claude your fill: **"I bought SYMBOL at 1004.50"**. It records it in your journal.

### Check how the earlier picks did (the Excel tracker)
Every daily list is recorded automatically and followed on the real prices after that. Open
**`tayyib-live\trader\tracker.xlsx`** in Excel:
- **Tracker** sheet: one row per pick, showing buy above, stop, target, then what happened. The Status
  column is WAITING, NOT TRIGGERED, OPEN, TARGET, STOP, BREAKEVEN or TIME EXIT, followed by the bought
  date, exit date and Result R.
- **Summary** sheet: win rate and average result, split by PASS / WARN / BLOCK, by swing / delivery and by setup.
- The bottom of each daily list also shows "How earlier lists did".

Or ask Claude: **"How did yesterday's picks do?"**. This is paper only: nothing is bought. Judge it after
30 or more closed trades, not after a few days.

### While you hold a trade
- **"Check my alerts"**: tells you if a stop, target or time limit was hit.
- **"I sold SYMBOL at 1064"**: records the sale, with profit after charges.
- **"Show my positions"**: your open and closed trades and how you're doing.

### Once a month
- The halal list refreshes itself (when it's 30 days old).
- Every few months, compare it with a Shariah fund's holdings: see the [FAQ](FAQ.md#how-do-i-check-the-halal-list-is-right).

### Once a year
- **"How much should I purify for 2026?"**: the charity amount from your dividends.

---

## Part 3 (optional): Run it automatically every day

You can have Windows make the list at 3:45 PM every weekday, without opening Claude.

1. Get a fixed copy of the tool (the plugin's own folder can move when it updates). In Command Prompt:
   ```
   git clone https://github.com/R12Wan-Pat3l/tayyib-trader.git C:\tayyib-trader
   ```
   (No git? On the GitHub page click **Code, Download ZIP** and unzip it to `C:\tayyib-trader`.)
   Once a month run `git -C C:\tayyib-trader pull` to get updates.
2. Open **Task Scheduler** (search for it in the Start menu), then **Create Basic Task**.
3. Name: `tayyib daily`. Trigger: **Weekly**, Monday to Friday, **3:45 PM**.
4. Action: **Start a program**.
   - Program: `py`
   - Arguments: `C:\tayyib-trader\tayyib-daily\daily.py`
   - Start in: `C:\Users\YOUR-NAME\tayyib-live`
5. Finish. Each day the list is saved as `tayyib-live\trader\daily\YYYY-MM-DD.md`. Open it in Notepad,
   or ask Claude "show me today's list".

On an NSE holiday there is no new price data, so it repeats the previous day's list. Add holidays to your config (`"holidays": ["YYYY-MM-DD", ...]` from NSE's holiday list) so the plan dates ("valid until" and the time stop) skip them.

---

## Changing your settings

Your settings live in `tayyib-live\trader\config.json`. Ask Claude, for example: **"set my risk per
trade to 0.5%"** or **"turn off the squeeze setup"**. Anything you don't set keeps its default.

**Risk per trade is not the stop.** They are two different things:
- The **stop** is how far the price may fall before you sell (for example 5% under your buy price).
  The plan sets it from the chart.
- **Risk per trade** is how much *money* you lose if that stop is hit (1% = Rs 1,000 on Rs 1 lakh).
  The tool picks the number of shares so the loss at the stop is that amount.

So a wider stop means *fewer shares*, not a bigger loss. With 1% risk on Rs 1 lakh:
- a 10% stop buys about Rs 10,000 of a stock: if the stop is hit, you lose Rs 1,000;
- a 5% stop buys about Rs 20,000: still Rs 1,000;
- a 2% stop would allow Rs 50,000, but the 20% max position caps it at Rs 20,000, so you risk only Rs 400.

**Losing streaks happen.** Ask **"show my risk preview"** to see what your numbers mean. With 1% risk:

| losses in a row | your capital is down |
|---|---|
| 3 | 2.97% |
| 5 | 4.90% |
| 10 | 9.56% |

At 2% risk, 10 losses in a row cost 18.3%; at 3% (the highest allowed) 26.3%. Pick a risk you could
live with after ten losses.

**What you can change, and the safe ranges:**

| setting | default | allowed |
|---|---|---|
| risk per trade | 1% | 0.25% to 3% |
| max in one stock | 20% | 5% to 40% |
| max open trades | 6 | 1 to 20 |
| max total risk (heat) | 6% | 1% to 15% |
| least reward:risk | 1.5 | 1 to 5 |
| swing stop at most | 10% | 2% to 10% |
| delivery stop at most | 15% | 3% to 15% |
| least daily traded value | Rs 2 crore | at least Rs 50 lakh |
| each setup | on | on or off, with its own thresholds |

If a value is outside its range, or a name is misspelt, the tool uses the default for that one setting
and tells you, in a line that starts with `CONFIG:` at the bottom of the daily list. Nothing changes
silently.

**What you cannot change:** delivery (CNC) only, no intraday, no F&O, no short selling, no margin, and
only halal-compliant stocks. These are rules in the code, not settings.

**Halal thresholds.** You may make them stricter (for example debt under 20%) at any time. To make them
*looser* than TASIS, you must write down who says so (your scholar or the method you follow) in
`loosen_note`; without it the tool refuses and keeps the TASIS limits. With it, every daily list starts
with a line saying the thresholds are looser than TASIS, and why. See the [FAQ](FAQ.md#can-i-loosen-the-halal-thresholds).

Every daily list records a short code for the settings it used: `default@1` when you changed nothing,
otherwise a code such as `b1d996bb` that stands for your changes. The Excel tracker's Summary sheet
splits the results by that code, so after a change you can see whether the new
settings did better or worse.

---

## Before real money

Let the Excel tracker run for 4 to 6 weeks: it follows every pick for you, without any money. Check the
Summary sheet, especially the PASS rows. If you also want to practise yourself, record your own trades
with "I bought" / "I sold", without putting money in. Then ask **"show my positions"** and look at your real win rate and average R.
The time machine shows past odds; your own journal shows whether *you* can follow the plan.

## Something not working?

| problem | fix |
|---|---|
| `py` not found | Reinstall Python with "Add Python to PATH" ticked |
| `python3` opens the Microsoft Store | Normal on Windows: the tool uses `py` |
| "NSE did not answer" / HTTP 403 | NSE sometimes blocks scripts. Insider data shows UNKNOWN; everything else still works |
| A stock you know is halal is blocked | See the [FAQ](FAQ.md): you can check it and record your ruling |
| Anything else | Open an issue: https://github.com/R12Wan-Pat3l/tayyib-trader/issues |

Never post your broker login, API keys or account numbers anywhere.
