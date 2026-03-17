# `src/` Refactor Design Spec
**Date:** 2026-03-17
**Project:** Melon Trading Bot
**Goal:** Complete the partial `src/` refactor and retire `chartink_webhook.py` (6,016 lines) as the active entry point. `src/main.py` becomes the sole entry point.

---

## Approach

**Phased migration with single entry point (Approach C).**
`src/main.py` becomes the entry point from day one of the migration. Functionality is restored in six ordered phases, each leaving the bot fully operational. `chartink_webhook.py` is frozen (never run again) but not deleted until Phase 6.

**CRITICAL — Timing constraint:** Phase 1 and Phase 2 must be deployed as a single unit, outside market hours (before 9:15 IST or after 15:30 IST). Phase 1 alone leaves the webhook handler returning 404 — all ChartInk signals are dropped. Never deploy Phase 1 without immediately completing Phase 2 in the same session.

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
│   └── ui.py                        # NEW — dashboard HTML, debug/upload pages
├── scripts/
│   └── migrate_json_to_db.py        # NEW — one-time JSON → SQLite migration
└── tests/
    ├── conftest.py
    ├── test_risk_service.py
    ├── test_trading_service.py
    └── test_webhook.py
```

### Database Tables

**Existing tables** (already in `src/models/database.py`):
- `positions`
- `trades`
- `signals`
- `incoming_alerts`

**New tables** (added to `src/models/database.py` in Phase 1):
- **`insights`** — per-symbol trade analytics (replaces `trade_insights.json`)
- **`turbo_queue`** — multi-timeframe signal queue (replaces `turbo_queue.json`)
- **`error_log`** — centralized error tracking (replaces `error_log.json`)

Note: `config.json` is migrated to `.env` file only (not a DB table). `src/core/config.py` already reads from environment variables via Pydantic Settings — this is the canonical config location.

### Deployment Constraint: SQLite + Single Worker
SQLite is not safe for multiple concurrent writer processes. Production must run with `--workers 1`:
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
```
Fix the `workers=1 if debug else 4` line in `src/main.py` to always use 1 until/unless the project migrates to PostgreSQL with WAL mode.

### Repository Interface Sketch
These method signatures must exist on Phase 2 deliverables so Phase 3 can depend on them:

**`signal_repository.py`** (needed by `position_service.py` in Phase 3):
```python
async def record_signal(db, symbol, scan_name, signal_type, ...) -> Signal
async def is_duplicate(db, symbol, scan_name, within_minutes=5) -> bool
async def get_today_signals(db) -> list[Signal]
async def get_stats(db) -> dict
```

**`alert_repository.py`** (needed by analytics routes in Phase 4):
```python
async def record_alert(db, ...) -> IncomingAlert
async def update_status(db, alert_id, status, ...) -> None
async def get_recent(db, limit=100) -> list[IncomingAlert]
async def get_stats(db) -> dict
async def get_by_symbol(db, symbol) -> list[IncomingAlert]
async def get_by_scan(db, scan_name) -> list[IncomingAlert]
async def get_today(db) -> list[IncomingAlert]
```

### dashboard.html API Compatibility Constraint
`dashboard.html` has ~245 element IDs and makes 24 distinct API calls. **All existing API endpoint paths, HTTP methods, and JSON response field names used by `dashboard.html` must be preserved exactly.** Do not rename routes, change HTTP methods, or rename response keys during refactoring. Verify each route against `dashboard.html` before marking a phase complete.

---

## Phases

Each phase ends with: tests pass, bot runs on `src/`, changes committed.

### Phase 1 — Foundation *(deploy together with Phase 2 — see timing constraint)*
- Add 3 new DB tables to `models/database.py`: `insights`, `turbo_queue`, `error_log`
- Write `src/scripts/migrate_json_to_db.py` (idempotent, dry-run flag)
- Add `src/api/routes/config.py`:
  - `GET /api/config`
  - `POST /api/config`
