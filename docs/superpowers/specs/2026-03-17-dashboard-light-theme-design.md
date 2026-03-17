# Dashboard Light Theme Redesign — Design Spec
_Date: 2026-03-17_

## Summary

Restyle the Melon Trading Bot dashboard (`dashboard.html`) from its current dark theme to a clean, modern light theme. Zero feature loss — all 8 tabs, all navigation, all controls, tables, modals, and interactive elements are preserved exactly. Only the visual layer changes: color tokens, typography, spacing, card styles, badges, and buttons.

---

## Goals

- Replace dark CSS custom properties with a light design system
- Apply consistent typography hierarchy (stat numbers, section labels, body text)
- Polish card components: white backgrounds, subtle borders, proper shadows
- Restyle badges, pills, buttons, and status indicators for light mode
- Update charts (Chart.js) to use light-mode-appropriate colors
- Maintain full responsiveness (desktop sidebar + mobile bottom tab bar)
- Keep all JavaScript untouched — no logic changes

---

## Design System Tokens

Replace the `:root` block with the following light theme tokens:

```css
:root {
    /* Backgrounds */
    --c-bg:         #f0f2f5;
    --c-surface:    #ffffff;
    --c-surface-2:  #f8f9fa;
    --c-surface-3:  #f1f3f5;

    /* Borders */
    --c-border:     rgba(0,0,0,0.08);
    --c-border-2:   rgba(0,0,0,0.12);

    /* Text */
    --c-text:       #111827;
    --c-muted:      #6b7280;

    /* Semantic colors — darkened for light bg readability */
    --c-green:      #16a34a;
    --c-green-dim:  rgba(22,163,74,0.10);
    --c-red:        #dc2626;
    --c-red-dim:    rgba(220,38,38,0.10);
    --c-amber:      #d97706;
    --c-amber-dim:  rgba(217,119,6,0.10);
    --c-blue:       #2563eb;
    --c-blue-dim:   rgba(37,99,235,0.10);
    --c-purple:     #7c3aed;
    --c-purple-dim: rgba(124,58,237,0.10);

    /* Typography */
    --font-mono: 'JetBrains Mono', monospace;

    /* Transitions */
    --t-fast: 120ms ease;
    --t-med:  220ms ease;
    --t-slow: 380ms ease;

    /* Shadows */
    --shadow-card:  0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04);
    --shadow-green: 0 4px 24px rgba(22,163,74,0.15);

    /* Safe area insets */
    --sat: env(safe-area-inset-top);
    --sar: env(safe-area-inset-right);
    --sab: env(safe-area-inset-bottom);
    --sal: env(safe-area-inset-left);
}
```

---

## Component Changes

### Body & Base
- `body { background: var(--c-bg); color: var(--c-text); }`
- Remove `class="dark"` from `<html>` element
- Update `theme-color` meta to `#f0f2f5`
- Update `apple-mobile-web-app-status-bar-style` to `default`

### Scrollbar
```css
::-webkit-scrollbar-track { background: var(--c-surface-2); }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #9ca3af; }
```

### Glass / Surface Classes
Replace `.glass` dark backdrop with light card style:
```css
.glass {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    box-shadow: var(--shadow-card);
}
.glass-hover:hover {
    background: var(--c-surface-2);
    border-color: var(--c-border-2);
}
```

### Cards
```css
.card {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: 12px;
    box-shadow: var(--shadow-card);
}
/* Hover states — reduce shadow weight for light theme */
.card:hover     { border-color: var(--c-border-2); box-shadow: var(--shadow-card); }
.pos-card:hover { border-color: var(--c-border-2); box-shadow: var(--shadow-card); }
/* glass-hover green glow: remove dark-mode glow, use subtle border instead */
.glass-hover:hover { box-shadow: var(--shadow-card); border-color: var(--c-border-2); }
```

### Position Progress Track
```css
/* pos-track uses rgba(255,255,255,.07) which is invisible on light cards */
.pos-track { background: var(--c-surface-3); }
/* progress-step connector uses near-black — replace with border color */
.progress-step::after { background: var(--c-border-2); }
```

### Responsive Alerts Table (mobile)
```css
/* #incoming-alerts-body tr has hardcoded dark bg in @media (max-width: 768px) */
#incoming-alerts-body tr {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
}
```

### Modal Overlays
The two modal scrim overlays use inline `style="background:rgba(0,0,0,.65)"` — this is acceptable on both themes (dark scrim works on light bg). Keep as-is; no change required.

### Top Navbar (`.tnav-*`)
- Replace hardcoded `rgba(13,13,20,...)` background on `#top-navbar` with `var(--c-surface)`
- `border-bottom: 1px solid var(--c-border)`
- Logo text: `var(--c-text)`
- Nav links: `var(--c-muted)` default, `var(--c-text)` active
- `.tnav-btn.nav-item-active`: replace neon green (`#4ade80`/`#22c55e`) with `var(--c-blue)`

### Sidebar (desktop)
- Background: `var(--c-surface)`
- Border-right: `1px solid var(--c-border)`
- Nav items: hover background `var(--c-surface-2)`, active background `var(--c-blue-dim)`, active text `var(--c-blue)`
- `.nav-item::before` (active left indicator): replace `var(--c-green)` with `var(--c-blue)`

### Bottom Tab Bar (mobile)
- Replace hardcoded `rgba(13,13,20,...)` background on `#bottom-tab-bar` and `#mobile-top-bar` with `var(--c-surface)`
- Border-top: `1px solid var(--c-border)`
- `.btb-btn.nav-item-active`: replace neon green (`#4ade80`/`#22c55e`) icon + label color with `var(--c-blue)`

