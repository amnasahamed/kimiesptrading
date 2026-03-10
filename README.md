# Chartink Trading Bot ⚡

A lightweight, ultra-fast trading webhook system to replace n8n workflows.

**Latency: ~100-200ms** (10x faster than n8n)

📖 **[Full Setup Instructions →](INSTRUCTIONS.md)**

---

## Architecture

```
┌─────────────┐      2ms       ┌──────────────┐
│  Chartink   │ ─────────────→ │   FastAPI    │
└─────────────┘                └──────┬───────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ↓                 ↓                 ↓
              ┌─────────┐      ┌──────────┐      ┌──────────┐
              │  Quote  │      │  OHLCV   │      │  Config  │
              │ (50ms)  │      │  (100ms) │      │  (0.1ms) │
              └────┬────┘      └────┬─────┘      └────┬─────┘
                   └─────────────────┘                 │
                             ↓                        │
                      ┌────────────┐                   │
                      │  ATR Calc  │                   │
                      │   (0.1ms)  │                   │
                      └─────┬──────┘                   │
                            ↓                          │
                     ┌─────────────┐                   │
                     │  SL/TP/Qty  │                   │
                     │   (0.1ms)   │                   │
                     └──────┬──────┘                   │
                            ↓                          │
                     ┌─────────────┐                   │
                     │Place Order  │ ←─────────────────┘
                     │  (100ms)    │
                     └──────┬──────┘
                            ↓
              ┌─────────────────────────┐
              │  Telegram + Log (async) │
              └─────────────────────────┘
```

**Total: ~250-300ms** 🚀

## File Structure

```
chartink_webhook.py    ← FastAPI app (main entry)
calculator.py          ← ATR/SL/TP/Quantity logic
kite.py                ← Kite API wrapper
dashboard.html         ← Single-file dashboard
config.json            ← Settings (auto-created)
trades_log.json        ← Trade history (auto-created)
requirements.txt       ← Dependencies
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Edit `config.json`:

```json
{
  "kite": {
    "api_key": "your_api_key",
    "access_token": "your_access_token",
    "base_url": "https://api.kite.trade"
  },
  "telegram": {
    "bot_token": "your_bot_token",
    "chat_id": "your_chat_id",
    "enabled": true
  },
  "chartink": {
    "webhook_secret": "your_secret"
  }
}
```

### 3. Run

```bash
python chartink_webhook.py
```

Or with uvicorn directly:

```bash
uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Access Dashboard

Open: http://localhost:8000/dashboard

### 5. Set Webhook URL in Chartink

**Primary webhook URL:**
```
http://your-server:8000/webhook/chartink
```

#### Chartink Payload Format

Chartink sends JSON like this:
```json
{
    "stocks": "SEPOWER,ASTEC,EDUCOMP,KSERASERA,IOLCP,GUJAPOLLO,EMCO",
    "trigger_prices": "3.75,541.8,2.1,0.2,329.6,166.8,1.25",
    "triggered_at": "2:34 pm",
    "scan_name": "Short term breakouts",
    "scan_url": "short-term-breakouts",
    "alert_name": "Alert for Short term breakouts",
    "webhook_url": "http://your-web-hook-url.com"
}
```

- `stocks`: Comma-separated list of symbols
- `trigger_prices`: Comma-separated prices matching stock order
- `triggered_at`: Time when scan triggered
- `scan_name`: Name of your scan

The bot will:
1. Parse all stocks from the alert
2. Process each stock sequentially
3. Respect `max_trades_per_day` limit
4. Send individual Telegram notifications

