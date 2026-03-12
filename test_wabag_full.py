#!/usr/bin/env python3
"""
Full diagnostic test for WABAG trade failure
"""
import json
import asyncio
from datetime import datetime, time

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

print("=" * 70)
print("DIAGNOSTIC REPORT: Why WABAG Trade Didn't Execute")
print("=" * 70)
print()

# WABAG Data from user
wabag_data = {
    "symbol": "WABAG",
    "name": "Va Tech Wabag Limited",
    "price": 1286,
    "change_percent": 7.32,
    "volume": 1140810
}

print(f"📊 Stock: {wabag_data['name']} ({wabag_data['symbol']})")
print(f"💰 Price: ₹{wabag_data['price']}")
print(f"📈 Change: +{wabag_data['change_percent']}%")
print(f"📊 Volume: {wabag_data['volume']:,}")
print()

# Check config issues
print("=" * 70)
print("CONFIGURATION CHECK")
print("=" * 70)

issues = []
warnings = []

# 1. System enabled
if not config.get("system_enabled"):
    issues.append("❌ System is DISABLED")
else:
    print("✅ System is enabled")

# 2. Trading hours
now = datetime.now().time()
start_str = config.get("trading_hours", {}).get("start", "09:15")
end_str = config.get("trading_hours", {}).get("end", "15:30")
start_time = datetime.strptime(start_str, "%H:%M").time()
end_time = datetime.strptime(end_str, "%H:%M").time()

if start_time <= now <= end_time:
    print(f"✅ Within trading hours ({start_str}-{end_str})")
else:
    issues.append(f"❌ Outside trading hours (now: {now.strftime('%H:%M')}, hours: {start_str}-{end_str})")

# 3. Kite API credentials
kite = config.get("kite", {})
if not kite.get("api_key"):
    issues.append("❌ Kite API Key not configured")
else:
    print("✅ Kite API Key is set")

if not kite.get("access_token"):
    issues.append("❌ Kite Access Token not configured")
else:
    print("✅ Kite Access Token is set")

# 4. Trade budget
if "trade_budget" not in config:
    warnings.append("⚠️  trade_budget not set in config (using default ₹50,000)")
else:
    print(f"✅ Trade budget: ₹{config['trade_budget']:,.2f}")

# 5. Capital check
capital = config.get("capital", 0)
print(f"ℹ️  Capital: ₹{capital:,.2f}")

# 6. Position sizing check
from calculator import calculate_intelligent_position

# Simulate with different ATR values
atr_values = [20, 30, 40, 50, 60, 70, 80]
print()
print("=" * 70)
print("POSITION SIZING ANALYSIS")
print("=" * 70)
print(f"{'ATR':>8} | {'Qty':>5} | {'Risk':>10} | {'Value':>12} | {'Status':>10}")
print("-" * 70)

trade_budget = config.get("trade_budget", 50000)
risk_percent = config.get("risk_percent", 1.0)

for atr in atr_values:
    params = calculate_intelligent_position(
        current_price=wabag_data['price'],
        atr=atr,
        capital=capital,
        risk_percent=risk_percent,
        trade_budget=trade_budget,
        direction="BUY"
    )
    
    if params:
        status = "OK"
        print(f"{atr:>8} | {params.quantity:>5} | ₹{params.risk_amount:>8.2f} | ₹{params.quantity * params.entry:>10.2f} | {status:>10}")
    else:
        status = "REJECTED"
        # Calculate why
        sl_dist = atr * 1.5
        risk_amt = capital * risk_percent / 100
        risk_per_share = sl_dist
        if risk_per_share > 0:
            qty_risk = int(risk_amt / risk_per_share)
        else:
            qty_risk = 0
        qty_budget = int(trade_budget * 0.98 / wabag_data['price'])
        print(f"{atr:>8} | {0:>5} | - | - | {status} (qty=0, risk_max={qty_risk}, budget_max={qty_budget})")

print()
print("=" * 70)
print("POSSIBLE REASONS WABAG DIDN'T TRADE")
print("=" * 70)

reasons = []

# Based on previous trades in log
trades_log = []
try:
    with open("trades_log.json", "r") as f:
        trades_log = json.load(f)
except:
    pass

failed_trades = [t for t in trades_log if t.get("status") == "FAILED"]
if failed_trades:
    reasons.append(f"1. Previous trades FAILED ({len(failed_trades)} failed orders in log)")
    reasons.append("   → Check Kite API credentials and access token validity")

if capital < 10000:
    reasons.append(f"2. LOW CAPITAL (₹{capital:,.2f})")
    reasons.append("   → With 1% risk, max risk per trade is only ₹50")
    reasons.append("   → If ATR > ₹33, you cannot buy even 1 share of WABAG at ₹1286")

if not kite.get("access_token") or len(kite.get("access_token", "")) < 20:
    reasons.append("3. INVALID/MISSING KITE ACCESS TOKEN")
    reasons.append("   → Access tokens expire daily and need regeneration")

# Check if webhook was actually received
reasons.append("4. WEBHOOK NOT RECEIVED")
reasons.append("   → Check if Chartink alert was triggered")
reasons.append("   → Check if webhook URL is correct and accessible")
reasons.append("   → Check if webhook secret matches")

reasons.append("5. CHARTINK CONFIGURATION ISSUE")
reasons.append("   → Verify scan is set to trigger correctly")
reasons.append("   → Check if webhook URL is properly configured in Chartink")
reasons.append("   → Ensure webhook is sent as POST with correct format")

if issues:
    print()
    print("CRITICAL ISSUES FOUND:")
    for issue in issues:
        print(f"  {issue}")

print()
print("LIKELY REASONS (ranked by probability):")
for reason in reasons:
    print(f"  {reason}")

print()
print("=" * 70)
print("RECOMMENDED ACTIONS")
print("=" * 70)
print("""
1. CHECK IF WEBHOOK WAS RECEIVED:
   - Check server logs for incoming webhook requests
   - Test webhook manually: curl -X POST http://localhost:8000/webhook/chartink

2. VERIFY KITE API CONNECTION:
   - Go to dashboard → Test Kite Connection
   - Or run: curl http://localhost:8000/api/test-kite

3. REGENERATE KITE ACCESS TOKEN:
   - Login to Kite and generate new request token
   - Update in dashboard or config.json

4. CHECK CHARTINK WEBHOOK CONFIG:
   - URL should be: http://YOUR_IP:8000/webhook/chartink
   - Method: POST
   - Content-Type: application/json
   - Secret should match config.json (currently: MelonBot123)

5. MONITOR LOGS:
   - Run: tail -f /var/log/trading-bot/*.log
   - Or check journalctl if running as service

6. TEST MANUALLY:
   curl -X POST http://localhost:8000/webhook/chartink \\
     -H "Content-Type: application/json" \\
     -d '{"symbol":"WABAG","action":"BUY","price":1286}'
""")
