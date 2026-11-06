# Design System Master File: tayyib

> **LOGIC:** When building a specific page, first check `design-system/tayyib/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** tayyib (tayyib-trader's local dashboard)
**Version:** 2, the v0.1.7 redesign (2026-11-05). Version 1 (the first, plain v0.1.7 page) is described in git history.
**Generated with UI/UX Pro Max 2.15.0** (development-time aid; nothing from it ships or runs):
- `search.py "premium fintech portfolio dashboard calm trustworthy" --design-system -p tayyib --density 7`: off target
  (an enterprise landing-page pattern, dark-only OLED style, Fira fonts from Google). Retried once, as the skill says:
- `search.py "wealth portfolio tracker app calm" --design-system -p tayyib`: Minimalism & Swiss style, calm cyan +
  health green palette, light and dark supported. Used for the restraint and the palette direction.
- Style searches: **Bento Box Grid** (modular cards of varied size, 16–24px radius, soft shadows, 4 → 2 → 1 columns) and
  **Soft UI Evolution** (softer-than-flat depth, 8–12px radius, 200–300ms motion, measured contrast). Chart search: gauge /
  bullet chart for KPI against a target, "place the number and target text beside the gauge; colour alone is insufficient".
  UX searches: mobile first, empty states with a helpful action, loading feedback that does not flash.
- The `frontend-design` skill is not installed in this environment. Its usual direction was applied by hand: a
  committed palette, a distinctive type pairing (a book serif for display, a system sans for data), one accent, no
  template look.

---

## 1. Constraints (override everything below)

| constraint | rule |
|---|---|
| One file, plain CSS / JS | `tayyib-dashboard/index.html` with inline `<style>` and `<script>`, served by `dashboard.py`. No framework, no build step |
| Offline | No CDN, no Google Fonts, no external images or scripts (a test checks the page has no external URL) |
| Fonts | No bundled font (none is shipped with an OFL licence file yet). Display: `"Iowan Old Style", "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif`. Text and numbers: `"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif`, with `font-variant-numeric: tabular-nums` on every number. Mono only for ids and paths |
| Light + dark | Both from `prefers-color-scheme`. Dark is designed, not inverted: deep green-black surfaces, its own hero gradient, lighter status hues |
| Status never by colour alone | Every status = text label + an icon of its own shape (section 4) + colour |
| Colour-blind safe | Status hues from the Okabe-Ito set, darkened (light) or lightened (dark) to pass 4.5:1. R values signed (`+1.80R`, `−1.00R`); up / down also by ▲ / ▼ |
| Indian numbers | Formatted by the server: `₹1,00,000.00`; large money as `₹523.7 cr`, `₹12.5 lakh` |
| Missing data | **UNKNOWN** for a data failure; "not checked (business excluded)" when the screen never needed the number; "not yet" / "not closed" for a paper trade still pending; "no closed trades" instead of a 0 or ₹0.00 that looks real; "price data unavailable" instead of a guessed line |
| No sideways scroll | At every width from 375px. Tables use `table-layout: fixed` on a desktop and become cards below 900px |
| Two write routes only | Buttons switch tabs, sort, filter, open a drawer or **copy** text. The only writes are **Save settings** (after a review drawer), **Run today's list** (confirm drawer before 3:30 PM IST) **Run backtest** (v0.2.2: years, mode, compare in a drawer; the same `/api/run` route, one run at a time) and **Send test email** (v0.2.3: Settings, Email; the same route, only `email_report.py test`). The first-run Welcome drawer saves through **Save settings**. No password field anywhere. Nothing places an order |
| Motion | ≤ 200ms, transform / opacity / colour only; all off under `prefers-reduced-motion: reduce` |
| Tap targets | ≥ 44px for every button on a phone (tabs 56px) |

## 2. Colour tokens

Semantic CSS variables only; components never use raw hex.

| token | light | dark | use |
|---|---|---|---|
| `--bg` | `#F4F1E9` warm off-white | `#0C1311` deep green-black | page |
| `--surface` | `#FFFDF8` | `#131C19` | cards, tables, drawer |
| `--surface-2` / `--surface-3` | `#F1ECE1` / `#E6DFD1` | `#18231F` / `#203029` | table head, tracks, segmented controls |
| `--line` / `--line-strong` | `#E1D9C9` / `#CFC5B1` | 10% / 20% white-green | borders |
| `--fg` | `#16201C` | `#ECF1EE` | text |
| `--muted` | `#545E59` | `#A3B0AA` | secondary text |
| `--primary` | `#0F5257` petrol teal | `#7FD3C8` | active tab, links, buttons, lines in charts, focus ring |
| `--hero-a` → `--hero-b` | `#0F5257` → `#0A3D41` | `#145550` → `#0B2E2B` | hero and the safety banner (text `--on-hero`) |
| `--accent` | `#8C5E0E` brass | `#E3B866` | the logo dot and the "Top pick n" eyebrow only |
| `--pass` | `#00735A` | `#3FD0A8` | PASS, TARGET, right, within limit (Okabe-Ito bluish green) |
| `--warn` | `#8A5A00` | `#F2B84B` | WARN, near a limit, stop capped, stale (Okabe-Ito orange) |
| `--block` | `#B03A00` | `#FF8A5C` | BLOCK, STOP, wrong, over a limit, excluded (Okabe-Ito vermillion) |
| `--info` | `#005A8C` | `#6CC3F5` | pending, your override, entry line (Okabe-Ito blue) |
| `--unknown` | `#5B6472` | `#A3AEBD` | UNKNOWN, no trade, not checked |
| `--x-bg` | solid tints (`#E2F2EC` ...) | the hue at 12% | badge / chip / banner fills |

