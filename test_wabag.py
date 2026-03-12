#!/usr/bin/env python3
"""
Test script to understand why WABAG trade might have failed.
"""
import json
from calculator import calculate_intelligent_position, calculate_atr

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

# WABAG details
symbol = "WABAG"
price = 1286  # From user's data
volume = 1140810
change_percent = 7.32

# Config values
capital = config.get("capital", 100000)
risk_percent = config.get("risk_percent", 1.0)
trade_budget = config.get("trade_budget", 50000)  # Default ₹50k
risk_config = config.get("risk_management", {})

print("=" * 60)
print(f"Testing trade for: {symbol}")
print("=" * 60)
print(f"Stock Price: ₹{price}")
print(f"Volume: {volume:,}")
print(f"Change %: {change_percent}%")
print()
print(f"Config Capital: ₹{capital:,.2f}")
print(f"Config Risk %: {risk_percent}%")
print(f"Trade Budget: ₹{trade_budget:,.2f}")
print(f"Daily Risk Amount: ₹{capital * risk_percent / 100:,.2f}")
print()

# Simulate ATR calculation (typical for this price range)
# For a stock at ₹1286 with 7% move, ATR might be around ₹30-50
simulated_atr = 39.4  # Estimated based on price volatility

print(f"Estimated ATR: ₹{simulated_atr}")
print()

# Test position calculation
trade_params = calculate_intelligent_position(
    current_price=price,
    atr=simulated_atr,
    capital=capital,
    risk_percent=risk_percent,
    trade_budget=trade_budget,
    direction="BUY",
    atr_sl_multiplier=risk_config.get("atr_multiplier_sl", 1.5),
    atr_tp_multiplier=risk_config.get("atr_multiplier_tp", 3.0),
    min_rr=risk_config.get("min_risk_reward", 2.0),
    max_sl_percent=risk_config.get("max_sl_percent", 2.0),
    lot_size=1
)

if trade_params:
    print("✅ Trade would be ACCEPTED")
    print(f"   Entry: ₹{trade_params.entry}")
    print(f"   Stop Loss: ₹{trade_params.stop_loss}")
    print(f"   Target: ₹{trade_params.target}")
    print(f"   Quantity: {trade_params.quantity} shares")
    print(f"   Risk Amount: ₹{trade_params.risk_amount:,.2f}")
    print(f"   R:R = 1:{trade_params.risk_reward}")
    print(f"   Total Value: ₹{trade_params.quantity * trade_params.entry:,.2f}")
else:
    print("❌ Trade REJECTED by position calculator")
    print()
    
    # Debug: Check what constraint is failing
    print("DEBUG - Checking constraints:")
    
    # Calculate SL distance
    atr_sl_multiplier = risk_config.get("atr_multiplier_sl", 1.5)
    sl_distance = simulated_atr * atr_sl_multiplier
    print(f"   SL Distance: ₹{sl_distance:.2f} ({sl_distance/price*100:.2f}% of price)")
    
    # Budget constraint
    qty_from_budget = int(trade_budget * 0.98 / price)
    print(f"   Max qty from budget (₹{trade_budget}): {qty_from_budget} shares")
    
    # Risk constraint
    risk_amount = capital * risk_percent / 100
    risk_per_share = sl_distance
    if risk_per_share > 0:
        qty_from_risk = int(risk_amount / risk_per_share)
        print(f"   Max qty from risk (₹{risk_amount:.2f}): {qty_from_risk} shares")
    else:
        print(f"   Risk per share too small!")
        qty_from_risk = 0
    
    # The limiting factor
    quantity = min(qty_from_budget, qty_from_risk)
    print(f"   Final calculated qty: {quantity}")
    
    if quantity < 1:
        print("\n🔴 REASON: Quantity < 1 - Trade cannot be placed!")
        if qty_from_risk < 1:
            print("    → Risk constraint is the limiting factor")
            print(f"    → To buy 1 share at ₹{price}, you need risk amount ≥ ₹{risk_per_share:.2f}")
            print(f"    → Current risk amount: ₹{risk_amount:.2f}")
            needed_capital = risk_per_share * 100 / risk_percent
            print(f"    → Minimum capital needed: ₹{needed_capital:,.2f}")
        if qty_from_budget < 1:
            print("    → Budget constraint is the limiting factor")

print("\n" + "=" * 60)
print("ANALYSIS:")
print("=" * 60)

# Check common issues
issues = []

if not config.get("system_enabled"):
    issues.append("System is disabled in config")

if not config.get("kite", {}).get("api_key"):
    issues.append("Kite API key not configured")

if not config.get("kite", {}).get("access_token"):
    issues.append("Kite access token not configured")

# Check trading hours
from datetime import datetime, time
now = datetime.now().time()
start_time = datetime.strptime(config.get("trading_hours", {}).get("start", "09:15"), "%H:%M").time()
end_time = datetime.strptime(config.get("trading_hours", {}).get("end", "15:30"), "%H:%M").time()

if not (start_time <= now <= end_time):
    issues.append(f"Current time ({now.strftime('%H:%M')}) is outside trading hours ({start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')})")

# Check if trade_budget is set
if "trade_budget" not in config:
    issues.append("trade_budget not set in config (using default ₹50,000)")

if issues:
    print("Potential issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("No obvious configuration issues found.")
