# Dashboard Page Overrides: tayyib-dashboard/index.html

> **PROJECT:** tayyib. Rules here **override** `design-system/tayyib/MASTER.md` (version 2, the v0.1.7 redesign);
> everything else follows the Master.

## Page-specific rules

- **Layout:** max width 1440px; 24px gutter (16px on a phone). Four tabs: Today, Results, Halal, Tickets. Pill tabs
  in the sticky top bar on a desktop; a bottom tab bar with icons below 760px.
- **Breakpoints:** 375 (designed first), 760 (bottom tab bar, single-column cards), 900 (tables become cards: two
  columns on a phone, four from 600px), 1180 (hero above the tiles; settings chip hidden), 1366 / 1440.
- **Today:** hero (date in words, written time, "This list was made with", date picker) + six KPI tiles; top-pick
  cards (price ladder, 60-day sparkline, halal chip, check badge, 2×2 numbers, one-line why, Why?); full list as a
  fixed-layout table with reasons truncated (full text in the tooltip and the drawer); highlight bar for capped
  stops and near / over halal limits, always with a labelled flag.
- **Results:** KPI tiles (win rate, avg R, total R, closed / 30 ring), equity card with an area gradient, result
  chips (right / wrong / no trade / pending), summary tables (one spanning "no closed trades" cell instead of four),
  every pick with a Chart button that opens the drawer.
- **Halal:** donut + legend, limits panel, filters (status defaults to compliant), gauges per ratio; Ratios opens the
  drawer.
- **Tickets:** safety banner, ready tickets (PASS, then WARN) with numbered steps for the user's broker and the other
  broker folded, Copy → "Copied ✓"; "Blocked (not tickets)" collapsed; positions.
- **Charts:** inline SVG computed by the server. Gradients use per-chart ids. A text summary under every chart.
  "price data unavailable" instead of any guessed line.

## Pre-delivery checklist: results (redesign, 2026-11-05)

Checked on the live data (`%USERPROFILE%\tayyib-live\trader`, read-only) with headless Chrome driven over the
DevTools protocol: real device-width emulation (375px included), light and dark, and clicks to open each drawer.
39 screenshots in the session scratchpad (`screenshots-v0.1.7`), each also measured for sideways overflow.

| check | result |
|---|---|
| No emojis as icons; one icon set | PASS: 5 status shapes, 4 tab icons, the logo; all inline SVG |
| `cursor: pointer` on clickables | PASS: tabs, sort headers, filters, Why? / Chart / Ratios, Copy, Close, folded sections |
| Transitions ≤ 200ms | PASS: 160ms colour / transform; drawer 200ms |
| Contrast ≥ 4.5:1, light and dark | PASS: lowest 4.79 (brass accent eyebrow, light), PASS text 4.95; all pairs in MASTER section 2 |
| Visible focus | PASS: 2.5px `:focus-visible` ring; the drawer is a modal `<dialog>` (focus trapped, Esc closes, focus returns) |
| `prefers-reduced-motion` | PASS: transitions, the shimmer and the drawer animation off |
| Responsive 375 / 768 / 1024 / 1366 / 1440 | PASS: no sideways scroll on any of the 39 captures (scrollWidth = clientWidth); the Why drawer renders fully at every width |
| Tap targets ≥ 44px on a phone | PASS: buttons 44px (slim table buttons are 36px on a desktop only, 44px rows on a phone are full-width), tabs 56px |
| Nothing behind fixed bars | PASS: body padding for the bottom tab bar; the sticky header offset matches the top bar |
| Status never by colour alone | PASS: badge = icon + word; flags = icon + words; gauges = bar + value + state word; ▲ / ▼ with % |
| Indian numbers | PASS: ₹1,00,000.00; ₹523.7 cr; set by the server |
| Offline | PASS: no external URL in the page (tested); system fonts only |
| Missing / not yet / not checked | PASS: UNKNOWN only for data failures; "no closed trades", "not yet", "not closed", "not checked (business excluded)" (tested) |
| Footer on every view | PASS: "Not financial advice, not a fatwa." |

Found and fixed during the review:
- the phone tab bar rendered at the top (a `backdrop-filter` on the top bar trapped `position: fixed`);
- the sticky table header sat over the first row (`overflow: hidden` made the table card its scroll container; now `clip`);
- price-ladder labels overlapped on narrow cards (now a three-column label row);
- the dark hero and safety banner turned pale (they used the dark theme's light primary; now their own tokens);
- table headers and dates broke mid-word; pending rows said UNKNOWN where "not yet" is the truth;
- the tickets banner repeated its own title.

Not verified: a real phone or tablet (emulated widths only), Firefox and Safari (Chrome only), and screen readers.