The brand teal is deliberately bluer than PASS green, and PASS never appears without its check-circle and label.

**Measured WCAG contrast** (worst case over bg / surface / surface-2), light / dark: fg 14.18 / 14.15, muted 5.71 / 7.20,
primary 7.54 / 9.28, accent 4.79 / 8.71, pass 4.95 / 8.31, warn 5.03 / 9.03, block 5.16 / 6.96, info 6.27 / 8.28,
unknown 5.08 / 7.19. Text on the hero 8.88 / 7.79; button text on primary 8.88 / 9.40. Status text on its own tint:
light 5.04–6.25, dark 6.17–7.63. Every pair is at least 4.5:1.

## 3. Type, spacing, shape, depth

- Display serif (hero date 30px, section titles 22px, card symbols 22px, KPI values 26px); text sans 15px, tables 14px,
  labels 12–13px; table headers 11.5px uppercase with 0.06em tracking.
- Spacing on a 4px grid: 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 36, 48. Page gutter 24px (16px on a phone), max 1440px.
- Radius: 8 (inputs), 12 (banners), 18 (cards, panels, tables), 24 (hero, drawer); pills 999px.
- Depth (soft UI): `--shadow-1` hairline for tiles and tables, `--shadow-2` for cards, `--shadow-3` for the drawer.
  Dark mode uses an inset top highlight instead of drop shadows.

## 4. Status: label + shape + colour

| status | icon (inline SVG, 16px grid, 1.8 stroke) | token |
|---|---|---|
| PASS / TARGET / ✓ passed / within limit | circle with a check | `--pass` |
| WARN / near limit / stop capped / stale | triangle with `!` | `--warn` |
| BLOCK / STOP / ✗ failed / over limit / excluded | octagon with `×` | `--block` |
| pending (WAITING, OPEN) / override | clock | `--info` |
| UNKNOWN / no trade / not checked | dashed circle with `?` | `--unknown` |

Icons are `aria-hidden`; the label beside them is the accessible text.

## 5. Components

