# UI/UX Revamp Design Spec
**Date:** 2026-03-17
**Project:** Melon Trading Bot Dashboard
**Approach:** Option B — Design System Swap + Layout Restructure (JS/data logic untouched)

---

## Goals

Revamp the entire UI/UX of `dashboard.html` (and supporting HTML pages) without losing any existing features or data. Target: modern fintech app style (clean cards, breathing room, clear hierarchy).

---

## Layout & Navigation

### Desktop (≥1024px)
- **Fixed top navbar** (~56px tall)
  - Left: Logo + app name
  - Center: Nav items — Dashboard · Positions · Trades · Analytics · Learning · Alerts · Turbo
  - Right: Connection status dot + Trading toggle + Settings gear icon
- **No sidebar** — full-width content area below navbar
- Content max-width: 1440px, centered, with horizontal padding (24px)
- System status bar moves into top navbar or directly below it as a slim info strip

### Mobile (<1024px)
- **Slim top bar:** App name + connection status dot + trading toggle only
- **Fixed bottom tab bar** (safe-area inset aware):
  - Icons with labels: Dashboard, Positions, Trades, Analytics, Learning, Alerts, Turbo
  - Settings gear icon at far right
- Full-screen scrollable content between top bar and bottom tabs

### Positions Tab — Sub-navigation
- GTT Orders grouped inside Positions tab
- Pill/tab switcher within the tab content: "Open Positions" | "GTT Orders"
- Not a separate top-level nav item

### Settings / Config
- Gear icon in top navbar (desktop) and bottom tab bar (mobile)
- Navigates to the existing Config tab content (all fields preserved)
- No modal/slide-over needed — just switches to config tab

---

## Visual Style

### Color System (CSS Custom Properties)
```css
--c-bg:         #0d0d14;   /* slightly warmer dark */
--c-surface:    #13131d;
--c-surface-2:  #1a1a27;
--c-surface-3:  #222233;
--c-border:     rgba(255,255,255,0.07);
--c-border-2:   rgba(255,255,255,0.11);
--c-text:       #e2e8f0;
--c-muted:      #6b7280;
--c-green:      #22c55e;
--c-green-dim:  rgba(34,197,94,0.12);
--c-red:        #ef4444;
--c-red-dim:    rgba(239,68,68,0.12);
--c-amber:      #f59e0b;
--c-amber-dim:  rgba(245,158,11,0.12);
--c-blue:       #3b82f6;
--c-blue-dim:   rgba(59,130,246,0.12);
--c-purple:     #a855f7;
--c-purple-dim: rgba(168,85,247,0.12);
```

### Typography
- Fonts: Inter (UI) + JetBrains Mono (numbers/code) — unchanged
- Page/tab titles: 20px / font-weight 600
- Section headers: 11px / uppercase / letter-spacing 0.08em / muted color
- Large metric values: 28–32px / font-weight 700 / mono
- Body text: 13–14px / font-weight 400
- Labels/badges: 11–12px

### Cards & Components
- Card padding: 20px (consistent)
- Card border-radius: 16px outer, 10px inner elements
- Shadow: `0 2px 16px rgba(0,0,0,0.4)` (subtle, not heavy borders)
- Hover: border-color shifts to green tint, slight shadow lift
- Consistent 24px gap between cards in grids

### Buttons
- Primary: green bg, black text, green glow on hover
- Danger: red bg, white text
- Ghost: surface-2 bg, muted border, lighten on hover
- All buttons: 10px radius, ripple effect on tap, scale(0.97) on active

### Status Indicators
- Pulsing dot: active=green, inactive=red, warning=amber (unchanged behavior)
- Badges: pill shape, colored bg-dim + colored text

---

## Tabs & Content Inventory (all preserved)

| Tab | Key Features |
|-----|-------------|
| Dashboard | Smart warning cards, Trading windows, Turbo toggle, Risk overview (P&L, Capital, Risk %), Open positions summary, Recent trades, Quick chart |
| Positions | Open positions table + GTT Orders (sub-tab pill switcher) |
| Trades | Trade history table with filters |
| Analytics | Performance charts, stats (Chart.js) |
| Learning | Learning engine stats, badges |
| Alerts | Incoming alerts table/cards, alert stats |
| Turbo | Turbo queue, turbo mode controls |
| Config (Settings) | All existing config fields: capital, risk, modes, API keys, windows, etc. |

---

## Responsive Behavior

- **Breakpoints:** mobile < 768px, tablet 768–1023px, desktop ≥ 1024px
- Tables convert to card-list layout on mobile (existing behavior preserved)
- Grid columns: 1 col mobile, 2 col tablet, 3–4 col desktop
- All touch targets ≥ 44px on mobile
- Bottom tab bar uses `padding-bottom: env(safe-area-inset-bottom)`

---

## Implementation Strategy

All JavaScript, API calls, data-binding IDs, and functional logic remain **completely untouched**. Only HTML structure and CSS are modified.

### Phases
1. **CSS Design System** — Update `:root` vars, reset, typography helpers, card/button components
2. **Top Navbar** — Replace sidebar with top nav (desktop) + bottom tab bar (mobile)
3. **Dashboard Tab** — Restyle cards, grid, status bar
4. **Positions Tab** — Add GTT sub-tab pill switcher, restyle table
5. **Trades Tab** — Restyle filters + table
6. **Analytics Tab** — Restyle charts section
7. **Learning Tab** — Restyle stats cards
8. **Alerts Tab** — Restyle alert cards/table
9. **Turbo Tab** — Restyle turbo controls
10. **Config Tab** — Restyle form fields, sections

---

## Success Criteria

- All 9 tabs functional with zero JS breakage
- Top nav on desktop, bottom tabs on mobile
- GTT grouped under Positions as sub-tab
- Config accessible via gear icon
- Consistent spacing (24px grid gaps, 20px card padding)
- All existing IDs and data attributes preserved
- Mobile-first responsive, touch-friendly
