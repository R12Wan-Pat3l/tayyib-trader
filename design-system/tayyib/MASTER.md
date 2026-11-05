# Design System Master File: tayyib

> **LOGIC:** When building a specific page, first check `design-system/tayyib/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** tayyib (tayyib-trader's local, read-only dashboard)
**Generated:** 2026-11-05 with UI/UX Pro Max 2.15.0:
`search.py "personal finance trading analytics dashboard" --design-system --persist -p "tayyib" --density 8 --motion 2 --page dashboard`
**Category (generator):** Personal Finance Tracker. **Design dials:** Motion 2/10 (subtle), Density 8/10 (dense).
**Adapted** by hand to the project's constraints (section 1). The generator's raw output is kept in the
appendix for reference; where they disagree, section 1 wins.

UI/UX Pro Max is a development-time design aid. Nothing from it ships or runs in tayyib-trader.

---

## 1. Constraints (override everything below)

| constraint | rule |
|---|---|
| Plain CSS | No Tailwind, no CSS framework, no build step. One `index.html` with inline `<style>` and `<script>` |
| Offline | No CDN, no Google Fonts, no external images or scripts. The page must work with the network unplugged |
| Fonts | System stack only: `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`; numbers in `ui-monospace, "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace` with `font-variant-numeric: tabular-nums` (replaces the generator's Fira Code / Fira Sans) |
| Light + dark | Both, from `prefers-color-scheme`. Light is the default; no pure white page background (generator anti-pattern): `#F7F8FA` |
| Status never by colour alone | Every status carries a text label **and** an icon of its own shape (section 4). Colour is a third cue, never the only one |
| Colour-blind safe | Status hues from the Okabe-Ito set (distinguishable with protanopia, deuteranopia and tritanopia); positive / negative numbers are signed (`+1.80R`, `−1.00R`) and never red/green only |
| Indian number format | `Intl.NumberFormat("en-IN")`: `₹1,00,000.00`; percentages to 1–2 decimals; dates `YYYY-MM-DD` (IST) as stored |
| Missing data | Shown as the word **UNKNOWN** (or "price data unavailable" for charts), never `0`, never blank, never a guessed line |
| Dense tables | Row height 32px, cell padding 4px 8px, 13–14px text; readable at **1366px** and at **375px** (tables scroll inside their own wrapper, never the page) |
| Read-only | The only buttons are tabs, sort / filter / expand controls and **Copy**. No form posts, no button that places, changes or cancels an order |
| Motion | Subtle (dial 2): 150–200ms colour / opacity transitions only; none under `prefers-reduced-motion: reduce`. No GSAP (generator suggestion dropped: no external scripts) |

Replaced from the generator: Glassmorphism (backdrop blur hurts dense-table legibility and contrast) becomes
**flat, bordered surfaces**; the "Product Demo + Features" landing pattern does not apply to a tool and becomes
**tabbed data views** (section 6).

---

## 2. Colour tokens

Semantic CSS variables only; components never use raw hex.

| token | light | dark | use |
|---|---|---|---|
| `--bg` | `#F7F8FA` | `#0F172A` | page |
| `--surface` | `#FFFFFF` | `#192134` | cards, tables |
| `--surface-2` | `#EEF1F5` | `#101A34` | table head, zebra, code |
| `--fg` | `#111827` | `#F1F5F9` | text |
| `--muted` | `#4B5563` | `#A3B1C6` | secondary text |
| `--border` | `#D5DAE1` | `rgba(255,255,255,.12)` | lines |
| `--primary` | `#1E40AF` | `#93B4FF` | links, active tab, focus ring |
| `--pass` | `#00735A` | `#3FD0A8` | PASS, TARGET, right (Okabe-Ito bluish green, darkened for 4.5:1) |
| `--warn` | `#8A5A00` | `#F2B84B` | WARN, near a limit, stale (Okabe-Ito orange, darkened) |
| `--block` | `#B03A00` | `#FF8A5C` | BLOCK, STOP, wrong, excluded (Okabe-Ito vermillion, darkened) |
| `--info` | `#005A8C` | `#6CC3F5` | OPEN / WAITING / pending (Okabe-Ito blue) |
| `--unknown` | `#5B6472` | `#A3AEBD` | UNKNOWN, NOT TRIGGERED |

Measured WCAG contrast, worst case over `--bg`, `--surface` and `--surface-2` (light / dark): fg 15.66 / 14.65,
muted 6.67 / 7.38, primary 7.70 / 7.81, pass 5.15 / 8.25, warn 5.23 / 8.97, block 5.37 / 6.91, info 6.52 / 8.23,
unknown 5.28 / 7.14. Every pair is at least 4.5:1.

