# Dashboard Light Theme Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle `dashboard.html` from dark to a clean light theme using a new CSS design system — zero feature loss, all 8 tabs and navigation intact, no JS logic changes.

**Architecture:** All changes are confined to the CSS `<style>` block and two Chart.js color strings inside the `<script>` block of `dashboard.html`. The `:root` token block is replaced first, then each component section is updated top-to-bottom. No new files are created.

**Tech Stack:** Pure CSS custom properties, Chart.js (inline config), HTML5

---

## Chunk 1: Token Replacement & Base Styles

### Task 1: Replace `:root` design tokens

**Files:**
- Modify: `dashboard.html:31-71` (`:root` block)

- [ ] **Step 1: Replace the `:root` block**

  Find the existing `:root { ... }` block starting at line 31 and replace it entirely with:

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

- [ ] **Step 2: Update `<html>` element and meta tags**

  - Change `<html lang="en" class="dark">` → `<html lang="en">`
  - Change `<meta name="theme-color" content="#0f1117">` → `<meta name="theme-color" content="#f0f2f5">`
  - Change `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">` → `<meta name="apple-mobile-web-app-status-bar-style" content="default">`

- [ ] **Step 3: Update scrollbar styles**

  Find the `::-webkit-scrollbar` block and replace with:

  ```css
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: var(--c-surface-2); }
  ::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #9ca3af; }
  ```

- [ ] **Step 4: Update `body` base styles**

  Find `body { background: var(--c-bg); ... }` and ensure it reads:
  ```css
  body {
      background: var(--c-bg);
      color: var(--c-text);
      overscroll-behavior-y: none;
  }
  ```
  This is required so the base background and text color respond to the new tokens immediately.

- [ ] **Step 5: Update glass surface classes**

  Find `.glass { ... }` and `.glass-hover:hover { ... }` and replace with:

  ```css
  .glass {
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      box-shadow: var(--shadow-card);
  }
  .glass-hover:hover {
      background: var(--c-surface-2);
      border-color: var(--c-border-2);
      box-shadow: var(--shadow-card);
  }
  ```

- [ ] **Step 6: Update card and stat-card hover states**

  Find `.card:hover { ... }`, `.pos-card:hover { ... }`, and `.stat-card:hover { ... }` and replace each:

  ```css
  .card:hover {
      border-color: var(--c-border-2);
      box-shadow: var(--shadow-card);
  }
  .pos-card:hover {
      border-color: var(--c-border-2);
      box-shadow: var(--shadow-card);
      transform: translateY(-1px);
  }
  .stat-card:hover {
      border-color: var(--c-border-2);
      box-shadow: var(--shadow-card);
      transform: translateY(-1px);
  }
  ```

  Note: `.card` base (`background: var(--c-surface); border: 1px solid var(--c-border)`) already uses tokens and requires no change — only the hover rules have hardcoded green/dark values.

- [ ] **Step 7: Verify in browser**

  Open `https://coolify.themelon.in` (or `http://185.193.66.177:8000`). The page background should now be light grey (`#f0f2f5`). Cards will still show dark text as the tokens are now light. Some elements may still look dark — that is expected; subsequent tasks fix each component.

- [ ] **Step 8: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: replace dark CSS tokens with light design system root"
  ```

---

### Task 2: Navigation — Top Navbar, Mobile Bar, Bottom Tab Bar

**Files:**
- Modify: `dashboard.html` — CSS blocks for `#top-navbar`, `#mobile-top-bar`, `#bottom-tab-bar`, `.tnav-btn`, `.nav-item::before`, `.btb-btn`

- [ ] **Step 1: Update `#top-navbar` background and border**

  Find `#top-navbar { ... }` CSS block. Replace the `background` and `backdrop-filter` lines:
  ```css
  background: rgba(13,13,20,.95);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--c-border);
  ```
  with:
  ```css
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-border);
  ```
  (Remove the `backdrop-filter` line entirely — not needed on light theme.)

- [ ] **Step 2: Update `#mobile-top-bar` background and border**

  Find `#mobile-top-bar { ... }` CSS block. Replace:
  ```css
  background: rgba(13,13,20,.95);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--c-border);
  ```
  with:
  ```css
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-border);
  ```