- **Top bar** (sticky, blurred): logo mark (two rotated squares, an eight-point star, around a leaf, brass centre dot),
  wordmark in the serif, the tabs as a pill segmented control, "Current settings: default@2" on the right. On a
  phone the tabs become a **bottom tab bar** with icons (56px targets, safe-area padding).
- **Hero** (Today): deep-teal gradient card with the date in words, written time, scanned count, "This list was made
  with: default@n" and the date picker; beside it six **KPI tiles** (capital in lakh/crore, risk per trade, scanned,
  PASS / WARN / BLOCK counts with their icons).
- **Top-pick card**: rank eyebrow, symbol, company · setup, check badge, halal chip (within / near / over limit, or
  "compliant by your override"), stop-capped chip, **price ladder**, **60-day sparkline** with an area gradient and the
  % change (▲ / ▼), a 2×2 grid of quantity / risk at stop / net R:R / time machine, a one-line "why" summary, and Why?.
- **Price ladder**: one rounded track; the stop-to-entry part tinted as risk, entry-to-target as reward; markers: stop
  = diamond, entry = circle (info), target = circle (pass); a three-column label row with price, R multiple and %.
- **Responsive table**: `table-layout: fixed`, sticky header under the top bar, sortable `<button>` headers with
  `aria-sort`, long text truncated with an ellipsis and the full text in `title`. Below 900px each row becomes a card:
  cells in two columns with their header as a small label (`data-label`).
- **Drawer** (`<dialog>` with `showModal`, so focus is trapped and Esc closes): a slide-over from the right on a
  desktop (560px), a bottom sheet with a grab handle on a phone (max 88vh). Used for Why?, the price chart and Ratios.
- **Why groups**: `<details open>` per group (HALAL, LIQUIDITY, SETUP, NEWS, PLAN, HISTORY, RISK) with a tally
  (✓ n, ✗ n, ? n) in the summary; each item has its icon, the word (passed / failed / UNKNOWN), value, limit, flags and
  note. Headlines are shown in full here.
- **Gauge** (halal ratio): track, fill = value / limit (scaled so the limit sits at 2/3), a dark tick at the limit and a
  warn tick at the near mark, and text "value / limit" plus the state in words with its icon.
- **Donut** (halal universe): stroke-dasharray segments, the total in the centre, a legend with badge, count and %.
- **Progress ring**: closed trades out of 30, the number inside.
- **Equity curve**: cumulative R line with an area gradient and a dashed 0R line; an empty state until a trade closes.
- **Safety banner** (Tickets): hero gradient, shield icon, "Nothing here places an order".
- **Copy button**: filled primary; on success turns PASS-coloured and reads "Copied ✓" for 1.6s; announced in an
  `aria-live` region.
- **Collapsed sections**: `<details>` for "Blocked (not tickets)", the other broker's steps and run notes.
- **Skeletons** for loading (shimmer, off under reduced motion) and **empty states** that say what to run
  ("Run: give me today's halal list").

## 5b. Backtest tab (v0.2.2)

