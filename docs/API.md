# Melon Trading Bot — API Reference

Base URL: `http://localhost:8000`
Version: 2.0.0
All request/response bodies are JSON unless noted.

---

## Table of Contents

1. [Health](#health)
2. [Dashboard](#dashboard)
3. [Trading](#trading)
4. [Positions](#positions)
5. [GTT Orders](#gtt-orders)
6. [Quotes & Funds](#quotes--funds)
7. [Config](#config)
8. [Webhook](#webhook)
9. [Incoming Alerts](#incoming-alerts)
10. [Turbo](#turbo)
11. [Analytics & Learning](#analytics--learning)
12. [Strategy Optimizer](#strategy-optimizer)
13. [ESP Display](#esp-display)
14. [UI Pages](#ui-pages)
15. [Known Issues / Debug Notes](#known-issues--debug-notes)

---

## Health

### `GET /health`
System health check.

**Response**
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "mode": "paper",
  "timestamp": "2026-03-18T11:11:28.185058",
  "checks": {
    "config": { "status": "ok", "system_enabled": true, "paper_trading": true },
    "database": { "status": "ok" }
  }
}
```

---

## Dashboard

### `GET /api/dashboard`
Single combined endpoint — returns config + stats + trades + alert stats in one round trip. Used by the dashboard on load.

**Response**
```json
{
  "config": { ...see Config section... },
  "stats": { ...see Stats section... },
  "trades": [ ...array of trade objects... ],
  "alerts_stats": { ...see Incoming Alerts Stats section... }
}
```

### `GET /api/stats`
Trading statistics for today.

**Response**
```json
{
  "system_enabled": true,
  "within_trading_hours": true,
  "today_trades": 0,
  "today_pnl": 0,
  "max_trades": 100,
  "winning_trades": 0,
  "losing_trades": 2,
  "capital": 2000.0,
  "risk_percent": 1.0,
  "total_trades": 0,
  "paper_trades_today": 0,
  "live_trades_today": 0
}
```

### `POST /api/reset-daily`
Resets the dashboard state for a new trading day (clears today's counters).

**Response** `{ "status": "ok" }`

---

## Trading

### `POST /api/trade`
Manually execute a trade.

**Request**
```json
{
  "symbol": "RELIANCE",
  "action": "BUY",
  "quantity": null,
  "price": null
}
```
- `action`: `"BUY"` (default) or `"SELL"`
- `quantity`: omit to auto-calculate from capital + risk %
- `price`: omit for market order

**Response**
```json
{
  "status": "SUCCESS",
  "order_id": "...",
  "message": "Order placed successfully"
}
```

### `GET /api/trades`
All trades executed today.

**Response** — array of trade objects:
```json
[
  {
    "id": "TRD...",
    "symbol": "RELIANCE",
    "action": "BUY",
    "quantity": 1,
    "entry_price": 1234.5,
    "exit_price": null,
    "pnl": null,
    "status": "open",
    "paper_trading": true,
    "date": "2026-03-18T09:30:00"
  }
]
```

### `GET /api/portfolio`
Full portfolio summary (positions + trades + P&L).

---

## Positions

### `GET /api/positions`
Current open positions with live P&L.

**Response**
```json
{
  "positions": [
    {
      "id": "POS...",
      "symbol": "RELIANCE",
      "quantity": 1,
      "entry_price": 1234.5,
      "ltp": 1250.0,
      "unrealized_pnl": 15.5,
      "sl_price": 1210.0,
      "tp_price": 1280.0,
      "paper_trading": true,
      "entry_time": "2026-03-18T09:30:00"
    }
  ],
  "count": 1,
  "total_unrealized_pnl": 15.5
}
```

### `POST /api/positions/{position_id}/close`
Close a position (places a sell order).

**Request**
```json
{ "exit_price": null }
```
Omit `exit_price` for market price.

### `POST /api/positions/{position_id}/force-close`
Force-close a position record without placing an order (use when already closed externally via Kite app).

**Request**
```json
{ "exit_price": 1250.0 }
```

### `POST /api/positions/{position_id}/modify-sl`
Update stop-loss price. For live positions, also re-places the GTT order.

**Request**
```json
{ "new_sl_price": 1220.0 }
```

### `POST /api/positions/sync`
Sync local positions against Kite — marks positions as closed if they've been exited on Kite.

### `GET /api/positions/kite-debug`
Compare raw Kite positions vs local DB. Useful for diagnosing sync issues.

**Response**
```json
{
  "kite_positions": [],
  "local_open_positions": [],
  "match_analysis": { "kite_count": 0, "local_open_count": 0 }
}
```

### `POST /api/sync-kite`
Import positions placed directly via the Kite app (not through the bot) into local DB.

---

## GTT Orders

### `GET /api/gtt-orders`
List all active GTT (Good-Till-Triggered) stop-loss orders from Kite, enriched with matching position info.

**Response**
```json
{
  "status": "success",
  "count": 0,
  "orders": [
    {
      "id": 123456,
      "type": "single",
      "status": "active",
      "condition": {
        "exchange": "NSE",
        "tradingsymbol": "RELIANCE",
        "trigger_values": [1210.0]
      },
      "position_id": "POS..."
    }
  ]
}
```

### `POST /api/gtt/cleanup`
Cancel orphan GTT orders (GTTs with no matching open local position).

**Response** `{ "status": "ok", "cancelled": 2 }`

---

## Quotes & Funds

### `GET /api/quote/{symbol}`
Real-time LTP and OHLCV from Kite.

**Example:** `GET /api/quote/RELIANCE`

**Response (success)**
```json
{
  "symbol": "RELIANCE",
  "ltp": 1250.0,
  "open": 1230.0,
  "high": 1260.0,
  "low": 1225.0,
  "close": 1245.0,
  "volume": 1200000,
  "change": 5.0,
  "change_percent": 0.4
}
```

**Response (failure)**
```json
{ "detail": "Quote not available" }
```

> **Note:** Returns 404-style detail when Kite token is invalid or symbol not found.

### `GET /api/kite/funds`
Account funds and margin from Kite.

**Response (success)**
```json
{
  "status": "ok",
  "funds": {
    "available_cash": 10000.0,
    "available_intraday": 50000.0,
    "utilized": 2000.0,
    "exposure": 1500.0,
    "span": 500.0,
    "net_available": 8000.0
  },
  "timestamp": "..."
}
```

**Response (failure)**
```json
{ "status": "error", "funds": null, "timestamp": "..." }
```

### `POST /api/test-kite`
Test Kite API connectivity. Fetches NIFTY 50 quote as a smoke test.

**Response (success)**
```json
{
  "status": "success",
  "message": "Connected! NIFTY 50 LTP: ₹23770.25",
  "nifty_ltp": 23770.25
}
```

**Response (failure)**
```json
{ "status": "failed", "message": "Could not fetch quote. Check Token." }
```

---

## Config

### `GET /api/config`
Current configuration (sensitive fields like tokens are masked with `***`).

**Response**
```json
{
  "system_enabled": true,
  "paper_trading": true,
  "capital": 2000.0,
  "risk_percent": 1.0,
  "max_trades_per_day": 100,
  "trading_hours": { "start": "09:15", "end": "15:30" },
  "trading_windows": [
    { "start": "09:15", "end": "12:00" },
    { "start": "13:30", "end": "15:30" }
  ],
  "kite": {
    "api_key": "8zjb...",
    "api_secret": "***",
    "access_token": "***",
    "base_url": "https://api.kite.trade"
  },
  "telegram": { "enabled": true, "bot_token": "***", "chat_id": "245567614" },
  "whatsapp": { "enabled": true, "api_key": "***", "recipient": "919745010715" },
  "risk_management": {
    "atr_multiplier_sl": 1.5,
    "atr_multiplier_tp": 3.0,
    "min_risk_reward": 2.0,
    "max_sl_percent": 2.0
  },
  "chartink": { "webhook_secret": "MelonBot123" },
  "club_positions": true,
  "prevent_duplicate_stocks": false,
  "trailing_tp_enabled": true
}
```

### `POST /api/config`
Update configuration. Only fields provided are updated (partial update).

**Request** — all fields optional:
```json
{
  "system_enabled": true,
  "paper_trading": false,
  "capital": 5000.0,
  "risk_percent": 1.5,
  "max_trades_per_day": 10,
  "kite_access_token": "NewTokenHere",
  "kite_api_key": "...",
  "kite_api_secret": "...",
  "trading_hours": { "start": "09:15", "end": "15:30" },
  "telegram": { "enabled": true, "bot_token": "...", "chat_id": "..." },
  "whatsapp": { "enabled": false },
  "risk_management": { "atr_multiplier_sl": 2.0 },
  "paper_trading_filters": {},
  "signal_validation": {},
  "trading_windows": [ { "start": "09:15", "end": "12:00" } ]
}
```

### `POST /api/test-telegram`
Send a test message to configured Telegram chat.

### `POST /api/test-whatsapp`
Send a test WhatsApp message.

---

## Webhook

### `GET /webhook/chartink`
Connectivity check — returns status so ChartInk can verify the endpoint is reachable.

**Response** `{ "status": "ok", "message": "Webhook active" }`

### `POST /webhook/chartink`
Main webhook — receives ChartInk alerts (JSON format).

**ChartInk Webhook URL to configure:** `http://<your-server>/webhook/chartink`
**Secret:** `MelonBot123` (set in ChartInk webhook settings)

**Request**
```json
{
  "stocks": "RELIANCE,INFY",
  "trigger_prices": "1250.0,1800.0",
  "scan_name": "my_scan",
  "alert_name": "Breakout",
  "triggered_at": "2026-03-18 09:30:00",
  "secret": "MelonBot123"
}
```
- `stocks`: comma-separated symbol list
- `trigger_prices`: comma-separated price list matching `stocks` order
- `secret`: must match `config.chartink.webhook_secret`

**Response**
```json
{
  "status": "ok",
  "processed": 2,
  "rejected": 0,
  "details": [...]
}
```

### `POST /webhook/chartink/form`
Same as above but accepts `application/x-www-form-urlencoded` (some ChartInk configurations send form data).

---

## Incoming Alerts

### `GET /api/incoming-alerts`
Recent webhook alerts received, with optional filtering.

**Query params:**
- `limit` (int, default 50): max alerts to return
- `status` (string, optional): filter by `processed`, `rejected`, `error`, `pending`

**Response**
```json
{
  "alerts": [
    {
      "id": "ALT20260318102307478",
      "timestamp": "2026-03-18T10:23:07.478896",
      "alert_type": "json",
      "source_ip": "23.106.53.213",
      "symbols": ["RELIANCE", "INFY"],
      "scan_name": "cklaude2",
      "processing_status": "rejected",
      "result_summary": "All 2 stocks rejected",
      "latency_ms": 300.08
    }
  ],
  "count": 1,
  "filter": { "status": null, "limit": 50 }
}
```

**`processing_status` values:**
| Value | Meaning |
|---|---|
| `processed` | Trade was executed |
| `rejected` | Signal filtered out (outside hours, duplicate, etc.) |
| `error` | Exception during processing (e.g. Kite API failure) |
| `pending` | Queued in turbo mode, awaiting confirmation |

### `GET /api/incoming-alerts/stats`
Today's aggregate alert statistics.

**Response**
```json
{
  "stats": {
    "date": "2026-03-18",
    "total": 31,
    "by_type": { "json": 31 },
    "by_status": { "rejected": 21, "error": 10 },
    "unique_sources": ["23.106.53.213"],
    "avg_latency_ms": 111.73,
    "max_latency_ms": 553.91
  },
  "timestamp": "..."
}
```

### `GET /api/incoming-alerts/symbol/{symbol}`
All today's alerts that included a specific symbol.

### `GET /api/incoming-alerts/scan/{scan_name}`
All today's alerts from a specific scan name.

### `GET /api/incoming-alerts/today`
Summary of all alerts received today (counts and breakdown).

### `GET /api/signals`
Today's signal processing history and stats (internal signal log, not raw alerts).

### `POST /api/signals/clear`
Clear today's signal log (for testing purposes).

---

## Turbo

Turbo mode queues signals and waits for multi-timeframe confirmation before executing.

### `GET /api/turbo/status`
Current turbo queue state.

**Response**
```json
{
  "status": "ok",
  "turbo_enabled": true,
  "queue_size": 0,
  "processing_count": 0,
  "completed_today": 0,
  "expired_count": 0,
  "queued": [],
  "processing": [],
  "recent_completed": [],
  "timestamp": "..."
}
```

### `POST /api/turbo/cleanup`
Remove completed/expired turbo queue entries older than 24 hours.

---

## Analytics & Learning

### `GET /api/insights`
Per-symbol trade insights from all historical trades in DB.

### `GET /api/insights/{symbol}`
Insights for a specific symbol (win rate, avg P&L, best/worst trades).

### `GET /api/learning/report`
Full learning report — summary + symbols + signals + time patterns + recommendations combined.

### `GET /api/learning/summary`
High-level paper vs live P&L summary.

**Response**
```json
{
  "status": "ok",
  "total_trades": 318,
  "paper": { "count": 300, "pnl": 0.0, "win_rate": 0.0, "wins": 0, "losses": 300 },
  "live":  { "count": 18,  "pnl": -12.2, "win_rate": 0.0, "wins": 0, "losses": 18 },
  "combined_pnl": -12.2
}
```

### `GET /api/learning/symbols`
Per-symbol performance with paper/live breakdown and letter grades (A–F).

### `GET /api/learning/signals`
Signal conversion rate: how many webhook alerts actually became trades.

### `GET /api/learning/time-patterns`
Hourly win-rate and P&L patterns (which hour of day performs best).

### `GET /api/learning/recommendations`
Actionable trading recommendations generated from historical data.

### `GET /api/analysis/paper-uptrend`
Analyses how far paper trades ran up after entry — useful for evaluating missed profit potential.

### `GET /api/debug/paper-live-classification`
Debug endpoint: shows how trades are being classified as paper vs live.

---

## Strategy Optimizer

### `GET /api/strategy/analytics`
Comprehensive strategy analytics: best/worst scan names, time windows, risk-reward stats.

### `POST /api/strategy/apply`
Apply a specific recommendation from the strategy optimizer by index.

**Request**
```json
{ "recommendation_idx": 0 }
```

### `POST /api/strategy/custom`
Apply custom strategy parameters and save to config.

**Request** — all fields optional:
```json
{
  "risk_percent": 1.5,
  "min_risk_reward": 2.5,
  "atr_multiplier_sl": 1.5,
  "atr_multiplier_tp": 3.0,
  "max_slippage_percent": 0.5,
  "trading_hours": { "start": "09:15", "end": "15:30" }
}
```

### `GET /api/strategy/history`
Log of all strategy configuration changes made through the optimizer.

### `POST /api/strategy/reset`
Reset strategy parameters to system defaults.

---

## ESP Display

Lightweight endpoints for ESP8266/ESP32 hardware trading displays.

### `GET /api/esp/stats`
Compact stats payload (minimal JSON for small devices).

### `GET /api/esp/positions`
Simplified position list for display on small screens.

### `GET /api/esp/alert`
Latest webhook alert (mark-as-shown on read — polling-friendly).

---

## UI Pages

| URL | Description |
|---|---|
| `GET /` or `GET /dashboard` | Main trading dashboard |
| `GET /debug` | Debug page with raw API outputs |
| `GET /kite-login` | Kite OAuth token exchange helper |
| `GET /esp-setup` | ESP8266/ESP32 hardware setup guide |
| `GET /test-cors` | CORS test page |
| `GET /upload` | File upload page |
| `POST /api/upload` | Upload a file (multipart/form-data) |
| `GET /api/uploaded-files` | List uploaded files |

---

## Known Issues / Debug Notes

### Quote API returning `"Quote not available"`
- **Cause:** Kite access token is expired or invalid
- **Fix:** Get a new `request_token` via Kite OAuth login, then `POST /api/config` with `{ "kite_access_token": "new_token" }` or update `config.json` and restart the server
- **Check:** `POST /api/test-kite` — should return `"status": "success"`

### Kite Funds returning `"status": "error"`
- **Cause:** Same as above — token expired
- **Also check:** `GET /api/positions/kite-debug` to see if Kite is reachable

### Alerts showing `processing_status: "error"` with `"Could not fetch market price"`
- **Cause:** Quote API failing due to bad Kite token
- **Fix:** Refresh access token

### All 300 paper trades showing 0 P&L / 0 wins
- **Cause:** Paper trades were logged but exit prices were never recorded (positions not properly closed)
- **Debug:** `GET /api/positions/kite-debug`, `GET /api/debug/paper-live-classification`

### Turbo mode: signals queued but never executed
- **Check:** `GET /api/turbo/status` for queue state
- **Config:** `turbo_mode.trend_alignment_required` — set `false` to relax entry conditions
- **Config:** `turbo_mode.check_interval_seconds` — how often confirmation is checked

### Server startup
```bash
# Start server
venv/bin/python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1

# Check if running
curl http://localhost:8000/health
```

### Daily token refresh (manual process)
1. Open: `https://kite.zerodha.com/connect/login?v=3&api_key=8zjbufhni9k0u2mx`
2. Login and copy `request_token` from redirect URL
3. `POST /api/config` with `{ "kite_access_token": "<exchanged_token>" }`
   *(or update `config.json` directly and restart)*
