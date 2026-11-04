---
name: tayyib-scanner
description: >-
  Chart Scanner for halal NSE stocks. Scans only the Shariah-compliant universe for swing
  setups (breakout near the 20-day high, pullback to the 20 EMA, oversold bounce above the 200-day,
  volatility squeeze) and delivery setups (long-term trend near the 52-week high), with liquidity
  filters, on free daily Yahoo data. Writes trader/scan.json. Use when the user says "scan the market",
  "find halal setups", "what is breaking out on NSE", "swing trade ideas", "stocks to buy for delivery",
  "build my watchlist", or at the start of the week.
argument-hint: "[--mode swing|delivery|all] [--symbols ...]"
---

# tayyib-scanner

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-scanner/scan.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, a data source down), say so and stop. Never give halal status, prices, ratios, setups or levels from memory.

Lists halal-compliant stocks whose daily chart matches a rule. A list of charts, not a list of stocks
to buy. Each candidate comes with a **trigger** (a buy-stop just above a level) and an
**invalidation** (the level that kills the idea).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py"                          # all modes, whole compliant universe
python3 "${CLAUDE_SKILL_DIR}/scan.py" --mode swing --top 15
python3 "${CLAUDE_SKILL_DIR}/scan.py" --mode delivery
python3 "${CLAUDE_SKILL_DIR}/scan.py" --symbols TCS,ASIANPAINT  # still halal-filtered
python3 "${CLAUDE_SKILL_DIR}/scan.py" --setups breakout,pullback --limit 100
```

Run it after the close (3:30 PM IST) or before the open; it uses completed daily bars.

| setup | mode | rule (on the latest close) |
|---|---|---|
| breakout | swing | close > 50-day > 200-day, 50-day rising, within 3% of the 20-day high; trigger just above it |
| pullback | swing | same uptrend, low tagged the 20 EMA, close held it, RSI 35-58; trigger above that day's high |
| oversold | swing | above the 200-day, RSI(14) under 35 in the last 4 days, a green close |
| squeeze | swing | uptrend, last 10 days' range under half the prior 30 days' and under 8% of price |
| trend | delivery | above a rising 200-day, 50 > 200, within 15% of the 52-week high, 6-month return > 0 |

Liquidity: price at least Rs 20 and 20-day average traded value at least Rs 2 crore (config
`min_price`, `min_turnover_rs`). Score ranks candidates; it is not a probability.

Next: `tayyib-news` on the candidates, then `tayyib-entry check SYMBOL`.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