- [ ] **Step 3: Update `#bottom-tab-bar` background and border**

  Find `#bottom-tab-bar { ... }` CSS block. Replace:
  ```css
  background: rgba(13,13,20,.97);
  border-top: 1px solid var(--c-border);
  ```
  with:
  ```css
  background: var(--c-surface);
  border-top: 1px solid var(--c-border);
  ```

- [ ] **Step 4: Update top nav active button style**

  Find `.tnav-btn.nav-item-active { ... }` and replace with:

  ```css
  .tnav-btn.nav-item-active {
      background: var(--c-blue-dim);
      color: var(--c-blue);
      border-color: rgba(37,99,235,0.2);
  }
  ```

  Also update `.tnav-btn:hover`:
  ```css
  .tnav-btn:hover {
      background: var(--c-surface-2);
      color: var(--c-text);
  }
  ```

- [ ] **Step 5: Update nav-item active indicator (left bar)**

  Find `.nav-item::before { ... }`. Replace:
  ```css
  background: var(--c-green);
  ```
  with:
  ```css
  background: var(--c-blue);
  ```

- [ ] **Step 6: Update bottom tab bar active state**

  Find `.btb-btn.nav-item-active { color: #4ade80; }` and `.btb-btn.nav-item-active i { color: #22c55e; }`.
  Replace both with:
  ```css
  .btb-btn.nav-item-active { color: var(--c-blue); }
  .btb-btn.nav-item-active i { color: var(--c-blue); }
  ```

- [ ] **Step 7: Confirm sidebar border-right**

  The sidebar `<aside id="sidebar">` already has `style="background:var(--c-surface);border-right:1px solid var(--c-border)"` as an inline style — it uses tokens correctly. No CSS change required, but verify visually that the sidebar-to-content separator is visible on the light theme.

- [ ] **Step 8: Verify in browser**

  Top navbar, mobile bar, and bottom tab bar should now show white backgrounds. Active tab indicator should be blue, not green.