- Add `src/api/routes/ui.py`:
  - `GET /` — serve `dashboard.html`
  - `GET /dashboard` — serve `dashboard.html`
  - `GET /test-cors` — CORS test page
  - `GET /esp-setup` — ESP hardware setup page
  - `GET /kite-login` — Kite login page
  - `GET /debug` — debug page
  - `GET /upload` — file upload form
  - `POST /api/upload` — file upload handler
  - `GET /api/uploaded-files` — list uploaded files
- Wire all routes into `src/main.py`
- **Bot operational:** yes (reduced feature set — webhook trading not yet restored; deploy Phase 2 immediately)

### Phase 2 — Core Trading Path *(deploy immediately after Phase 1)*
- Create `src/repositories/signal_repository.py` (absorb `signal_tracker.py`) — see interface sketch above
- Create `src/repositories/alert_repository.py` (absorb `incoming_alerts.py`) — see interface sketch above
- Create `src/services/calculator_service.py` (wrap `calculator.py`)
- Create `src/services/brokerage_service.py` (wrap `brokerage_calculator.py` + `margins.py`)
- Create `src/services/notification_service.py` (Telegram + WhatsApp)
- Expand `src/services/risk_service.py` to full 5-step validation:
  1. Trading window check
  2. Nifty health check
  3. Duplicate signal check (uses `signal_repository.is_duplicate`)
  4. Max position limit
  5. Price slippage check
- Create `src/api/routes/webhook.py`:
  - `POST /webhook/chartink` — main webhook receiver
  - `POST /webhook/chartink/form` — form-based webhook
  - `GET /webhook/chartink` — webhook status
- Expand `src/services/trading_service.py` — full paper + live order execution
- Pre-existing routes in `src/api/routes/trading.py` (already exist, verify correctness only — count toward 58):
  - `POST /api/trade` — execute single trade
  - `POST /api/positions/{id}/close` — close position
  - `GET /api/portfolio` — portfolio summary
- Add to `src/api/routes/trading.py`:
  - `POST /api/reset-daily` — reset daily trade state
  - `GET /api/kite/funds` — (partially exists, complete it)
  - `GET /api/quote/{symbol}` — (partially exists, complete it)
  - `GET /api/signals` — signal history
  - `POST /api/signals/clear` — clear signal history
  - `GET /api/stats` — trading statistics
  - `POST /api/test-telegram` — test Telegram notification
  - `POST /api/test-whatsapp` — test WhatsApp notification
- Add to `src/api/routes/config.py`:
  - `POST /api/test-kite` — test Kite connectivity
- Write tests: `test_risk_service.py`, `test_trading_service.py`, `test_webhook.py`
- **Bot operational:** yes (full trading restored)

### Phase 3 — Position Management
- Create `src/services/position_service.py`:
  - Position clubbing (average multiple entries)
  - GTT order monitoring (background task)
  - Sync positions with Kite
  - Force-close position
  - ESP last-alert state (stored in app state via FastAPI lifespan, not DB — single-process safe)
- Add routes to `src/api/routes/trading.py`:
  - `POST /api/positions/sync`
  - `POST /api/positions/{id}/force-close`
  - `POST /api/positions/{id}/modify-sl`
  - `GET /api/positions/kite-debug`
  - `GET /api/gtt-orders`
  - `POST /api/gtt/cleanup`
  - `POST /api/sync-kite`
  - `GET /api/esp/stats`
  - `GET /api/esp/positions`
  - `GET /api/esp/alert`
- **Bot operational:** yes + richer position management

### Phase 4 — Analytics & Learning
- Create `src/services/learning_service.py` (absorb `learning_engine.py` + `enhanced_learning.py`)
- Add `src/api/routes/analytics.py`:
  - `GET /api/insights`, `GET /api/insights/{symbol}`
  - `GET /api/learning/report`, `/summary`, `/symbols`, `/signals`, `/time-patterns`, `/recommendations`
  - `GET /api/strategy/analytics`
  - `POST /api/strategy/apply`
  - `POST /api/strategy/custom`
  - `POST /api/strategy/reset`
  - `GET /api/strategy/history`
  - `GET /api/debug/paper-live-classification`
  - `GET /api/analysis/paper-uptrend`
