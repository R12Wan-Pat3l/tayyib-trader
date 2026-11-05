# Dashboard Page Overrides: tayyib-dashboard/index.html

> **PROJECT:** tayyib. Generated 2026-11-05 by UI/UX Pro Max (`--page dashboard`), then adapted.
> Rules here **override** `design-system/tayyib/MASTER.md`; everything else follows the Master.

## Page-specific rules

- **Layout:** max width 1400px, 16px gutter on a phone. Tabs, not a 12-column grid: Today, Results, Halal,
  Tickets (generator: "12-column grid"; a tabbed single column reads better at 375px).
- **Density:** high. 32px table rows, 13–14px table text, sticky table headers.
- **Effects:** row highlight on hover (150ms), expandable rows for "Why?", "Chart" and "Ratios". Not used
  from the generator: chart zoom on click, filter animations, loading spinners (a "Loading..." line instead:
  the data is local and arrives in well under a second).
- **Highlights:** a capped stop or a halal ratio near its limit puts a 3px warn bar on the row's left edge
  **and** a triangle + "stop capped" / "near halal limit" label: never the bar alone.
- **Charts:** inline SVG computed by the server. Price: close line, entry solid / stop dashed / target dotted,
  labelled at the right edge; triangle = bought, square = exit; a text summary under it. Equity: cumulative R
  with a dashed 0R line and a text summary. "price data unavailable" instead of any guessed line.

## Pre-delivery checklist: results (v0.1.7, 2026-11-05)

Checked on the live data (a copy of `%USERPROFILE%\tayyib-live\trader`) with headless Chrome screenshots of
every tab at 1366px, light and dark, plus the offline test suite (`tests/test_v017.py`).

| check | result |
|---|---|
| No emojis as icons | PASS: five inline-SVG shapes (circle-check, triangle, octagon, clock, dashed circle) |
| One consistent icon set | PASS: the five shapes, 16px grid, 1.8 stroke |
| `cursor: pointer` on clickable elements | PASS: tabs, sort headers, Why? / Chart / Ratios, Copy |
| Hover transitions 150–300ms | PASS: 150ms colour / background only |
| Text contrast 4.5:1 (light and dark) | PASS: lowest pair 5.15:1 (pass green on white); see MASTER section 2 |
| Visible focus for keyboard | PASS: 2px `:focus-visible` outline; tabs use arrow keys / Home / End |
| `prefers-reduced-motion` | PASS: all transitions off |
| Responsive 375 / 768 / 1024 / 1366 | PARTLY VERIFIED: 1366 and 500px checked by screenshot; no page-level horizontal scroll (tables scroll in their own wrapper, long paths wrap). Headless Chrome will not render narrower than 500px, so 375px is by CSS only: check it on a phone |
| No content behind fixed navbars | PASS: no fixed bars |
| No horizontal scroll on mobile | PASS at 500px (see above) |
| Status never by colour alone | PASS: every status is label + shape; R values are signed (+ / −) |
| Indian number format | PASS: ₹1,00,000.00, formatted by the server (`inr()`) |
| Works offline | PASS: no external URL in the page (a test checks it); system fonts |
| Missing values are UNKNOWN, never 0 | PASS: server-side formatting, tested (`test_null_is_unknown`) |

Found and fixed during the check: the Halal table and the equity-curve summary did not render (a DOM
helper dropped every child after the first); the long data-folder path widened the page on a phone.