- [ ] **Step 9: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: light theme nav — top bar, mobile bar, bottom tabs, active states"
  ```

---

## Chunk 2: Component Styles

### Task 3: Badges, Buttons, Forms

**Files:**
- Modify: `dashboard.html` — `.badge-*`, `.btn-*`, `input`/`select`/`textarea` CSS blocks

- [ ] **Step 1: Update all badge variants including badge-gray**

  Find each `.badge-*` rule. Replace the entire badge section with:

  ```css
  .badge-green  { background: var(--c-green-dim);  color: var(--c-green);  }
  .badge-red    { background: var(--c-red-dim);    color: var(--c-red);    }
  .badge-amber  { background: var(--c-amber-dim);  color: var(--c-amber);  }
  .badge-blue   { background: var(--c-blue-dim);   color: var(--c-blue);   }
  .badge-purple { background: var(--c-purple-dim); color: var(--c-purple); }
  .badge-gray   { background: var(--c-surface-3);  color: var(--c-muted);  }
  ```

  Note: `.badge-gray` previously used `rgba(255,255,255,.08)` which is invisible on a light surface.

- [ ] **Step 2: Update `.btn-primary`**

  Find `.btn-primary { ... }` and update:
  ```css
  .btn-primary {
      background: var(--c-blue);
      color: #fff;
      border: none;
      border-radius: 8px;
      font-weight: 600;
  }
  .btn-primary:hover { background: #1d4ed8; }
  ```

- [ ] **Step 3: Update `.btn-secondary`**

  ```css
  .btn-secondary {
      background: var(--c-surface-2);
      color: var(--c-text);
      border: 1px solid var(--c-border);
      border-radius: 8px;
      font-weight: 500;
  }
  .btn-secondary:hover { background: var(--c-surface-3); }
  ```

- [ ] **Step 4: Update `.btn-danger`**

  ```css
  .btn-danger {
      background: var(--c-red-dim);
      color: var(--c-red);
      border: 1px solid rgba(220,38,38,0.2);
      border-radius: 8px;
      font-weight: 600;
  }
  .btn-danger:hover { background: var(--c-red); color: #fff; }
  ```

- [ ] **Step 5: Update form inputs**

  Find `input, select, textarea { ... }` block and update background/border/color:
  ```css
  input, select, textarea {
      background: var(--c-surface-2);
      border: 1px solid var(--c-border-2);
      color: var(--c-text);
      border-radius: 8px;
  }
  input:focus, select:focus, textarea:focus {
      border-color: var(--c-blue);
      outline: none;
      box-shadow: 0 0 0 3px rgba(37,99,235,0.12);
  }
  ```

- [ ] **Step 6: Verify in browser**

  Navigate to the Config tab. Verify: form inputs have light background with visible border, buttons render correctly (blue primary, grey secondary, red danger). Badges visible in positions/alerts tabs.

- [ ] **Step 7: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: light theme badges, buttons, form inputs"
  ```

---

### Task 4: Tables, Status Bar, Loading Screen

**Files:**
- Modify: `dashboard.html` — table CSS, `#system-status-bar`, loading screen, `#incoming-alerts-body` responsive block

- [ ] **Step 1: Update table styles**

  Find the table/thead/tbody CSS and update:
  ```css
  thead th {
      background: var(--c-surface-2);
      color: var(--c-muted);
      border-bottom: 1px solid var(--c-border);
  }
  tbody tr { border-bottom: 1px solid var(--c-border); }
  tbody tr:hover { background: var(--c-surface-2); }
  tbody td { color: var(--c-text); }
  ```

- [ ] **Step 2: Fix responsive alerts table card (mobile)**

  Find the `@media (max-width: 768px)` block containing `#incoming-alerts-body tr`. Replace:
  ```css
  background: rgba(26, 26, 37, 0.8);
  border: 1px solid rgba(255,255,255,0.05);
  ```
  with:
  ```css
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  ```

- [ ] **Step 3: Update `#system-status-bar`**

  Find `#system-status-bar { ... }` and ensure:
  ```css
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-border);
  ```

- [ ] **Step 4: Update loading screen**

  The loading screen (`#loading-screen`) already uses `style="background:var(--c-bg)"` inline — it will automatically pick up the new light token. However the spinner and icon use Tailwind-like classes (`border-t-primary-500`, `text-primary-400`) which resolve to `var(--c-green)` via utility classes at lines ~1630/1934. Update the `.loader-ring` animation to use blue instead of green:

  Find `.loader-ring { animation: spinGlow ... }` and the `@keyframes spinGlow` block. Replace:
  ```css
  @keyframes spinGlow {
      0%   { box-shadow: 0 0 0 0 rgba(34,197,94,.4); }
      50%  { box-shadow: 0 0 20px 4px rgba(34,197,94,.2); }
      100% { box-shadow: 0 0 0 0 rgba(34,197,94,.4); }
  }
  ```
  with:
  ```css
  @keyframes spinGlow {
      0%   { box-shadow: 0 0 0 0 rgba(37,99,235,.3); }
      50%  { box-shadow: 0 0 16px 3px rgba(37,99,235,.15); }
      100% { box-shadow: 0 0 0 0 rgba(37,99,235,.3); }
  }
  ```

  Update ALL `primary-*` utility classes to shift the accent from green to blue. Find and replace each of the following (spread across ~lines 1630–1970):

  ```css
  /* Text */
  .text-primary-400               { color: var(--c-blue); }
  .hover\:text-primary-400:hover  { color: var(--c-blue); }

  /* Backgrounds */
  .bg-primary-500                 { background-color: var(--c-blue); }
  .bg-primary-500\/10             { background-color: rgba(37,99,235,0.08); }
  .bg-primary-500\/20             { background-color: rgba(37,99,235,0.20); }
  .bg-primary-500\/30             { background-color: rgba(37,99,235,0.25); }
  .hover\:bg-primary-500\/30:hover { background-color: rgba(37,99,235,0.15); }

  /* Borders */
  .border-primary-500             { border-color: var(--c-blue); }
  .border-primary-500\/20         { border-color: rgba(37,99,235,0.2); }
  .border-primary-500\/30         { border-color: rgba(37,99,235,0.3); }
  .border-primary-500\/50         { border-color: rgba(37,99,235,0.5); }
  .border-t-primary-500           { border-top-color: var(--c-blue); }
  .hover\:border-primary-500\/30:hover { border-color: rgba(37,99,235,0.3); }
  .hover\:border-primary-500\/50:hover { border-color: rgba(37,99,235,0.5); }
  ```

  This globally shifts the "primary" accent from green to blue throughout the dashboard, consistent with the light theme design direction.

- [ ] **Step 5: Verify in browser**

  Hard-refresh the page to catch the loading screen. Verify: loading spinner is blue, tables have light header rows, row hover is light grey, system status bar is white with border.

- [ ] **Step 6: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: light theme tables, status bar, loading screen, primary accent blue"
  ```

---

### Task 5: Toast Notifications

**Files:**
- Modify: `dashboard.html` — `.toast`, `.toast-success/error/warning/info` CSS blocks (~lines 1111–1179)

- [ ] **Step 1: Update base `.toast` styles**

  Find `.toast { ... }` (the block at ~line 1111, not the responsive override at ~line 975). Update:
  ```css
  .toast {
      background: var(--c-surface);
      border: 1px solid var(--c-border);
      box-shadow: var(--shadow-card);
      color: var(--c-text);
  }
  ```

- [ ] **Step 2: Update `.toast-success`**

  Replace the hardcoded dark background:
  ```css
  .toast-success { background: #f0fdf4; border-left: 3px solid var(--c-green); }
  .toast-success .toast-title { color: var(--c-green); }
  .toast-success .toast-progress { background: var(--c-green); }
  ```

- [ ] **Step 3: Update `.toast-error`**

  ```css
  .toast-error { background: #fef2f2; border-left: 3px solid var(--c-red); }
  .toast-error .toast-title { color: var(--c-red); }
  .toast-error .toast-progress { background: var(--c-red); }
  ```

- [ ] **Step 4: Update `.toast-warning`**

  ```css
  .toast-warning { background: #fffbeb; border-left: 3px solid var(--c-amber); }
  .toast-warning .toast-title { color: var(--c-amber); }
  .toast-warning .toast-progress { background: var(--c-amber); }
  ```

- [ ] **Step 5: Update `.toast-info`**

  ```css
  .toast-info { background: #eff6ff; border-left: 3px solid var(--c-blue); }
  .toast-info .toast-title { color: var(--c-blue); }
  .toast-info .toast-progress { background: var(--c-blue); }
  ```

- [ ] **Step 6: Verify in browser**

  Trigger a toast: go to Config tab, click any Save button. Verify the toast has a tinted light background (green tint for success), dark text, and the correct colored title.

- [ ] **Step 7: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: light theme toast notifications — all four variants"
  ```

---

## Chunk 3: Position Components & Chart.js

### Task 6: Position Track and Progress Steps

**Files:**
- Modify: `dashboard.html` — `.pos-track`, `.progress-step::after` CSS blocks

- [ ] **Step 1: Fix position SL→TP progress track**

  Find `.pos-track { ... }`. Replace:
  ```css
  background: rgba(255,255,255,.07);
  ```
  with:
  ```css
  background: var(--c-surface-3);
  ```

- [ ] **Step 2: Fix progress step connector line**

  Find `.progress-step::after { ... }`. Replace:
  ```css
  background: #1a1a25;
  ```
  with:
  ```css
  background: var(--c-border-2);
  ```

  Also find `.progress-step.completed::after` and keep:
  ```css
  .progress-step.completed::after { background: var(--c-green); }
  ```

- [ ] **Step 3: Fix pos-track-dot border**

  Find `.pos-track-dot { ... }`. Replace:
  ```css
  border: 2px solid var(--c-bg);
  ```
  with:
  ```css
  border: 2px solid var(--c-surface);
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: light theme position track and progress step connector"
  ```

---

### Task 7: Chart.js Colors

**Files:**
- Modify: `dashboard.html` — chart config in `<script>` block (~lines 4862–4866)

- [ ] **Step 1: Update equity chart grid/tick colors**

  Find the chart `scales` config block containing:
  ```js
  grid: { color: 'rgba(255,255,255,0.05)' },
  ticks: { color: '#6b7280', font: { size: 10 } }
  ```
  (appears twice, for x and y axes)

  Replace both `grid` values:
  ```js
  grid: { color: 'rgba(0,0,0,0.06)' },
  ```
  Leave `ticks: { color: '#6b7280' }` — this value is already correct for light theme.

- [ ] **Step 2: Add tooltip styling to equity chart**

  Find the equity chart's `plugins.tooltip` block (currently only has `callbacks`). Expand it to:
  ```js
  tooltip: {
      backgroundColor: '#ffffff',
      borderColor: 'rgba(0,0,0,0.1)',
      borderWidth: 1,
      titleColor: '#111827',
      bodyColor: '#374151',
      callbacks: {
          label: (context) => '₹' + context.parsed.y.toLocaleString('en-IN')
      }
  }
  ```
  Without this, Chart.js defaults to a dark tooltip background (`rgba(0,0,0,0.8)`) which would look out of place on the light theme.

- [ ] **Step 3: Update win/loss doughnut chart legend**

  Find the doughnut chart's `legend.labels` config:
  ```js
  labels: { color: '#9ca3af', padding: 20 }
  ```
  This value is fine for light theme — no change needed.

- [ ] **Step 4: Update doughnut chart colors for light theme visibility**

  Find `backgroundColor: ['#22c55e', '#ef4444']` in the win/loss chart.
  Replace with the darkened light-theme variants:
  ```js
  backgroundColor: ['#16a34a', '#dc2626']
  ```

- [ ] **Step 5: Verify charts in browser**

  Open Dashboard tab. Verify: equity chart has visible light gridlines, chart tooltip appears white with dark text on hover, win/loss doughnut uses correct darkened green/red colors.

- [ ] **Step 6: Commit**

  ```bash
  git add dashboard.html
  git commit -m "style: light theme Chart.js grid, tooltip, and chart colors"
  ```

> **Note on typography utility classes** (`.section-label`, `.hero-number`, `.mono-value`): These are listed in the spec as additive CSS classes. They do not currently exist in `dashboard.html` and applying them would require HTML edits across hundreds of elements — out of scope for this CSS-only restyle. Adding the CSS rules without applying them in HTML has no effect. These are deferred to a follow-up pass if fine-grained typography polish is desired.

---

## Chunk 4: Final Sweep & Verification

### Task 8: Smoke Test All 8 Tabs

- [ ] **Step 1: Open dashboard in browser**

  Open `https://coolify.themelon.in`. Verify:
  - Page background is light grey (`#f0f2f5`)
  - Top navbar is white with dark text
  - Dashboard (tab 1) shows white cards on grey background

- [ ] **Step 2: Check Dashboard tab**

  Verify: Trading windows card, turbo toggle, risk overview, live trade feed, stats cards, charts all readable. P&L numbers in green/red. Charts have visible gridlines.

- [ ] **Step 3: Check Positions tab**

  Verify: Position cards render on white background, SL→TP progress track visible, badge colors correct, action buttons styled.

- [ ] **Step 4: Check GTT Orders tab**

  Verify: GTT list renders on white cards, status badges visible.

- [ ] **Step 5: Check Trades tab**

  Verify: Table renders with light header row, row hover works, P&L column colored correctly.

- [ ] **Step 6: Check Analytics tab**

  Verify: All analytics cards render on white, charts readable.

- [ ] **Step 7: Check Alerts tab**

  Verify: Alert table renders, stat cards visible. On mobile (resize window <768px), alert rows should show as white cards not dark cards.

- [ ] **Step 8: Check Turbo tab**

  Verify: Queue cards, signal history table, status legend all visible on light background.

- [ ] **Step 9: Check Learning tab**

  Verify: Key metrics, recommendations, strategy editor, symbol performance all render correctly. Purple accent used for learning engine headers.

- [ ] **Step 10: Check Config tab**

  Verify: All form inputs visible (light background with border), save buttons styled correctly.

- [ ] **Step 11: Test toast notification**

  Trigger a toast by clicking any save button in Config. Verify the toast appears with the correct light variant background (green toast for success, not dark).

- [ ] **Step 12: Check mobile layout**

  Resize browser to <1024px. Verify: bottom tab bar is white with correct active blue indicator, mobile top bar is white.

- [ ] **Step 13: Final commit**

  ```bash
  git add dashboard.html
  git commit -m "style: dashboard light theme — complete restyle with design system"
  ```
