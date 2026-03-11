# 🚀 DEPLOYMENT CHECKLIST - P0 Critical Fixes

## Pre-Deploy Checklist

- [x] All code changes complete
- [x] Syntax checks passed
- [x] No breaking changes to API

## Deploy Steps

### Step 1: Deploy to Coolify
```bash
# Option A: Via Coolify Dashboard
1. Open https://your-coolify-dashboard.com
2. Find "trading-bot" resource
3. Click "Redeploy" or "Restart"

# Option B: Via SSH (if you have access)
ssh your-server
cd ~/trading-bot
docker-compose down && docker-compose up -d
```

### Step 2: Wait for Startup (30 seconds)
Watch logs for:
```
🚀 Chartink Trading Bot Starting
📊 Dashboard: http://localhost:8000/dashboard
🔗 Webhook: http://localhost:8000/webhook/chartink
```

### Step 3: Verify Deployment
```bash
# Check health
curl https://coolify.themelon.in/

# Should return:
{"status":"running","service":"Chartink Trading Bot","version":"1.0"}
```

### Step 4: Clean Up Orphan GTTs
```bash
curl -X POST https://coolify.themelon.in/api/gtt/cleanup
```

Expected response:
```json
{
  "status": "success",
  "message": "Cancelled X orphan GTTs (Y checked)",
  "details": { ... }
}
```

### Step 5: Verify CORS Fix
```bash
# This should FAIL (CORS blocked)
curl -H "Origin: https://evil-site.com" \
     -I https://coolify.themelon.in/api/positions

# This should WORK (allowed origin)
curl -H "Origin: https://coolify.themelon.in" \
     -I https://coolify.themelon.in/api/positions
```

### Step 6: Check GTT Orders
```bash
curl https://coolify.themelon.in/api/gtt-orders
```

Make sure:
- No orphan WABAG GTTs
- All GTTs have matching open positions

### Step 7: Test Paper Trade (Optional)
```bash
# Enable paper trading first
curl -X POST https://coolify.themelon.in/api/config \
  -H "Content-Type: application/json" \
  -d '{"paper_trading": true}'

# Send test signal
curl -X POST https://coolify.themelon.in/webhook/chartink \
  -H "Content-Type: application/json" \
  -d '{"symbol": "RELIANCE", "action": "BUY", "price": 2500}'
```

### Step 8: Monitor Logs
```bash
# Watch for errors
docker-compose logs -f trading-bot

# Or via Coolify logs tab
```

Look for:
- ✅ "SL GTT placed: XXX"
- ✅ "Position sync: X position(s) marked as closed"
- 🚨 Any ERROR messages

---

## Rollback Plan

If something breaks:

```bash
# Immediate rollback via git
git log --oneline -5  # Find previous commit
git revert HEAD       # Revert last commit
docker-compose restart
```

Or disable trading:
```bash
curl -X POST https://coolify.themelon.in/api/config \
  -H "Content-Type: application/json" \
  -d '{"system_enabled": false}'
```

---

## Post-Deploy Verification

- [ ] Dashboard loads without errors
- [ ] Open positions display correctly
- [ ] GTT orders listed correctly
- [ ] No orphan GTTs remaining
- [ ] Paper trading test works (if tested)
- [ ] Telegram notifications working (if configured)

---

## Support

If issues arise:
1. Check logs: `docker-compose logs -f`
2. Disable system via API
3. Contact support with log output

---

Good luck! 🚀