- Add `src/api/routes/alerts.py`:
  - `GET /api/incoming-alerts`
  - `GET /api/incoming-alerts/stats`
  - `GET /api/incoming-alerts/symbol/{symbol}`
  - `GET /api/incoming-alerts/scan/{scan_name}`
  - `GET /api/incoming-alerts/today`
- **Bot operational:** yes + full analytics

### Phase 5 — Turbo Mode
- Create `src/services/turbo_service.py` (absorb `turbo_queue.py`, wrap `turbo_analyzer.py`)
  - `turbo_processing.json` in-flight state: do NOT migrate — new `turbo_service.py` recreates in-flight state from scratch on startup (signals in the queue that were mid-processing are requeued; this is safe because the turbo processor re-validates before executing)
- Add `src/api/routes/turbo.py`:
  - `GET /api/turbo/status`
  - `POST /api/turbo/cleanup`
- Wire turbo processor as background lifespan task in `src/main.py`
- **Bot operational:** yes + turbo confirmed

### Phase 6 — Cleanup
- Pre-cleanup snapshot:
  ```bash
  cp trading.db trading.db.pre-cleanup.bak
  cp chartink_webhook.py chartink_webhook.py.archive
  ```
- Delete root-level modules now absorbed into `src/`:
  `chartink_webhook.py`, `kite.py`, `signal_tracker.py`, `incoming_alerts.py`, `turbo_queue.py`, `learning_engine.py`, `enhanced_learning.py`, `turbo_analyzer.py`, `margins.py`
- Keep until confirmed stable: `calculator.py`, `brokerage_calculator.py` (wrapped, not deleted until `calculator_service.py` and `brokerage_service.py` are verified in production)
- Final smoke test against all 8 tabs in `dashboard.html`
- **Bot operational:** yes, clean

---

## Data Migration

**Script:** `src/scripts/migrate_json_to_db.py`

| Source file | Target | Notes |
|---|---|---|
| `trades_log.json` | `trades` table | |
| `positions.json` | `positions` table | |
| `signals_log.json` | `signals` table | |
| `incoming_alerts.json` | `incoming_alerts` table | |
| `trade_insights.json` | `insights` table | new table |
| `config.json` | `.env` file | secrets/settings only; no DB table |
| `turbo_queue.json` | `turbo_queue` table | new table |
| `turbo_processing.json` | **not migrated** | in-flight state reset on startup (safe) |
| `error_log.json` | `error_log` table | new table, if file exists |

Properties:
- **Idempotent** — upserts, safe to re-run
- **Dry-run flag** — `--dry-run` previews without writing
- **Summary output** — `N migrated, M skipped, K errors`
- **Archives** — original JSON files renamed to `.bak` after successful migration

**Cutover procedure:**
1. `cp trading.db trading.db.pre-cutover.bak` — snapshot DB
2. `python src/scripts/migrate_json_to_db.py` — verify output
3. Stop monolith: `kill $(lsof -ti:8000)`
4. Start new: `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1`
5. Smoke test all critical endpoints
6. Monitor for 10 minutes

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

**After cutover — rollback includes database:**
Rolling back `src/` code requires also restoring the database backup taken at cutover start. Any trades placed since cutover will be lost. No Alembic migrations are used (YAGNI — single-file SQLite is snapshotted instead).
```bash
# 1. Stop the server
kill $(lsof -ti:8000)
# 2. Restore DB snapshot
cp trading.db.pre-cutover.bak trading.db
# 3. Roll back code
git checkout <phase-N-commit> -- src/
# 4. Restart
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
```

**Before Phase 6 (point of no return):**
```bash
cp trading.db trading.db.pre-cleanup.bak
cp chartink_webhook.py chartink_webhook.py.archive
```

---

## Success Criteria

- All **58 routes** from `chartink_webhook.py` reimplemented in `src/`
- `chartink_webhook.py` never runs after Phase 1+2 cutover
- All critical-path tests pass (`pytest src/tests/ -v`)
- Dashboard fully functional on `src/` (all 8 tabs) — all existing API paths, HTTP methods, and JSON response field names preserved exactly
- Turbo mode, learning engine, GTT monitoring all operational
- Monolith and root-level module stubs deleted in Phase 6
- No JSON files used at runtime (SQLite only)
- Server runs with `--workers 1`
