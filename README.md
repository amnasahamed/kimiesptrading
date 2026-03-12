# 🤖 ChartInk Trading Bot

A high-performance, production-ready trading bot that receives signals from [ChartInk](https://chartink.com) and executes trades via Zerodha Kite API. Built with FastAPI for ultra-low latency (~200ms total response time).

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ Features

### Core Trading
- ⚡ **Ultra-fast execution**: ~200ms total latency (webhook → order placement)
- 📊 **ChartInk Integration**: Receives webhook alerts from ChartInk scanner
- 🔗 **Zerodha Kite API**: Live market data and order execution
- 📝 **Paper Trading Mode**: Test strategies with ₹10,000 fixed position size
- 🎯 **Automatic SL/TP**: Bracket orders with Stop Loss and Take Profit
- 📱 **Telegram Notifications**: Real-time trade alerts

### Risk Management
- 🛡️ **5-Step Signal Validation**:
  1. Time window check (10:00-11:30, 13:30-14:30)
  2. Nifty health check (reject if down >0.3%)
  3. Max positions limit (3 for live, 20 for paper)
  4. Duplicate signal prevention
  5. Price slippage check
- 💰 **Daily Loss Limit**: Max 3% of capital
- 📈 **Position Sizing**: Intelligent sizing based on ATR and risk%
- 🔄 **Position Clubbing**: Average multiple entries of same stock

### Monitoring & Logging
- 📊 **Web Dashboard**: Real-time P&L, positions, trade history
- 🔔 **Incoming Alerts Logger**: Records EVERY webhook call from ChartInk
- 📜 **Signal Tracker**: Tracks all signals with status (executed/rejected/failed)
- 📈 **Performance Analytics**: Win rate, R:R ratios, trade statistics

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/amnasahamed/kimiesptrading.git
cd kimiesptrading

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy the example config and edit:

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "system_enabled": false,
  "paper_trading": true,
  "kite": {
    "api_key": "your_kite_api_key",
    "access_token": "your_access_token"
  },
  "chartink": {
    "webhook_secret": "your_webhook_secret"
  },
  "telegram": {
    "bot_token": "your_bot_token",
    "chat_id": "your_chat_id",
    "enabled": true
  }
}
```

### 3. Run the Bot

```bash
# Development
python chartink_webhook.py

# Production with uvicorn
uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000 --workers 1
```

### 4. Access Dashboard

Open: http://localhost:8000/dashboard

---

## 📡 Webhook Setup (ChartInk)

### Webhook URL

```
https://your-domain.com/webhook/chartink?secret=YOUR_SECRET
```

### ChartInk Alert Message Format

Configure your ChartInk scan with this webhook message:

```json
{
  "stocks": "{{stock}}",
  "trigger_prices": "{{trigger_price}}",
  "triggered_at": "{{triggered_at}}",
  "scan_name": "{{scan_name}}",
  "scan_url": "{{scan_url}}",
  "alert_name": "Alert for {{scan_name}}"
}
```

### Supported Alert Formats

| Format | Endpoint | Content-Type |
|--------|----------|--------------|
| JSON | `POST /webhook/chartink` | `application/json` |
| Form Data | `POST /webhook/chartink/form` | `application/x-www-form-urlencoded` |
| Query Params | `GET /webhook/chartink` | Query string |

---

## 📝 Paper Trading Mode

Perfect for testing signal accuracy without real money!

### Features
- ✅ Fixed ₹10,000 position size per trade
- ✅ No daily loss limits
- ✅ Higher position limit (20 vs 3 in live)
- ✅ Relaxed slippage tolerance (1% vs 0.5%)
- ✅ All trades tagged with 📝 PAPER

### Enable Paper Trading

```bash
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"paper_trading": true}'
```

### Paper Trading Filters (Configurable)

```json
{
  "paper_trading_filters": {
    "enabled": true,
    "fixed_position_size": 10000,
    "time_window_check": true,
    "nifty_check": false,
    "max_positions": 20,
    "prevent_duplicates": true,
    "slippage_check": true,
    "max_slippage_percent": 1.0,
    "daily_loss_limit": false
  }
}
```

---

## 🔌 API Endpoints

### Trading
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/chartink` | POST | Main webhook (JSON) |
| `/webhook/chartink/form` | POST | Webhook (Form data) |
| `/webhook/chartink` | GET | Webhook (Query params) |
| `/api/positions` | GET | Get open positions |
| `/api/trades` | GET | Get trade history |
| `/api/quote/{symbol}` | GET | Get live quote |

