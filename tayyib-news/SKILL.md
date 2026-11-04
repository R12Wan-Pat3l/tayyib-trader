---
name: tayyib-news
description: >-
  News Monitor for Indian stocks. Pulls recent headlines per stock from Google News India,
  NSE corporate announcements, Moneycontrol, ET Markets and Livemint RSS, tags them (results, dividend,
  order win, deal, regulatory, pledge, management) and flags HALAL-WATCH items (new borrowing, NCDs,
  entry into impermissible business) that could change a stock's Shariah status. Writes trader/news.json.
  Use when the user asks "any news on X", "why is X moving", "what's happening in the market", or
  after a scan and before an entry.
argument-hint: "[--symbols ...] [--hours 72] [--market]"
---

# tayyib-news

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-news/news.py ...`.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                         # scan candidates + open positions
python3 "${CLAUDE_SKILL_DIR}/news.py" --symbols TCS,INFY --hours 48
python3 "${CLAUDE_SKILL_DIR}/news.py" --market                # plus general market headlines
```

Times are IST. Sources that fail (sites change, rate-limit, or block bots) are listed at the end and
the rest still run; the feeds are in `config.json` under `news.feeds`.

How to use the output:
- **results** in the window: a swing trade held through results can gap past the stop. Say so.
- **HALAL-WATCH: new debt**: a large borrowing can push debt over 25% of assets. Suggest
  `tayyib-results SYMBOL` to see the ratio trend, and a rebuild of the halal list after the next filing.
- **HALAL-WATCH: impermissible business**: an acquisition or new line of business may make the stock
  non-compliant. Suggest the user check it and record a ruling with `tayyib-halal override`.
- `tayyib-risk` turns both kinds of flag into warnings on the order.

Headlines are not verified facts; NSE announcements are the company's own filing.

## Rules this skill never bends

- Halal-compliant stocks only (see `tayyib-halal`). Anything else is skipped or blocked.
- Delivery (CNC) only: no intraday (MIS), no F&O, no short selling, no margin or MTF.
- Nothing in tayyib-trader places an order. The user places it in their broker app after an explicit yes.
- Not financial advice, not a fatwa. Say so when you present results, briefly.

Files live in `trader/` in the current folder (override with `TAYYIB_DIR`). Every script takes `--json`.
