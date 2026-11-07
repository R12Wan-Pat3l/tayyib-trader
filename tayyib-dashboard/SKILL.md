---
name: tayyib-dashboard
description: >-
  Local Dashboard. Opens a page in the user's browser on 127.0.0.1 over their trader/
  files: Today (the daily list, top picks, every row's Why with ✓ / ✗ / UNKNOWN), Results (the paper
  tracker with price charts and an equity curve), Halal (ratios against the limits) and
  Tickets (Kite / Groww steps to copy, the positions journal) and Settings (edit config.json safely,
  with a risk preview and backups). A "Run today's list" button runs tayyib-daily. Places no order.
  Use when the user says "show my dashboard", "open the dashboard", "show it in the browser".
argument-hint: "[--port 8765] [--no-browser]"
---

# tayyib-dashboard

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same command from the repo root as `python3 tayyib-dashboard/dashboard.py`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, the port is busy), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

Run it from the folder where the user keeps their data (the one that holds `trader/`), or set `TAYYIB_DIR`:

```bash
python3 "${CLAUDE_SKILL_DIR}/dashboard.py"               # opens http://127.0.0.1:8765/
python3 "${CLAUDE_SKILL_DIR}/dashboard.py" --port 8800 --no-browser
```

It keeps running until the user presses Ctrl+C (run it in the background and tell them the URL).
It needs the other tayyib skills next to it (it reuses tayyib-tracker's summary, the same numbers as
the Excel Summary sheet).

What each tab shows:
- **Today:** the list for a date, with a banner when it is stale (not today's, or written before
  3:30 PM IST) or when a news source failed; top-pick cards; the full table (sort, filter by check and
  mode); a "Why?" drawer per row (a bottom sheet on a phone). Capped stops and halal ratios near or over
  a limit are marked.
- **Results:** every tracked pick with a labelled verdict (TARGET = right, STOP = wrong, NOT TRIGGERED =
  no trade, TIME EXIT by the sign of R, OPEN / WAITING = pending), a price chart per pick, the summary
  by check, mode, setup and settings label, and the equity curve. Until 30 trades have closed it says
  "still noise: don't judge yet".
- **Halal:** the universe (compliant first) with search and a status filter, ratio gauges against the
  limits (within / near / over), reported vs assumed-8% income, "not checked (business excluded)". Review and excluded
  stocks are shown for their status only.
- **Tickets:** PASS / WARN tickets first with the Kite / Groww steps (Copy buttons only), blocked ones
  folded under "Blocked (not tickets)", and the positions journal.
- **Settings (v0.2.7, simple):** Money & risk (capital, risk per trade, max position, max open trades),
  Broker (Zerodha or Groww; charges from the built-in tables), Strategies (five switches, at least one on)
  and Holidays, each with its default, range, a "changed" marker and Reset; a live risk preview in rupees;
  a read-only Halal card ("These rules can't be changed in the app."); a review of the changes before
  saving; restore from the last 20 backups in `trader/config_backups/`. The hard rules are shown as
  "Always on". Advanced keys changed in config.json are listed, not editable.
- **Run today's list** (Today tab): runs `tayyib-daily` on this computer with the same data folder, one run
  at a time, with its output live. Before 3:30 PM IST it asks first ("Prices aren't final yet").
  When it ends, the Today tab reloads; a failure shows the error and leaves the old list.

Every row and ticket is checked against the halal list **now**: a stock that is no longer compliant
shows "halal status changed since this list: re-check" and no levels.

Rules:
- It listens on 127.0.0.1 only. It answers GET / HEAD, plus exactly two POSTs: `/api/config` (save
  settings) and `/api/run` (run tayyib-daily). Each POST needs the right Host and Origin, the page's
  per-start token and a small JSON body. There is no button that places, changes or cancels an order; the user places every order themselves in their broker app after an
  explicit yes, and records it with `tayyib-broker placed`.
- Missing data is shown as UNKNOWN, a missing price series as "price data unavailable", never 0 and
  never a guessed line.
- Settings are checked by `tc.validate_config` (the same check every skill uses) before anything is
  written; invalid values are refused and nothing is partly saved. Changes apply from the next run.

Not financial advice, not a fatwa.
