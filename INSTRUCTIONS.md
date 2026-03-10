# Chartink Trading Bot - Setup Guide

A step-by-step guide to install, configure, and use the Chartink webhook trading bot.

---

## 📋 Prerequisites

Before you start, you need:

1. **VPS/Server** (or local computer for testing)
   - Ubuntu/Debian/CentOS or any Linux
   - Windows also works
   - Minimum 1GB RAM, 1 CPU core

2. **Python 3.8+**
   ```bash
   python3 --version
   ```

3. **Accounts Required:**
   - ✅ Zerodha Kite account (with API access)
   - ✅ Telegram account (for notifications)
   - ✅ Chartink account (Premium for webhooks)
   - ✅ VPS with static IP (for production)

---

## 📦 Step 1: Installation

### 1.1 Download the Bot

```bash
# Clone or download the files to your server
cd /home/yourusername
git clone <repository-url> trading-bot
# OR upload files via SCP/FTP

cd trading-bot
```

### 1.2 Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# OR if you have multiple Python versions:
pip3 install -r requirements.txt
```

**Dependencies installed:**
- FastAPI (web framework)
- Uvicorn (ASGI server)
- HTTPX (async HTTP client)
- Pydantic (data validation)
- KiteConnect (Zerodha API)

### 1.3 Verify Installation

```bash
python3 -m py_compile chartink_webhook.py
# Should return no errors
```

---

## ⚙️ Step 2: Configuration

### 2.1 Edit config.json

Open `config.json` and fill in your details:

```json
{
  "system_enabled": false,
  "trading_hours": {
    "start": "09:15",
    "end": "15:30"
  },
  "capital": 100000,
  "risk_percent": 1.0,
  "max_trades_per_day": 10,
  "kite": {
    "api_key": "YOUR_KITE_API_KEY",
    "access_token": "",
    "base_url": "https://api.kite.trade"
  },
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID",
    "enabled": true
  },
  "risk_management": {
    "atr_multiplier_sl": 1.5,
    "atr_multiplier_tp": 3.0,
    "min_risk_reward": 2.0,
    "max_sl_percent": 2.0
  },
  "chartink": {
    "webhook_secret": "your_secret_password"
  }
}
```

### 2.2 Get Kite API Credentials

1. Go to https://developers.kite.trade/
2. Login with your Zerodha account
3. Create a new app
4. Copy the **API Key** and **API Secret**
5. Paste API Key in `config.json`

### 2.3 Get Kite Access Token (Daily)

The access token expires every day. You need to generate it before 9:15 AM.

**Method 1: Manual (First time)**
1. Visit: `https://kite.trade/connect/login?v=3&api_key=YOUR_API_KEY`
2. Login with your Zerodha credentials
3. You'll be redirected to a URL like:
   ```
   http://localhost/?request_token=xyz123&status=success
   ```
4. Copy the `request_token` value
5. Exchange it for access token using the dashboard

**Method 2: Dashboard (Daily)**
1. Open your bot dashboard: `http://your-vps-ip:8000/dashboard`
2. Paste the access token in the "Kite Access Token" field
3. Click "Update Token"

**Method 3: Automated (Optional)**
See `automation/get_token.py` for Selenium automation.

### 2.4 Setup Telegram Notifications

