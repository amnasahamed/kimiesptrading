# `src/` Refactor Design Spec
**Date:** 2026-03-17
**Project:** Melon Trading Bot
**Goal:** Complete the partial `src/` refactor and retire `chartink_webhook.py` (6,016 lines) as the active entry point. `src/main.py` becomes the sole entry point.

---

## Approach

**Phased migration with single entry point (Approach C).**
`src/main.py` becomes the entry point from day one of the migration. Functionality is restored in six ordered phases, each leaving the bot fully operational. `chartink_webhook.py` is frozen (never run again) but not deleted until Phase 6.

---

## Architecture & File Structure

### Module Decisions (Wrap vs Absorb)

| Root module | Decision | Rationale |
|---|---|---|
| `calculator.py` | **Wrap** → `src/services/calculator_service.py` | Stable, well-contained math |
| `brokerage_calculator.py` + `margins.py` | **Wrap** → `src/services/brokerage_service.py` | Stable, no side effects; merge both |
| `kite.py` | **Absorb** → `src/services/kite_service.py` | Duplicate already exists in src/, consolidate |
| `signal_tracker.py` | **Absorb** → `src/repositories/signal_repository.py` | Fits existing repo pattern |
| `incoming_alerts.py` | **Absorb** → `src/repositories/alert_repository.py` | Fits existing repo pattern |
| `turbo_queue.py` | **Absorb** → `src/services/turbo_service.py` | Complex enough to be a service |
| `learning_engine.py` + `enhanced_learning.py` | **Absorb** → `src/services/learning_service.py` | Two files, one concern |
| `turbo_analyzer.py` | **Wrap** → called by `turbo_service.py` | 850 lines, stable internals |

### Target `src/` Structure

```
src/
├── main.py                          # App factory, lifespan, middleware
├── core/
│   ├── config.py                    # Pydantic settings (env vars) — exists
│   └── logging_config.py            # Structured logging — exists
├── models/
│   └── database.py                  # SQLAlchemy models — expand with 3 new tables
├── repositories/
│   ├── position_repository.py       # exists
│   ├── trade_repository.py          # exists
│   ├── signal_repository.py         # NEW — absorb signal_tracker.py
│   └── alert_repository.py          # NEW — absorb incoming_alerts.py
├── services/
│   ├── kite_service.py              # exists — absorb kite.py
│   ├── risk_service.py              # exists — expand to full 5-step validation
│   ├── trading_service.py           # exists — expand
│   ├── calculator_service.py        # NEW wrapper — calculator.py
│   ├── brokerage_service.py         # NEW wrapper — brokerage_calculator.py + margins.py
│   ├── notification_service.py      # NEW — Telegram + WhatsApp
│   ├── turbo_service.py             # NEW — absorb turbo_queue.py, wrap turbo_analyzer.py
│   ├── learning_service.py          # NEW — absorb learning_engine.py + enhanced_learning.py
│   └── position_service.py          # NEW — clubbing, GTT monitoring, sync logic
├── api/routes/
│   ├── trading.py                   # exists — expand
│   ├── webhook.py                   # NEW — ChartInk webhook handler
│   ├── config.py                    # NEW — GET/POST /api/config
│   ├── analytics.py                 # NEW — insights, learning, strategy endpoints
│   ├── alerts.py                    # NEW — incoming alerts endpoints
│   ├── turbo.py                     # NEW — turbo status/cleanup endpoints
│   └── ui.py                        # NEW — dashboard HTML, debug pages
├── scripts/
│   └── migrate_json_to_db.py        # NEW — one-time JSON → SQLite migration
└── tests/
    ├── conftest.py
    ├── test_risk_service.py
    ├── test_trading_service.py
    └── test_webhook.py
```

### New Database Tables
Three tables added to `src/models/database.py`:

- **`insights`** — per-symbol trade analytics (replaces `trade_insights.json`)
- **`turbo_queue`** — multi-timeframe signal queue (replaces `turbo_queue.json`)
- **`error_log`** — centralized error tracking (replaces `error_log.json`)

---

## Phases

Each phase ends with: tests pass, bot runs on `src/`, changes committed.

### Phase 1 — Foundation
- Add 3 new DB tables to `models/database.py`
- Write `src/scripts/migrate_json_to_db.py` (idempotent, dry-run flag)
- Migrate: `trades_log.json`, `positions.json`, `signals_log.json`, `incoming_alerts.json`, `trade_insights.json`, `config.json`
- Add `src/api/routes/config.py` — `GET /api/config`, `POST /api/config`
- Add `src/api/routes/ui.py` — serve `dashboard.html`, debug pages, kite-login
- Wire all routes into `src/main.py`
- **Bot operational:** yes (reduced feature set — no webhook trading yet)

### Phase 2 — Core Trading Path
- Create `src/repositories/signal_repository.py` (absorb `signal_tracker.py`)
- Create `src/repositories/alert_repository.py` (absorb `incoming_alerts.py`)
- Create `src/services/calculator_service.py` (wrap `calculator.py`)
- Create `src/services/brokerage_service.py` (wrap `brokerage_calculator.py` + `margins.py`)
- Create `src/services/notification_service.py` (Telegram + WhatsApp)
- Expand `src/services/risk_service.py` to full 5-step validation:
  1. Trading window check
  2. Nifty health check
  3. Duplicate signal check
  4. Max position limit
  5. Price slippage check
