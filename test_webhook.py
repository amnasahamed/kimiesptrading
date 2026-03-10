#!/usr/bin/env python3
"""
Test script for the Chartink webhook
"""
import httpx
import sys
from datetime import datetime

BASE_URL = "http://localhost:8000"


def test_health():
    """Test if server is running."""
    print("Testing health endpoint...")
    try:
        r = httpx.get(f"{BASE_URL}/", timeout=5)
        print(f"✅ Server is running: {r.json()}")
        return True
    except Exception as e:
        print(f"❌ Server not running: {e}")
        return False


def test_config():
    """Test config endpoint."""
    print("\nTesting config endpoint...")
    try:
        r = httpx.get(f"{BASE_URL}/api/config", timeout=5)
        config = r.json()
        print(f"✅ Config loaded")
        print(f"   System enabled: {config.get('system_enabled')}")
        print(f"   Capital: ₹{config.get('capital')}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_stats():
    """Test stats endpoint."""
    print("\nTesting stats endpoint...")
    try:
        r = httpx.get(f"{BASE_URL}/api/stats", timeout=5)
        stats = r.json()
        print(f"✅ Stats loaded")
        print(f"   Today's trades: {stats.get('today_trades')}")
        print(f"   Today's P&L: ₹{stats.get('today_pnl')}")
        print(f"   Within trading hours: {stats.get('within_trading_hours')}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_quote(symbol: str = "RELIANCE"):
    """Test quote endpoint."""
    print(f"\nTesting quote endpoint for {symbol}...")
    try:
        r = httpx.get(f"{BASE_URL}/api/quote/{symbol}", timeout=10)
        if r.status_code == 200:
            quote = r.json()
            print(f"✅ Quote received")
            print(f"   LTP: ₹{quote.get('ltp')}")
            print(f"   Change: {quote.get('change_percent')}%")
            return True
        else:
            print(f"⚠️  Quote not available (Kite token may be invalid)")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_webhook_post(symbol: str = "RELIANCE", action: str = "BUY", price: float = 2500):
    """Test webhook POST endpoint."""
    print(f"\nTesting webhook POST for {symbol} {action}...")
    
    # Single stock format
    payload = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "alert_name": "Momentum Breakout Test"
    }
    
    start = datetime.now()
    try:
        r = httpx.post(
            f"{BASE_URL}/webhook/chartink",
            json=payload,
            timeout=30
        )
        elapsed = (datetime.now() - start).total_seconds() * 1000
        
        result = r.json()
        print(f"✅ Response received in {elapsed:.0f}ms")
        print(f"   Status: {result.get('status')}")
        
        if result.get('status') == 'REJECTED':
            print(f"   Reason: {result.get('reason')}")
        elif result.get('trade_params'):
            tp = result['trade_params']
            print(f"   Entry: ₹{tp['entry']}")
            print(f"   SL: ₹{tp['stop_loss']}")
            print(f"   Target: ₹{tp['target']}")
            print(f"   Qty: {tp['quantity']}")
            print(f"   R:R: 1:{tp['risk_reward']}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_webhook_batch():
    """Test webhook with Chartink sample data (comma-separated)."""
    print("\nTesting webhook with Chartink sample format...")
    
    # Sample data from user's Chartink alert
    payload = {
        "stocks": "SEPOWER,ASTEC,EDUCOMP,KSERASERA,IOLCP,GUJAPOLLO,EMCO",
        "trigger_prices": "3.75,541.8,2.1,0.2,329.6,166.8,1.25",
        "triggered_at": "2:34 pm",
        "scan_name": "Short term breakouts",
        "scan_url": "short-term-breakouts",
        "alert_name": "Alert for Short term breakouts",
        "webhook_url": "http://your-web-hook-url.com"
    }
    
    print(f"   Stocks: {payload['stocks']}")
    print(f"   Count: {len(payload['stocks'].split(','))} stocks")
    
    start = datetime.now()
    try:
        r = httpx.post(
            f"{BASE_URL}/webhook/chartink",
            json=payload,
            timeout=60  # Longer timeout for multiple stocks
        )
        elapsed = (datetime.now() - start).total_seconds() * 1000
        
        result = r.json()
        print(f"✅ Response received in {elapsed:.0f}ms")
        print(f"   Status: {result.get('status')}")
        
        if result.get('results'):
            print(f"   Total stocks: {result.get('total_stocks')}")
            print(f"   Processed: {result.get('processed')}")
            for r in result['results']:
                status_emoji = "✅" if r.get('status') == 'SUCCESS' else "⚠️"
                print(f"   {status_emoji} {r.get('symbol')}: {r.get('status')}")
                if r.get('trade_params'):
                    tp = r['trade_params']
                    print(f"      Entry: ₹{tp['entry']}, SL: ₹{tp['stop_loss']}, Qty: {tp['quantity']}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_webhook_get(symbol: str = "RELIANCE", action: str = "BUY"):
    """Test webhook GET endpoint."""
    print(f"\nTesting webhook GET for {symbol} {action}...")
    
    start = datetime.now()
    try:
        r = httpx.get(
            f"{BASE_URL}/webhook/chartink",
            params={"symbol": symbol, "action": action},
            timeout=30
        )
        elapsed = (datetime.now() - start).total_seconds() * 1000
        
        result = r.json()
        print(f"✅ Response received in {elapsed:.0f}ms")
        print(f"   Status: {result.get('status')}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_telegram():
    """Test Telegram notification."""
    print("\nTesting Telegram...")
    try:
        r = httpx.post(f"{BASE_URL}/api/test-telegram", timeout=10)
        if r.status_code == 200:
            print("✅ Telegram test message sent")
            return True
        else:
            print("⚠️  Telegram not configured or failed")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    print("=" * 50)
    print("🧪 Chartink Trading Bot Tests")
    print("=" * 50)
    
    if not test_health():
        print("\n❌ Server is not running. Start it first:")
        print("   python chartink_webhook.py")
        sys.exit(1)
    
    test_config()
    test_stats()
    test_quote()
    test_telegram()
    
    print("\n" + "=" * 50)
    print("Webhook Tests (will use Kite API)")
    print("=" * 50)
    
    # Ask before testing webhooks (requires valid Kite token)
    response = input("\nTest webhook with Kite API? (y/n): ")
    if response.lower() == 'y':
        test_webhook_post()
        test_webhook_get()
        
        # Test batch format
        response2 = input("\nTest BATCH webhook (multiple stocks)? (y/n): ")
        if response2.lower() == 'y':
            test_webhook_batch()
    
    print("\n" + "=" * 50)
    print("✅ Tests complete")
    print("=" * 50)
    print(f"\nDashboard: http://localhost:8000/dashboard")
    print(f"Webhook URL: http://localhost:8000/webhook/chartink")
    print(f"Batch URL: http://localhost:8000/webhook/chartink/form")


if __name__ == "__main__":
    main()