Each status colour is used for the icon and the label text on `--surface`, and for a 3px left border on
banners and cards; tinted backgrounds are `color-mix(in srgb, var(--x) 12%, var(--surface))`.

## 3. Type, spacing, shape

- Base 14px for tables, 15px body, headings 18 / 16 / 14px semibold; line height 1.45.
- Spacing (density 8): `--s1 2px, --s2 4px, --s3 8px, --s4 12px, --s5 16px, --s6 24px, --s7 32px`.
- Radius 6px (cards 8px). Shadows: none in tables; `0 1px 2px rgba(0,0,0,.06)` on cards.
- Page gutter 16px on a phone, max width 1400px.

## 4. Status: label + shape + colour

| status | icon (inline SVG) | colour token |
|---|---|---|
| PASS / TARGET / ✓ ok | circle with a check | `--pass` |
| WARN / near limit / stale | triangle with `!` | `--warn` |
| BLOCK / STOP / ✗ failed / excluded | octagon with `×` | `--block` |
| OPEN / WAITING / review | clock (circle with hands) | `--info` |
| UNKNOWN / NOT TRIGGERED | dashed circle with `?` | `--unknown` |

Icons are decorative (`aria-hidden="true"`); the label next to them is the accessible text. Unicode ✓ / ✗ are
used inside the Why panel as text, always next to the words "ok" / "failed" / "UNKNOWN".

## 5. Components

- **Banner**: full-width box, 3px left border in its status colour, icon + bold first words. `role="status"`.
- **Card** (top pick): symbol, setup, entry / stop / target / qty / risk ₹ in a 2-column grid, status badge.
- **Badge**: icon + uppercase label, 12px semibold, 2px 6px padding, border 1px in the status colour.
- **Table**: sticky header, numeric columns right-aligned in the mono stack, sortable headers are `<button>`s
  with `aria-sort`, wrapper `overflow-x: auto` so only the table scrolls on a phone.
- **Expandable row** (Why?, chart): a `<button aria-expanded>` in the row; the detail renders in a full-width
  row below.
- **Ratio bar**: track = the limit (100%), fill = value / limit, a tick at the near-limit share (90%), the
  value and the limit as text beside it. Over the limit: block colour + octagon icon; near: warn colour + triangle.
- **Chart** (inline SVG, no library): price line, horizontal lines for entry (solid), stop (dashed),
  target (dotted), each labelled at the right edge; fill and exit as distinct markers (triangle up / square).
  A text summary under every chart. Equity curve: a line of cumulative R with a 0R baseline.
- **Copy button**: the only action button. Uses `navigator.clipboard.writeText`, falls back to selecting the
  text; announces "Copied" in an `aria-live` region.
- **Focus**: `:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px }`. Never removed.

## 6. Page pattern: tabbed data views

Header (title, version, data folder, settings label) → tabs (Today, Results, Halal, Tickets) → tab panel →
footer "Not financial advice, not a fatwa." on every tab. Tabs are `role="tablist"` buttons with arrow-key
navigation; the open tab is kept in the URL hash (`#today`), so the back button and reload work.

## 7. Anti-patterns (do not use)

- Pure white page background; colour-only status; red/green-only gains and losses
- Emojis as icons (use the inline SVG set in section 4)
- External fonts, CDNs, analytics, any network request other than `GET /api/...` on 127.0.0.1
- Layout-shifting hovers (scale transforms); instant state changes on hover (use 150ms)
- Invisible focus; placeholder-only labels; text under 12px
- Zero in place of a missing value; a drawn line where price data was unavailable
- Any control that suggests an order can be placed from the page

## 8. Pre-delivery checklist

Generator checklist, adapted (results recorded in `pages/dashboard.md`):

- [ ] No emojis used as icons (inline SVG set, section 4)
- [ ] One consistent icon set (the five shapes of section 4)
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150–300ms), none under reduced motion
- [ ] Light mode: text contrast 4.5:1 minimum (and dark mode)
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1366px / 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile (tables scroll inside their wrapper)
- [ ] tayyib: status never by colour alone (label + shape)
- [ ] tayyib: Indian number format (₹1,00,000.00)
- [ ] tayyib: works offline (no external URL in index.html)
- [ ] tayyib: UNKNOWN shown for missing values, never 0

---

## Appendix: the generator's raw output (reference only; section 1 overrides it)

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