### Configuration
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config` | GET | Get configuration |
| `/api/config` | POST | Update configuration |
| `/api/test-kite` | POST | Test Kite connection |
| `/api/test-telegram` | POST | Test Telegram |

### Monitoring
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/incoming-alerts` | GET | Get all webhook alerts |
| `/api/incoming-alerts/stats` | GET | Get alert statistics |
| `/api/incoming-alerts/today` | GET | Get today's summary |
| `/api/stats` | GET | Get trading stats |
| `/api/signals` | GET | Get signal history |
| `/health` | GET | Health check |

---

## 📊 Dashboard Features

### Main Dashboard
- Real-time P&L with color coding
- System status toggle
- Trading statistics (win rate, trades, etc.)
- Recent trades table
- Open positions with live P&L

### Incoming Alerts Tab
- View every webhook call from ChartInk
- Filter by status (pending/processed/rejected/error)
- Click for detailed view (raw payload, processing result)
- Statistics cards (Total, Processed, Rejected, Avg Latency)

### Positions Tab
- Close positions manually
- Sync with Kite positions
- View unrealized P&L
- Force-close positions

---

## 🛠️ Architecture

```
┌─────────────┐      2ms       ┌──────────────┐
│  ChartInk   │ ─────────────→ │   FastAPI    │
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

**Total Latency: ~200-300ms** 🚀

---

## 📁 Project Structure

```
.
├── chartink_webhook.py    # Main FastAPI application
├── kite.py                # Zerodha Kite API wrapper
├── calculator.py          # ATR, SL/TP calculations
├── signal_tracker.py      # Signal history & duplicate detection
├── incoming_alerts.py     # Webhook audit logging
├── dashboard.html         # Web dashboard (single file)
├── config.json            # Configuration (auto-created)
├── config.example.json    # Example configuration
├── trades_log.json        # Trade history (auto-created)
├── positions.json         # Open positions (auto-created)
├── signals_log.json       # Signal history (auto-created)
├── incoming_alerts.json   # Webhook audit log (auto-created)
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

---

## 🔐 Security Features

- ✅ Webhook secret validation
- ✅ Rate limiting (20 calls/minute per IP)
- ✅ IP address logging for audit
- ✅ Secrets masked in logs
- ✅ CORS protection
- ✅ Input validation on all endpoints

---

## 🐛 Troubleshooting

### Issue: "Invalid webhook secret"
**Solution**: The secret was sent in URL query string. Fixed in latest version - system now checks both URL and JSON body.

### Issue: "Max open positions reached"
**Solution**: Either close some positions or enable paper trading for unlimited testing.

### Issue: "Outside trading windows"
**Solution**: System only trades 10:00-11:30 and 13:30-14:30 IST. Disable time check in paper mode for testing.

### Issue: "Rate limit exceeded"
**Solution**: Wait 60 seconds. ChartInk may send multiple alerts quickly - rate limiting protects the system.

---

## 📝 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## ⚠️ Disclaimer

Trading involves financial risk. This bot is for educational purposes. Always:
- Test thoroughly in paper trading mode
- Start with small capital
- Never risk more than you can afford to lose
- Monitor the system regularly

---

## 📞 Support

For issues and feature requests, please use the [GitHub Issues](https://github.com/amnasahamed/kimiesptrading/issues) page.

---

**Made with ❤️ for the Indian trading community**