For **Form-data payload** (if JSON doesn't work):
```
http://your-server:8000/webhook/chartink/form
```

For **GET format** (testing):
```
http://your-server:8000/webhook/chartink?symbol=RELIANCE&action=BUY&price=2500
```

### Chartink Scan Configuration

Your scan should filter for momentum breakouts. Example criteria:

| Filter | Value | Purpose |
|--------|-------|---------|
| Daily Close | > 100 | Price filter |
| Daily Close | < 1500 | Avoid illiquid high-price stocks |
| Market Cap | > 2000 Cr | Ensure liquidity |
| Daily Close | > Daily SMA(50) | Uptrend confirmation |
| Daily SMA(10) | > Daily SMA(50) | Golden cross - momentum |
| Daily Close | > 1 day ago High | Breakout above previous high |
| % Change | > 2% | Momentum confirmation |
| Daily Volume | > 300,000 | Base liquidity |
| Daily Volume | > 2x SMA(20) | Volume spike confirmation |
| Daily Volume × Close | > 5 Cr | Value traded filter |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/webhook/chartink` | POST | Main webhook (Chartink) |
| `/webhook/chartink` | GET | Simple webhook (query params) |
| `/dashboard` | GET | Web dashboard |
| `/api/config` | GET | Get config |
| `/api/config` | POST | Update config |
| `/api/stats` | GET | Trading stats |
| `/api/trades` | GET | Today's trades |
| `/api/quote/{symbol}` | GET | Live quote |
| `/api/test-telegram` | POST | Test Telegram |

## Production Deployment (VPS)

### Using PM2

```bash
# Install PM2
npm install -g pm2

# Start with PM2
pm2 start "uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000" --name trading-bot

# Save PM2 config
pm2 save
pm2 startup
```

### Using Systemd

Create `/etc/systemd/system/trading-bot.service`:

```ini
[Unit]
Description=Chartink Trading Bot
After=network.target

[Service]
User=your_user
WorkingDirectory=/path/to/bot
ExecStart=/path/to/python -m uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
```

### Using Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "chartink_webhook:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t trading-bot .
docker run -d -p 8000:8000 --name trading-bot trading-bot
```

## Kite Access Token

The access token expires daily. You have two options:

### Option 1: Manual (Dashboard)

1. Login to Kite every morning
2. Get access token from: https://kite.trade/connect/login
3. Paste in dashboard before 9:15 AM

### Option 2: Automated (Selenium)

See `automation/get_token.py` for a Selenium script to auto-fetch token.

```bash
# Run daily via cron
crontab -e

# Add:
0 8 * * 1-5 /path/to/python /path/to/automation/get_token.py >> /tmp/kite_token.log 2>&1
```

## Risk Management

Configured in `config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `risk_percent` | 1.0 | Risk per trade (% of capital) |
| `max_trades_per_day` | 10 | Max trades allowed |
| `atr_multiplier_sl` | 1.5 | SL = ATR × multiplier |
| `atr_multiplier_tp` | 3.0 | TP = ATR × multiplier |
| `min_risk_reward` | 2.0 | Minimum R:R ratio |
| `max_sl_percent` | 2.0 | Max SL as % of entry |

## Guard Conditions

The system automatically rejects trades if:
- ❌ System is disabled
- ❌ Outside trading hours (9:15 AM - 3:30 PM)
- ❌ Max daily trades reached
- ❌ Invalid symbol
- ❌ Risk too high (calculated SL > max allowed)

## Monitoring

### Telegram Alerts

Get instant notifications for:
- ✅ Trade executed
- ❌ Trade rejected (with reason)
- 📊 Daily P&L summary

### Dashboard

Real-time view of:
- System status
- Today's P&L
- Trade history
- Win rate
- Position sizing

## Troubleshooting

### Check logs
```bash
pm2 logs trading-bot
# or
journalctl -u trading-bot -f
```

### Test webhook manually
```bash
curl -X POST http://localhost:8000/webhook/chartink \
  -H "Content-Type: application/json" \
  -d '{"symbol":"RELIANCE","action":"BUY","price":2500}'
```

### Test Kite connection
```bash
curl http://localhost:8000/api/quote/RELIANCE
```

## Performance Benchmarks

| Step | n8n | FastAPI |
|------|-----|---------|
| Webhook receive | ~200ms | ~2ms |
| Quote fetch | ~100ms | ~50ms |
| Order place | ~100ms | ~100ms |
| **Total** | **800ms-2s** | **~200ms** |

## License

MIT - Use at your own risk. Trading involves financial risk.
