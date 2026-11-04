# Changelog

## v0.1.2 (2026-11-04)

- Packaging only: the plugin version is bumped so `claude plugin update` delivers the v0.1.1 risk and
  daily-list fixes to anyone who installed 0.1.1 before they landed (`check.py`, `daily.py`,
  `size.py` and the daily SKILL.md). No behaviour change from the v0.1.1 tag.
- A test now fails if `plugin.json`, the core VERSION, the MCP server version and the top CHANGELOG
  entry disagree, so a release can't ship without a version bump.

## v0.1.1 (2026-11-04)

- New skill `tayyib-daily`: one command for today's halal trade list. It runs scan, news, plan, time
  machine, sizing and the risk check for the best candidates (only today's stocks; earlier plans and
  placed orders are left alone) and prints one table with entry, stop, stop %, target, quantity, rupee
  risk, verdict and PASS / WARN / BLOCK, with every reason (HALAL-WATCH first). Saved to
  `trader/daily/DATE.md`. Warns when run during market hours or when the halal list is due a rebuild.
- The daily list's PASS / WARN / BLOCK always matches a plain `tayyib-risk` run: it risk-checks the
  whole orders file (open positions and placed orders count), sizing best expectancy first. Today's
  tickets replace earlier unplaced ones and it says which; placed orders are never touched.
- `--mode all` alternates the best swing and delivery ideas instead of showing only delivery.
- Budget: a new ticket never reuses a placed order's id (adds -2, -3); it says when it replaces an
  earlier unplaced ticket for the same stock.
- Risk: a negative time-machine expectancy is a WARN. A second ticket for a signal that is already
  placed is a BLOCK. `check.py SYMBOL` now counts every other ticket toward the limits and only
  reports and saves the ones asked for.
- Daily list skips stocks you already hold or have placed (it says so); its notes say which tickets
  were removed and which were replaced; each reason is labelled BLOCK or WARN.
- MCP tool `daily` (17 tools, still none that place orders).
- Plugin version 0.1.1, so `claude plugin update` picks this up.

## v0.1.0 (2026-11-04)

First release. 13 skills for halal swing and delivery trading on NSE/BSE, an MCP server, and
91 offline tests. Validated on live data (Windows, Python 3.13) over several runs.

**Halal screen**
- Business screen (finance, alcohol, tobacco, gambling; plural names; NSE placeholder rows dropped)
  plus TASIS-style ratios: debt < 25% of assets, non-compliant income < 3%, cash + receivables < 90%.
- The income test shows reported interest and the assumed 8% return on short-term investments side
  by side; total income = revenue + interest + other income, as Indian annual reports define it.
- `compare` against a trusted Shariah list; `--accept-income-reviews` for income-only cases; user
  overrides kept across rebuilds; build summary shows counts before and after overrides.
- Live check vs Nippon Shariah BeES + Tata Ethical holdings (Sep 2026): the automatic screen agreed on
  81.0% of stocks, all differences on the strict side (we block, the funds allow); no stock we mark
  compliant is non-compliant on those lists. After checking 8 of the differences against their FY26
  annual reports and recording them as user overrides, agreement is 94.8%.

**Trading**
- Swing (breakout, pullback, oversold, squeeze) and delivery (trend) setups with liquidity filters.
- Stops capped at 10% (swing) and 15% (delivery), configurable; caps are strict.
- Time machine: 10,000 simulated futures + historical replay in R after charges; verdict warns when
  a loss is the most likely single outcome.
- Indian delivery charges match Zerodha's published rates to the paisa (GST on IPFT included).
- Hard rules in code: CNC only, no short selling, no F&O, no margin; no order is ever placed.

**Data**
- Yahoo (.NS), NSE announcements / PIT / bulk-block deals (reported UNKNOWN, never zero, when NSE
  blocks), Google News India, Moneycontrol, ET Markets, Livemint. News tags from headlines only,
  pick-lists recognised, near-repeats merged only with identical numbers within 12h.

**Works with**
- Claude Code (plugin or copied skill folders), any MCP client (`mcp/server.py`, 16 tools, none
  place orders), any agent via AGENTS.md. Windows: `py` fallback documented in every skill.