### Stat / Metric Cards
```css
.stat-card {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: 12px;
    box-shadow: var(--shadow-card);
}
/* Hero stat — P&L positive */
.stat-card.positive { border-left: 3px solid var(--c-green); }
/* Hero stat — P&L negative */
.stat-card.negative { border-left: 3px solid var(--c-red); }
```

### Badges / Pills
```css
/* Status badges — light-mode adjusted */
.badge-green  { background: var(--c-green-dim);  color: var(--c-green);  }
.badge-red    { background: var(--c-red-dim);    color: var(--c-red);    }
.badge-amber  { background: var(--c-amber-dim);  color: var(--c-amber);  }
.badge-blue   { background: var(--c-blue-dim);   color: var(--c-blue);   }
.badge-purple { background: var(--c-purple-dim); color: var(--c-purple); }
/* badge-gray uses white-channel bg which becomes invisible on light surface — fix: */
.badge-gray   { background: var(--c-surface-3);  color: var(--c-muted);  }
```

### Buttons
```css
.btn-primary {
    background: var(--c-blue);
    color: #fff;
    border: none;
    border-radius: 8px;
    font-weight: 600;
}
.btn-primary:hover { background: #1d4ed8; }

.btn-secondary {
    background: var(--c-surface-2);
    color: var(--c-text);
    border: 1px solid var(--c-border);
    border-radius: 8px;
    font-weight: 500;
}
.btn-secondary:hover { background: var(--c-surface-3); }

.btn-danger {
    background: var(--c-red-dim);
    color: var(--c-red);
    border: 1px solid rgba(220,38,38,0.2);
    border-radius: 8px;
    font-weight: 600;
}
.btn-danger:hover { background: var(--c-red); color: #fff; }
```

### Form Inputs / Selects
```css
input, select, textarea {
    background: var(--c-surface-2);
    border: 1px solid var(--c-border-2);
    color: var(--c-text);
    border-radius: 8px;
}
input:focus, select:focus {
    border-color: var(--c-blue);
    outline: none;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.12);
}
```

### Tables
```css
table { border-collapse: collapse; width: 100%; }
thead th {
    background: var(--c-surface-2);
    color: var(--c-muted);
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid var(--c-border);
    padding: 8px 12px;
}
tbody tr {
    border-bottom: 1px solid var(--c-border);
}
tbody tr:hover { background: var(--c-surface-2); }
tbody td { padding: 10px 12px; font-size: 0.8rem; color: var(--c-text); }
```

### Status Bar (Global System Status)
- Background: `var(--c-surface)`, border-bottom: `1px solid var(--c-border)`
- Status pills: use `var(--c-surface-2)` background, colored text per semantic color
- Live mode warning: `var(--c-amber-dim)` background, `var(--c-amber)` text

### Loading Screen
- Background: `var(--c-bg)`
- Loader ring: `var(--c-blue)` spinner
- Text: `var(--c-text)`

### Toast Notifications
Replace all four variant-specific hardcoded dark backgrounds and their title colors:
```css
.toast-success { background: #f0fdf4; border-left: 3px solid var(--c-green); }
.toast-error   { background: #fef2f2; border-left: 3px solid var(--c-red);   }
.toast-warning { background: #fffbeb; border-left: 3px solid var(--c-amber); }
.toast-info    { background: #eff6ff; border-left: 3px solid var(--c-blue);  }
/* All toast containers */
.toast { background: var(--c-surface); border: 1px solid var(--c-border); box-shadow: var(--shadow-card); color: var(--c-text); }
/* Variant title colors */
.toast-success .toast-title { color: var(--c-green); }
.toast-error   .toast-title { color: var(--c-red);   }
.toast-warning .toast-title { color: var(--c-amber); }
.toast-info    .toast-title { color: var(--c-blue);  }
```

### Charts (Chart.js)
Update per-chart instance color configs in the JS section (not global defaults — these are set inline per chart):
- `grid: { color: 'rgba(255,255,255,0.05)' }` → `grid: { color: 'rgba(0,0,0,0.06)' }` (all chart instances)
- `ticks: { color: ... }` → `ticks: { color: '#6b7280' }`
- Tooltip: `backgroundColor: '#ffffff', borderColor: 'rgba(0,0,0,0.1)', titleColor: '#111827', bodyColor: '#374151'`

### Typography Hierarchy (enforce consistently)
```css
/* Section label — "OPEN POSITIONS", "ALERTS TODAY" */
.section-label {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--c-muted);
}

/* Hero number — P&L, balance */
.hero-number {
    font-size: 2rem;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}

/* Mono price/ID values */
.mono-value {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-weight: 500;
}
```

---

## Scope Boundaries

**In scope:**
- All CSS inside `<style>` in `dashboard.html`
- `<html class="dark">` → remove `dark` class
- `theme-color` and status bar meta tags
- Chart.js color configuration in JS (grid/tick/tooltip colors only)
- Inline `style=` attributes that reference hardcoded dark colors

**Out of scope (do not change):**
- All JavaScript logic, API calls, event handlers
- HTML structure — no elements added, moved, or removed
- All 8 tabs and their content
- Sidebar navigation structure
- Mobile bottom tab bar item order
- Any Python/backend files

---

## File
- **Target file:** `/root/trading-bot/dashboard.html` (8234 lines)
- **Strategy:** Replace the `:root` token block, update component CSS classes systematically top-to-bottom, update Chart.js defaults in the JS section
- **No new files created**

---

## Success Criteria
1. Dashboard loads with light background (#f0f2f5), white cards
2. All 8 tabs fully functional and visually complete in light theme
3. P&L numbers render in green/red with correct weight and size
4. Sidebar and mobile nav both work correctly in light theme
5. All tables, forms, modals render correctly
6. Chart.js charts readable on light background
7. No dark-only artifacts (white text on white background, invisible borders)