1. **Create a Bot:**
   - Message @BotFather on Telegram
   - Send `/newbot`
   - Follow instructions
   - Copy the **bot token** (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Get Your Chat ID:**
   - Message @userinfobot
   - It will reply with your chat ID
   - OR message @getidsbot

3. **Test the Bot:**
   - Send a message to your bot
   - Visit: `https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates`
   - Look for `"chat":{"id":123456789`

4. **Update config.json:**
   ```json
   "telegram": {
     "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
     "chat_id": "123456789",
     "enabled": true
   }
   ```

### 2.5 Set Webhook Secret

Choose a strong password for your webhook:
```json
"chartink": {
  "webhook_secret": "MySecretPassword123!"
}
```

This prevents unauthorized access to your webhook.

---

## 🚀 Step 3: Run the Bot

### 3.1 Start the Server

```bash
# Simple start (for testing)
python3 chartink_webhook.py

# OR with uvicorn
uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000
```

You should see:
```
==================================================
🚀 Chartink Trading Bot Started
==================================================
📊 Dashboard: http://localhost:8000/dashboard
🔗 Webhook: http://localhost:8000/webhook/chartink
==================================================
```

### 3.2 Access the Dashboard

Open in browser:
```
https://coolify.themelon.in/dashboard
```

### 3.3 Test the Bot

Run the test script:
```bash
python3 test_webhook.py
```

This will verify:
- ✅ Server is running
- ✅ Config is loaded
- ✅ Telegram works
- ✅ Webhook responds

---

## 📊 Step 4: Configure Chartink Webhook

### 4.1 Create Your Scan

1. Login to https://chartink.com
2. Go to "Scan" → "Create Scan"
3. Add your filters (momentum breakout criteria)
4. Example filters:
   - Daily Close > 100
   - Daily Close < 1500
   - Market Cap > 2000
   - Daily Close > Daily SMA(50)
   - Daily SMA(10) > Daily SMA(50)
   - Daily Close > 1 day ago High
   - Daily Volume > 300000

### 4.2 Set Alert/Webhook

1. Save your scan
2. Click "Create Alert" or "Alert"
3. Configure:
   - **Alert Name:** Short term breakouts
   - **Webhook URL:** `https://coolify.themelon.in/webhook/chartink`
   - **Method:** POST
   - **Content Type:** application/json

### 4.3 Webhook Payload

Chartink will send this JSON:
```json
{
    "stocks": "RELIANCE,TCS,HDFCBANK",
    "trigger_prices": "2500,3500,1500",
    "triggered_at": "10:30 am",
    "scan_name": "Short term breakouts",
    "scan_url": "short-term-breakouts",
    "alert_name": "Alert for Short term breakouts",
    "webhook_url": "http://your-vps-ip:8000/webhook/chartink"
}
```

### 4.4 Test the Webhook

In Chartink, click "Test Webhook" or wait for scan to trigger.

You should receive:
1. Trade executed in Kite
2. Telegram notification
3. Entry in dashboard

---

## 🔄 Step 5: Daily Workflow

### Morning (Before 9:15 AM)

1. **Generate Kite Access Token:**
   - Visit: `https://kite.trade/connect/login?v=3&api_key=YOUR_API_KEY`
   - Login and copy request token
   - Exchange for access token
   - OR use automation script

2. **Update Token in Dashboard:**
   - Open: `http://your-vps-ip:8000/dashboard`
   - Paste new access token
   - Click "Update Token"

3. **Enable Trading:**
   - Toggle "Enable Trading" ON
   - Verify system status shows "Active"

### During Market Hours (9:15 AM - 3:30 PM)

- Bot runs automatically
- Chartink alerts trigger trades
- You get Telegram notifications
- Monitor via dashboard

### Evening (After 3:30 PM)

1. Review P&L in dashboard
2. Toggle "Enable Trading" OFF (optional)
3. Note down any issues

---

## 🖥️ Step 6: Production Deployment

### Option A: PM2 (Recommended)

Install PM2:
```bash
sudo npm install -g pm2
```

Start bot:
```bash
pm2 start "uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000" --name trading-bot
```

Save config:
```bash
pm2 save
pm2 startup
```

Useful commands:
```bash
pm2 status              # Check status
pm2 logs trading-bot    # View logs
pm2 restart trading-bot # Restart
pm2 stop trading-bot    # Stop
```

### Option B: Systemd Service

Create service file:
```bash
sudo nano /etc/systemd/system/trading-bot.service
```

Paste:
```ini
[Unit]
Description=Chartink Trading Bot
After=network.target

[Service]
User=yourusername
WorkingDirectory=/home/yourusername/trading-bot
ExecStart=/usr/bin/python3 -m uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```

View logs:
```bash
sudo journalctl -u trading-bot -f
```

### Option C: Docker (Optional)

Only if you prefer Docker:
```bash
docker build -t trading-bot .
docker run -d -p 8000:8000 --name trading-bot trading-bot
```

---

## 📱 Step 7: Monitoring

### Dashboard Features

Access: `http://your-vps-ip:8000/dashboard`

- **System Toggle:** Enable/disable trading
- **Capital:** Set trading capital
- **Risk %:** Risk per trade (default 1%)
- **Max Trades:** Daily limit
- **Trading Hours:** Market hours
- **Kite Token:** Update daily
- **P&L Tracking:** Real-time P&L
- **Trade History:** All today's trades

### Telegram Notifications

You'll receive alerts for:
- ✅ Trade executed
- ❌ Trade rejected (with reason)
- 📊 Entry/SL/Target details
- 🔗 Scan link

### Log Files

```bash
# View trades log
cat trades_log.json

# View config
cat config.json

# PM2 logs
pm2 logs trading-bot

# Systemd logs
sudo journalctl -u trading-bot -f
```

---

## ⚠️ Step 8: Risk Management

### Built-in Guards

The bot automatically rejects trades if:
- ❌ System is disabled
- ❌ Outside trading hours (9:15 AM - 3:30 PM)
- ❌ Max daily trades reached
- ❌ Invalid symbol (can't fetch quote)
- ❌ Calculated risk exceeds max SL %

### Adjust Risk Settings

In `config.json`:
```json
"risk_management": {
  "atr_multiplier_sl": 1.5,    // SL = ATR × 1.5
  "atr_multiplier_tp": 3.0,    // TP = ATR × 3.0
  "min_risk_reward": 2.0,       // Minimum R:R = 1:2
  "max_sl_percent": 2.0         // Max SL = 2% of entry
}
```

### Recommended Settings

| Capital | Risk % | Max Trades | Position Size |
|---------|--------|------------|---------------|
| ₹1 Lakh | 1% | 10 | ₹1,000 risk/trade |
| ₹5 Lakh | 1% | 10 | ₹5,000 risk/trade |
| ₹10 Lakh | 0.5% | 15 | ₹5,000 risk/trade |

---

## 🔧 Troubleshooting

### Issue: "Could not fetch quote"

**Cause:** Invalid Kite access token

**Solution:**
1. Generate new access token
2. Update in dashboard
3. Test again

### Issue: "Max daily trades reached"

**Cause:** Hit the `max_trades_per_day` limit

**Solution:**
- Wait for next day, OR
- Increase limit in dashboard, OR
- Reset trades_log.json (not recommended)

### Issue: "Outside trading hours"

**Cause:** Current time not within 9:15 AM - 3:30 PM

**Solution:**
- Check system time: `date`
- Adjust `trading_hours` in config.json if needed
- For testing, temporarily change trading hours

### Issue: Telegram not working

**Cause:** Wrong bot token or chat ID

**Solution:**
1. Test bot manually:
   ```bash
   curl -X POST "https://api.telegram.org/botYOUR_TOKEN/sendMessage" \
     -d "chat_id=YOUR_CHAT_ID" \
     -d "text=Test message"
   ```
2. Verify config.json values
3. Make sure you messaged the bot first

### Issue: Webhook not triggering

**Cause:** Firewall, wrong URL, or wrong secret

**Solution:**
1. Test webhook manually:
   ```bash
   curl -X POST http://your-vps-ip:8000/webhook/chartink \
     -H "Content-Type: application/json" \
     -d '{"symbol":"RELIANCE","action":"BUY","price":2500}'
   ```
2. Check firewall: `sudo ufw allow 8000`
3. Verify webhook secret matches

### Issue: Orders not placing in Kite

**Cause:** Insufficient funds, market closed, or API error

**Solution:**
1. Check Kite funds
2. Verify market is open
3. Check logs for error details
4. Ensure MIS product is enabled

---

## 📊 Performance Expectations

| Metric | Value |
|--------|-------|
| Webhook Latency | ~2ms |
| Quote Fetch | ~50-100ms |
| Order Placement | ~100ms |
| **Total Latency** | **~200-300ms** |

Much faster than n8n (800ms-2s).

---

## 🛡️ Security Checklist

- [ ] Change default webhook secret
- [ ] Use strong password for VPS
- [ ] Enable UFW firewall: `sudo ufw enable`
- [ ] Allow only port 8000 (or use Nginx reverse proxy)
- [ ] Keep API keys secret
- [ ] Don't commit config.json with real keys to Git
- [ ] Use HTTPS in production (Let's Encrypt)

---

## 💰 Cost Breakdown

| Item | Cost |
|------|------|
| VPS (DigitalOcean/AWS/Linode) | $5-10/month |
| Kite Connect API | Free (for personal use) |
| Telegram Bot | Free |
| Chartink Premium | ~₹2000/year |
| **Total** | **~$5-10/month** |

---

## 📞 Support & Resources

- **Kite API Docs:** https://kite.trade/docs/connect/v3/
- **Chartink Help:** https://chartink.com/help
- **Telegram Bot API:** https://core.telegram.org/bots/api

---

## ✅ Quick Start Checklist

- [ ] Install Python dependencies
- [ ] Get Kite API key
- [ ] Get Telegram bot token & chat ID
- [ ] Fill config.json
- [ ] Start the bot
- [ ] Access dashboard
- [ ] Test Telegram notification
- [ ] Set Chartink webhook URL
- [ ] Test webhook manually
- [ ] Generate Kite access token
- [ ] Enable trading
- [ ] Wait for scan to trigger
- [ ] Monitor first trade

---

**Ready to trade? Start with paper trading first! 🚀**
