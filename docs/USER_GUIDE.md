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

### Your dashboard (in the browser)
Everything above, on one page in your browser. It cannot buy or sell anything, and it runs on your own
computer only (nobody else can open it). The only two things it can change are your settings (the
Settings tab) and today's list (the **Run today's list** button), both explained below.

**Open it on Windows:**
- In Claude Code (in your `tayyib-live` folder), ask: **"Show my dashboard"**. Your browser opens
  `http://127.0.0.1:8765/`.
- Or without Claude: open Command Prompt, then
  ```
  cd %USERPROFILE%\tayyib-live
  py C:\Code\Trader\tayyib-trader\tayyib-dashboard\dashboard.py
  ```
  (use the folder where you cloned or installed tayyib-trader). Leave that window open while you use the
  dashboard; press **Ctrl+C** in it to stop. If the port is busy, add `--port 8800`.

**What each tab means:**
On a phone the tabs are at the bottom of the screen.
- **Today:** the date and your numbers at the top (capital, risk per trade, how many stocks were scanned,
  how many PASS, WARN and BLOCK). Yellow banners say when the list is old or was made before 3:30 PM, or
  when a news source failed (then HALAL-WATCH and results checks are incomplete). The top picks are
  cards: the bar shows the stop, the buy-above price and the target with how many R each is, and the
  small chart is the last 60 days. Below is the full list: click a column to sort, filter by PASS / WARN /
  BLOCK or swing / delivery, and press **Why?** on any row: a panel opens with every check, ✓ (passed),
  ✗ (failed) or UNKNOWN (no data), and news headlines in full. "stop capped" means the chart's stop was
  further away than your maximum stop %, so the cap was used. "near halal limit" means a ratio is within
  10% under its limit; "over limit" means it is at or over it (you will only see that on a stock you
  marked compliant yourself, with an override). "This list was made with" shows the settings of that
  list; "Current settings" (top right) shows yours now.
- **Results:** win rate, average R and total R ("no closed trades" until one closes), a ring counting
  closed trades towards 30 (until then: "still noise: don't judge yet"), the equity curve (your running
  total in R), and every earlier pick: TARGET = right, STOP = wrong, NOT TRIGGERED = no trade, TIME EXIT =
  right or wrong by the result, WAITING / OPEN = pending. "Triggered (paper)" is the day the price reached
  the buy-above level on paper: nothing was bought. **Chart** opens the price with the buy, stop and
  target lines. The summary splits results by check, mode, setup and settings.
- **Halal:** a ring of compliant / review / excluded / unknown, then the compliant stocks first (change
  the Status filter to see the rest). Each ratio is a small bar against its limit with the words "within
  limit", "near limit" or "over limit". Press **Ratios** for the details, reported interest next to the
  assumed 8% part, your override with its note and date, and the reasons. Stocks excluded for their
  business say "not checked (business excluded)": their ratios were never needed. Review and excluded
  stocks are listed for their status only.
- **Tickets:** PASS and WARN tickets you haven't placed yet, with **Copy** buttons for the Kite and Groww
  steps (they say "Copied ✓"), then the blocked ones folded away under "Blocked (not tickets)", then your
  open and closed positions. Copying is the only thing the buttons do: you still place every order yourself.

- **Settings:** change your numbers in the browser. See [Changing your settings](#changing-your-settings).

If a stock's halal status has changed since a list was made, that row only says "halal status changed
since this list: re-check", without prices.

### Run from the dashboard
On the Today tab, press **Run today's list**. It runs the same thing as asking Claude for today's list, on
your computer, with your data folder. You can tick **Skip news** to make it faster (the HALAL-WATCH and
results checks are then not done for today). A panel shows the progress; you can close it and the run
goes on. Only one run at a time.

- Before 3:30 PM IST on a weekday, or on a market holiday in your settings, it asks first: "Prices aren't
  final yet, levels may change". You can still run it.
- When it finishes, the Today tab shows the new list.
- If it fails, the panel shows the error and your old list stays as it was: nothing half-written.
- It never places an order. You still place every order yourself.

If you run it twice on one day with different settings, the tracker keeps the first run's unfilled picks
as **SUPERSEDED** (greyed in Results, "not counted") and follows the new ones. Picks that had already
reached their buy price are never touched.

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

Your settings live in `tayyib-live\trader\config.json`. Anything you don't set keeps its default. There
are two easy ways to change them:

**In the dashboard (Settings tab).** Every setting is listed by group (Risk, Plan, Selection, Broker &
charges, Halal), with its default, its allowed range and its unit. Move a slider or type a number:
- a changed value is marked **changed**, with **Reset** to go back to the default;
- a value outside its range is marked in red at once, with the reason;
- on the right (below, on a phone), **What this means in rupees** shows your loss per trade and after 3, 5
  and 10 losses in a row, with a warning above 2% a trade;
- **Review & save** lists every change (old → new) first. Nothing is saved until you press **Save
  settings**. Then it says "Changes apply from the next run."

Every save keeps a copy of your old `config.json` in `trader\config_backups\` (the last 20). Under
**Backups** you can see what each one would change and restore it, the same safe way.

**Back to the defaults.** Each field has **Reset**, each group has **Reset this section**, and the top of
the page has **Reset all to defaults**. "Reset all" keeps your capital and broker (they are facts about
you, not strategy) unless you tick **Also reset capital and broker**. Resetting Halal puts back the TASIS
limits, turns "review" stocks off and clears your source / scholar note. A reset only changes the form:
nothing is saved until you press **Review & save** and confirm, and the old settings are kept as a backup,
so you can undo it from **Backups**. After a full reset your settings code is `default@2`, even if you kept
your own capital and broker (the page tells you it kept them).

The rules that keep it halal and cash-only are shown under **Always on**: they are not settings, and the
page cannot switch them off.

**By asking Claude**, for example: **"set my risk per trade to 0.5%"** or **"turn off the squeeze
setup"**.

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
`loosen_note` (in the dashboard: the **Source / scholar** box); without it the tool refuses and keeps the
TASIS limits, and the dashboard will not save. With it, every daily list starts
with a line saying the thresholds are looser than TASIS, and why. See the [FAQ](FAQ.md#can-i-loosen-the-halal-thresholds).

Every daily list records a short code for the settings it used: `default@2` when you changed nothing
(your own capital and broker don't count),
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