Order fixed by the server (`order`): run picker + Run backtest + header list → **banners (warn style, all,
never collapsed)** → cards (strategy wide; Shariah BeES; Nifty 50 with a dashed border and the label "not
halal-screened, reference only" beside the neutral icon) → equity chart (strategy solid 2.4px primary,
ETF dashed info, Nifty dotted unknown: told apart by dash pattern, end labels and a legend, not by hue) with
a drawdown strip (block tint, dashed markers at the worst drawdown's peak and trough, dates in text) →
breakdown tables (rows under 30 trades: surface-2, muted text, dashed-circle icon and "(too few to judge)")
→ compare table → trades (filters as segmented controls, R with ▲ / ▼ and a sign, a Chart button per row)
→ universe (tiles, the late-joiner line as an info banner, two tables) → footer line "Past results do not
predict future results. Not financial advice, not a fatwa."

## 6. Page pattern: bento data views

Top bar → tab panel → footer "Not financial advice, not a fatwa." (every view). Each tab opens with a bento row
(hero + tiles, or KPI tiles + panels on a 12-column grid that falls to 6 and 1 column), then sections with a serif title
and a muted subtitle, then the detailed table. The open tab is kept in the URL hash; arrow keys move between tabs.

## 7. Anti-patterns (do not use)

- External fonts, scripts, images or icons; emoji as icons.
- A number without its unit or sign; ₹0.00 or 0% standing in for "nothing to measure yet".
- Status by colour alone; red / green as the only difference between two things.
- A table that scrolls sideways, or a page that does.
- Any button that could be read as acting on the market (buy, sell, place, order, submit, run).
- `backdrop-filter` on an ancestor of a fixed element (it traps `position: fixed`: the phone tab bar must not be
  inside a filtered top bar).
- Motion over 200ms, or motion that conveys nothing.

## 8. Pre-delivery checklist

- [ ] No emojis as icons; one SVG icon set (5 status shapes + 4 tab icons + logo)
- [ ] `cursor: pointer` on every clickable element
- [ ] Hover and press transitions ≤ 200ms; none under reduced motion
- [ ] Contrast ≥ 4.5:1 in light and dark (section 2)
- [ ] Visible `:focus-visible` ring; the drawer traps focus and returns it on close
- [ ] Responsive at 375, 768, 1024, 1366, 1440: no sideways scroll; tables become cards below 900px
- [ ] Tap targets ≥ 44px on a phone; nothing hidden behind the bottom tab bar
- [ ] Status never by colour alone; en-IN numbers; UNKNOWN never 0
- [ ] Works offline; footer on every view

---

## Appendix A: version 1 of this file (the first v0.1.7 page), sections 1-8, superseded

Kept for the record; see git history for the full text. Its generator query was
`search.py "personal finance trading analytics dashboard" --design-system --persist -p "tayyib" --density 8 --motion 2 --page dashboard`.

## Appendix B: the generator's raw output (reference only; section 1 overrides it)

- **Pattern:** Product Demo + Features (Hero > Product video/mockup > Feature breakdown > Comparison > CTA).
  Not used: this is a tool, not a landing page.
- **Style:** Glassmorphism (backdrop blur 10–20px, subtle 1px rgba white border, light reflection, Z-depth).
  Best for "financial dashboards"; accessibility risk conditional (contrast 4.5, keyboard, visible focus,
  reduced motion). Not used: blur behind dense tables lowers contrast.
- **Colours (dark):** primary `#1E40AF`, secondary `#3B82F6`, accent `#059669`, background `#0F172A`,
  foreground `#FFFFFF`, card `#192134`, muted `#101A34`, muted foreground `#94A3B8`, border
  `rgba(255,255,255,0.08)`, destructive `#DC2626`, ring `#FFFFFF`. "Trust blue + profit green on dark."
  Kept: primary, background, card, muted (dark theme). Changed: green / red status replaced by the
  colour-blind-safe set in section 2.
- **Typography:** Fira Code / Fira Sans via Google Fonts. Replaced by the system stack (offline).
- **Spacing (density 8/10):** 2, 4, 8, 12, 16, 24, 32px. Kept.
- **Shadows:** sm `0 1px 2px rgba(0,0,0,.05)`, md `0 4px 6px rgba(0,0,0,.1)`, lg, xl. Only sm is used.
- **Motion:** Scroll Reveal (subtle) with GSAP ScrollTrigger. Dropped (no external scripts, no need).
- **Avoid:** pure white backgrounds. Kept.
- **Supplementary searches:** `"cumulative performance over time" --domain chart` → line chart; "never
  distinguish series by hue alone", "visible data table plus concise trend summary" (applied: equity curve
  with a text summary). `"color not only status indicator" --domain ux` → "use icons/text in addition to
  colour" (applied: section 4). `"data table dense sortable" --domain ux` → "overflow-x-auto wrapper"
  (applied: section 5).
