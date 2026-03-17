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
  - Right: Connection status dot + Trading toggle + Settings gear icon (`onclick="switchTab('config')"`)
- **No sidebar** — full-width content area below navbar
- Content max-width: 1440px (new addition), centered, with horizontal padding (24px)
- System status bar rendered as a slim strip directly below the top navbar

### Tablet (768–1023px)
- Uses the **mobile layout**: slim top bar + fixed bottom tab bar (same as mobile < 768px)
- Bottom tabs replace top nav at this breakpoint too (cleaner on touch screens)

### Mobile (<768px)
- **Slim top bar:** App name + connection status dot + trading toggle only
- **Fixed bottom tab bar** (safe-area inset aware):
  - Icons with labels: Dashboard, Positions, Trades, Analytics, Learning, Alerts, Turbo
  - Settings gear icon at far right (`onclick="switchTab('config')"`)
- Full-screen scrollable content between top bar and bottom tabs

### Sidebar — Preserved as Invisible Stub
- `#sidebar` and `#sidebar-overlay` elements are **kept in the DOM but hidden** via `display:none` on both breakpoints
- `toggleMobileSidebar()` function is left untouched (becomes a no-op visually but doesn't throw)
- `#mobile-menu-btn` (hamburger) is hidden — no longer shown in the new top bar

### Navigation JS Compatibility (CRITICAL)
- All new nav buttons (top navbar + bottom tab bar) **must carry class `nav-item`** so `switchTab`'s `querySelectorAll('.nav-item')` active-state logic works
- **ID uniqueness constraint:** HTML IDs must be unique. Since `switchTab` uses `getElementById('nav-{tabname}')` to set the active highlight, only one element can hold that ID.
  - Desktop top navbar buttons get `id="nav-{tabname}"` (e.g., `id="nav-dashboard"`)
  - Mobile bottom tab bar buttons use `data-tab="{tabname}"` instead of an ID
  - `switchTab` is updated minimally to also activate `[data-tab="{tab}"]` elements (one-line addition alongside the existing `getElementById` call)
  - This is the **only JS change** required — a single extra line in `switchTab`
- Gear/Settings: desktop navbar uses `id="nav-config"`, mobile bottom bar uses `data-tab="config"`

### GTT Sub-tab — JS Compatibility (CRITICAL)
- `#tab-gtt` and `#nav-gtt` elements are **preserved in the DOM**
- `#nav-gtt` is hidden (not shown in top navbar or bottom tab bar) but remains in DOM so `switchTab('gtt')` doesn't throw
- Inside `#tab-positions`, a pill switcher is added: "Open Positions" | "GTT Orders"
  - "Open Positions" pill: calls `switchTab('positions')` — activates the Positions tab normally
  - "GTT Orders" pill: calls `switchTab('gtt')` — activates `#tab-gtt` as the visible full tab
- Inside `#tab-gtt`, a **"← Back to Positions"** link/button calls `switchTab('positions')` — this is the return path
- The pill switcher in `#tab-positions` is **purely visual UI** with no JS state to manage — each pill just calls the existing `switchTab()` with its target tab name
- GTT remains a real tab, just reachable only via the pill in Positions, not the main nav

### `#page-title` — Preserved
- `#page-title` element is **kept in the top navbar** on all breakpoints (visible on mobile top bar, visible or subtly shown on desktop navbar)
- Updated by `switchTab` as before — no change to JS

### `#toast-container`
- Adjusted `top` offset to `calc(56px + 8px)` to clear the new fixed top navbar (currently `top-4`)

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

### Dynamic Class Name Aliases (DO NOT RENAME)
JS generates class names dynamically via `textColors` object and template literals (e.g., `text-green-400`, `text-red-400`, `text-primary-400`, `border-l-yellow-500/50`). These are CSS compatibility aliases defined in the stylesheet. They must not be renamed or removed — only their style values may change.

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
| Positions | Open positions table + GTT Orders (sub-tab pill switcher — see GTT section above) |
| Trades | Trade history table with filters |
| Analytics | Performance charts, stats (Chart.js) |
| Learning | Learning engine stats, badges |
| Alerts | Incoming alerts table/cards, alert stats |
| Turbo | Turbo queue, turbo mode controls |
| Config (Settings) | All existing config fields: capital, risk, modes, API keys, windows, etc. |

---

## Responsive Behavior

- **Breakpoints:** mobile+tablet < 1024px uses bottom tab layout; desktop ≥ 1024px uses top navbar
- Tables convert to card-list layout on mobile (existing behavior preserved)
- Grid columns: 1 col mobile, 2 col tablet, 3–4 col desktop
- All touch targets ≥ 44px on mobile
- Bottom tab bar uses `padding-bottom: env(safe-area-inset-bottom)`

---

## Implementation Strategy

All JavaScript, API calls, data-binding IDs, and functional logic remain **untouched** except:
- `#toast-container` top offset adjusted in CSS (not JS)
- GTT pill switcher calls existing `switchTab('gtt')` — no new JS needed

### Phases
1. **CSS Design System** — Update `:root` vars, reset, typography helpers, card/button components
2. **Top Navbar + Bottom Tab Bar** — Replace sidebar HTML with top nav (desktop) + bottom tab bar (mobile); hide sidebar stub
3. **Dashboard Tab** — Restyle cards, grid, status bar
4. **Positions Tab** — Add GTT pill switcher, restyle table
5. **Trades Tab** — Restyle filters + table
6. **Analytics Tab** — Restyle charts section
7. **Learning Tab** — Restyle stats cards
8. **Alerts Tab** — Restyle alert cards/table
9. **Turbo Tab** — Restyle turbo controls
10. **Config Tab** — Restyle form fields, sections

---

## Success Criteria

- All 9 tabs switch correctly (including `switchTab('gtt')` via pill switcher in Positions)
- Active nav highlight works on both top navbar and bottom tab bar
- `#page-title` updates on every tab switch
- Top nav on desktop (≥1024px), bottom tabs on tablet+mobile (<1024px)
- GTT reachable via pill switcher inside Positions tab
- Config accessible via gear icon on both nav layouts
- Consistent spacing (24px grid gaps, 20px card padding)
- All existing element IDs and dynamic CSS class aliases preserved
- Toast notifications clear the new fixed top navbar
- Mobile-first responsive; all touch targets ≥ 44px
- Smoke test checklist: tab switching, trading toggle, turbo toggle, GTT refresh, chart render, toast notifications, config save