- Create `src/api/routes/webhook.py` — `POST /webhook/chartink`, `GET /webhook/chartink`
- Expand `src/services/trading_service.py` — full paper + live order execution
- Write tests: `test_risk_service.py`, `test_trading_service.py`, `test_webhook.py`
- **Bot operational:** yes (full trading restored)

### Phase 3 — Position Management
- Create `src/services/position_service.py`:
  - Position clubbing (average multiple entries)
  - GTT order monitoring (background task)
  - Sync positions with Kite
  - Force-close position
- Add routes to `src/api/routes/trading.py`:
  - `POST /api/positions/sync`
  - `POST /api/positions/{id}/force-close`
  - `GET /api/positions/kite-debug`
  - `GET /api/gtt-orders`
  - `POST /api/gtt/cleanup`
- **Bot operational:** yes + richer position management

### Phase 4 — Analytics & Learning
- Create `src/services/learning_service.py` (absorb `learning_engine.py` + `enhanced_learning.py`)
- Add `src/api/routes/analytics.py`:
  - `GET /api/insights`, `GET /api/insights/{symbol}`
  - `GET /api/learning/report`, `/summary`, `/symbols`, `/signals`, `/time-patterns`, `/recommendations`
  - `GET /api/strategy/analytics`, `POST /api/strategy/apply`, `/custom`, `/reset`
  - `GET /api/strategy/history`
  - `GET /api/stats`
- **Bot operational:** yes + full analytics

### Phase 5 — Turbo Mode
- Create `src/services/turbo_service.py` (absorb `turbo_queue.py`, wrap `turbo_analyzer.py`)
- Add `src/api/routes/turbo.py`:
  - `GET /api/turbo/status`
  - `POST /api/turbo/cleanup`
- Wire turbo processor as background lifespan task in `src/main.py`
- **Bot operational:** yes + turbo confirmed

### Phase 6 — Cleanup
- Pre-cleanup: `cp chartink_webhook.py chartink_webhook.py.archive`
- Delete: `chartink_webhook.py`, `kite.py`, `signal_tracker.py`, `incoming_alerts.py`, `turbo_queue.py`, `learning_engine.py`, `enhanced_learning.py`, `turbo_analyzer.py`, `margins.py`
- Keep as reference: `calculator.py`, `brokerage_calculator.py` (wrapped, not deleted until stable)
- Final smoke test against all tabs in `dashboard.html`
- **Bot operational:** yes, clean

---

## Data Migration

**Script:** `src/scripts/migrate_json_to_db.py`

| Source file | Target table |
|---|---|
| `trades_log.json` | `trades` |
| `positions.json` | `positions` |
| `signals_log.json` | `signals` |
| `incoming_alerts.json` | `incoming_alerts` |
| `trade_insights.json` | `insights` |
| `config.json` | `config` table + `.env` |

Properties:
- **Idempotent** — upserts, safe to re-run
- **Dry-run flag** — `--dry-run` previews without writing
- **Summary output** — `N migrated, M skipped, K errors`
- **Archives** — original JSON files renamed to `.bak` after successful migration

**Cutover procedure:**
1. `python src/scripts/migrate_json_to_db.py` — verify output
2. Stop monolith: `kill $(lsof -ti:8000)`
3. Start new: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
4. Smoke test critical endpoints
5. Monitor for 10 minutes

---

## Testing Strategy

Tests cover the critical trading path only — the logic that decides whether a trade is placed.

### `tests/conftest.py`
- In-memory SQLite fixture
- Mock `KiteService` (no real API calls)
- Sample signal payloads: valid, invalid, duplicate, out-of-hours

### `tests/test_risk_service.py`
- Rejects signals outside trading windows
- Rejects when max positions reached
- Rejects duplicate signals
- Rejects when daily loss limit hit
- Rejects when Nifty below threshold
- Passes valid signals through

### `tests/test_trading_service.py`
- Paper trade creates position record
- Live trade calls `kite_service.place_order` with correct params
- Position clubbing merges correctly
- Close position updates DB and calls Kite

### `tests/test_webhook.py`
- Valid ChartInk payload → trade executed
- Invalid secret → 401
- Malformed payload → 422
- Trading disabled → signal logged, not traded
- Rate limit exceeded → 429

### Not tested (out of scope)
- Telegram/WhatsApp (mocked at boundary)
- Turbo internals (covered by manual smoke test)
- Learning engine (no critical path risk)
- All read-only analytics endpoints

---

## Rollback Strategy

**Before cutover:** `chartink_webhook.py` is never modified. To revert:
```bash
uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000
```
JSON files are untouched until Phase 6.

**After cutover:** Each phase is a separate git commit. Roll back any phase:
```bash
git checkout <phase-N-commit> -- src/
uvicorn src.main:app
```

**Before Phase 6 (point of no return):**
```bash
cp trading.db trading.db.pre-cleanup.bak
cp chartink_webhook.py chartink_webhook.py.archive
```

---

## Success Criteria

- All 62 routes from `chartink_webhook.py` reimplemented in `src/`
- `chartink_webhook.py` never runs after Phase 1 cutover
- All critical-path tests pass (`pytest src/tests/ -v`)
- Dashboard fully functional on `src/` (all 8 tabs)
- Turbo mode, learning engine, GTT monitoring all operational
- Monolith and root-level module stubs deleted in Phase 6
- No JSON files used at runtime (SQLite only)
