# WhatsApp & Telegram Notifications

## Overview

The trading bot now supports editable WhatsApp and Telegram notifications directly from the **Settings** page. You'll receive instant alerts when:

1. **Trade Entry** - When a live trade is executed with entry price, SL, and target
2. **Trade Exit** - When a position is closed with booked P&L (profit or loss)

**Note:** WhatsApp alerts are for **LIVE trades only**. Paper trades only send Telegram notifications.

---

## Configuration (Dashboard Settings)

### Method 1: Using the Settings Page (Recommended)

1. Open the Dashboard → Click **Configuration** in the sidebar
2. Scroll down to **Notification Settings**
3. Configure Telegram and/or WhatsApp:

#### Telegram Setup
1. Enable **Telegram Notifications** toggle
2. Enter your **Bot Token** (from @BotFather)
3. Enter your **Chat ID** (get from @userinfobot)
4. Click **"Send Test Message"** to verify
5. Click **"Save Settings"**

#### WhatsApp Setup
1. Enable **WhatsApp Notifications** toggle
2. Enter your **WasenderAPI Key** (from wasenderapi.com)
3. Enter your **Recipient Number** with country code (e.g., `919745010715`)
4. Click **"Send Test Message"** to verify
5. Click **"Save Settings"**

### Method 2: Manual Config (config.json)

```json
{
  "telegram": {
    "bot_token": "your-bot-token",
    "chat_id": "your-chat-id",
    "enabled": true
  },
  "whatsapp": {
    "api_key": "your-wasender-api-key",
    "recipient": "919745010715",
    "enabled": true
  }
}
```

---

## WasenderAPI Documentation

**Official Docs:** https://docs.wasenderapi.com  
**Base URL:** `https://www.wasenderapi.com`

### Getting Your WasenderAPI Key

1. Sign up at https://wasenderapi.com
2. Go to your **Dashboard** → **Settings**
3. Generate or copy your **API Key**
4. The API key starts working immediately

### API Endpoint

```http
POST https://www.wasenderapi.com/api/send-message
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json

{
  "to": "919745010715",
  "text": "Hello from WasenderAPI!"
}
```

---

## Telegram Bot Setup

1. Message **@BotFather** on Telegram
2. Create a new bot with `/newbot`
3. Copy the **Bot Token** provided
4. Message **@userinfobot** to get your **Chat ID**
5. Enter both in the dashboard settings

---

## Message Format Examples

### Entry Alert
```
🔴 LIVE TRADE - ENTRY ALERT

Symbol: RELIANCE
Quantity: 100
Entry Price: ₹2,450.50
Stop Loss: ₹2,400.00
Target: ₹2,550.00

Risk per share: ₹50.50
Potential Reward: ₹99.50

Good luck! 🚀
```

### Exit Alert (Profit)
```
🔴 LIVE - 🟢 PROFIT BOOKED

Symbol: RELIANCE
Quantity: 100
Entry Price: ₹2,450.50
Exit Price: ₹2,550.00
Exit Reason: TARGET_HIT

✅ P&L: +₹9,950.00

Keep learning! 📈
```

### Exit Alert (Loss)
```
🔴 LIVE - 🔴 LOSS BOOKED

Symbol: RELIANCE
Quantity: 100
Entry Price: ₹2,450.50
Exit Price: ₹2,400.00
Exit Reason: STOP_LOSS

❌ P&L: -₹5,050.00

Keep learning! 📈
```

---

## Testing

### Test from Dashboard
- Navigate to **Configuration** tab
- Click **"Send Test Message"** button next to Telegram or WhatsApp
- Look for toast notification confirming success/failure

### Test via API

```bash
# Test Telegram
curl -X POST http://localhost:8000/api/test-telegram

# Test WhatsApp
curl -X POST http://localhost:8000/api/test-whatsapp
```

---

## Troubleshooting

### "Failed to send message"

**For Telegram:**
- Check Bot Token format (should be like `123456789:ABCdef...`)
- Verify Chat ID is correct (numeric, no quotes)
- Make sure you started a chat with your bot

**For WhatsApp:**
- Verify API key from WasenderAPI dashboard
- Check recipient number format (country code + number, no `+`)
- Ensure recipient has WhatsApp installed

### Toast Notifications Not Showing

- Check browser console for JavaScript errors
- Verify server is running: `curl http://localhost:8000/health`

### Changes Not Saving

- Check **Save Settings** button shows success toast
- Refresh page to verify settings persisted
- Check server logs: `tail -f app.log`

---

## Security Notes

- API keys are **masked** in the dashboard (show as `***`)
- Keys are stored in `config.json` on the server
- Never commit API keys to git
- The recipient should be your own number

---

## UI/UX Features

### Toast Notifications
Non-intrusive toast notifications appear for:
- ✅ Settings saved successfully
- ✅ Test message sent
- ❌ Errors with details
- ℹ️ Info messages

### Visual Indicators
- **WhatsApp Badge** in header shows ✓ when configured
- **Toggle switches** show enabled/disabled state
- **Test buttons** provide immediate feedback

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config` | GET | Get current configuration (keys masked) |
| `/api/config` | POST | Update configuration |
| `/api/test-telegram` | POST | Send test Telegram message |
| `/api/test-whatsapp` | POST | Send test WhatsApp message |

---

## Need Help?

- **Telegram Bot Issues:** https://core.telegram.org/bots
- **WasenderAPI Issues:** https://docs.wasenderapi.com
- **Dashboard Issues:** Check browser console and server logs
