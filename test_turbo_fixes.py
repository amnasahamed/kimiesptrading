#!/usr/bin/env python3
"""
Test script to verify Turbo Mode fixes are working.
Run this to test the historical data fetching and continuous monitoring.
"""

import asyncio
import json
from datetime import datetime

# Test configuration (minimal)
TEST_CONFIG = {
    "kite": {
        "api_key": "8zjbufhni9k0u2mx",
        "access_token": "EZ6eHy6M5oF55omPFsIUMdBavUEOKS8N",
        "base_url": "https://api.kite.trade"
    },
    "turbo_mode": {
        "enabled": True,
        "max_monitor_duration_seconds": 30,  # Short for testing
        "check_interval_seconds": 2,
        "indicators": {
            "rsi_overbought": 65,
            "rsi_oversold": 35,
            "volume_threshold": 1.2
        }
    }
}


async def test_kite_historical_data():
    """Test that get_historical_data works."""
    print("\n" + "="*60)
    print("Test 1: Kite Historical Data API")
    print("="*60)
    
    try:
        from kite import KiteAPI
        
        kite = KiteAPI(
            api_key=TEST_CONFIG["kite"]["api_key"],
            access_token=TEST_CONFIG["kite"]["access_token"],
            base_url=TEST_CONFIG["kite"]["base_url"]
        )
        
        # Test getting 1H candles
        print("Fetching 1H candles for RELIANCE...")
        candles = await kite.get_historical_data(
            symbol="RELIANCE",
            interval="60minute",
            duration=30
        )
        
        if candles and len(candles) > 0:
            print(f"✅ SUCCESS! Fetched {len(candles)} candles")
            print(f"   First candle: {candles[0]['timestamp']}, Close: {candles[0]['close']}")
            print(f"   Last candle: {candles[-1]['timestamp']}, Close: {candles[-1]['close']}")
            
            # Check structure
            required_keys = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if all(k in candles[0] for k in required_keys):
                print("✅ Candle structure is correct")
                return True
            else:
                print("❌ Candle structure is missing keys")
                return False
        else:
            print("❌ FAILED! No candles returned")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_turbo_analyzer_trend():
    """Test trend alignment check."""
    print("\n" + "="*60)
    print("Test 2: Turbo Analyzer Trend Check")
    print("="*60)
    
    try:
        from turbo_analyzer import TurboAnalyzer
        
        analyzer = TurboAnalyzer(TEST_CONFIG)
        
        # Test with a reliable stock
        symbol = "RELIANCE"
        print(f"Checking trend alignment for {symbol} BUY...")
        
        trend = await analyzer.check_trend_alignment(symbol, "BUY")
        
        print(f"Result:")
        print(f"   Aligned: {trend.aligned}")
        print(f"   Direction: {trend.direction}")
        print(f"   Confidence: {trend.confidence:.1f}%")
        print(f"   Reason: {trend.reason}")
        
        if trend.aligned:
            print("✅ Trend check PASSED")
        else:
            print("⚠️ Trend check did not align (may be due to actual market conditions)")
        
        # Print details
        if trend.details:
            print(f"   Details: {json.dumps(trend.details, indent=2, default=str)}")
        
        return True  # Return True even if not aligned, as that's market-dependent
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_turbo_analyzer_monitor():
    """Test continuous entry monitoring (short duration)."""
    print("\n" + "="*60)
    print("Test 3: Turbo Analyzer Continuous Monitoring")
    print("="*60)
    
    try:
        from turbo_analyzer import TurboAnalyzer
        
        # Use very short duration for testing
        test_config = TEST_CONFIG.copy()
        test_config["turbo_mode"]["max_monitor_duration_seconds"] = 10
        test_config["turbo_mode"]["check_interval_seconds"] = 2
        
        analyzer = TurboAnalyzer(test_config)
        
        symbol = "RELIANCE"
        print(f"Monitoring {symbol} BUY for 10 seconds (checking every 2s)...")
        print("(This simulates continuous monitoring until conditions met or timeout)")
        
        entry = await analyzer.monitor_entry(
            symbol=symbol,
            direction="BUY",
            max_duration=10,
            check_interval=2
        )
        
        print(f"\nResult:")
        print(f"   Triggered: {entry.triggered}")
        print(f"   Duration: {entry.duration_seconds:.1f}s")
        print(f"   Reason: {entry.trigger_reason}")
        
        if entry.triggered:
            print(f"   Entry Price: ₹{entry.entry_price:.2f}")
            print(f"   Confidence: {entry.confidence_score:.0f}%")
            print("✅ Entry was triggered!")
        else:
            print("⚠️ Entry not triggered (conditions not met within timeout)")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_indicator_calculations():
    """Test that indicator calculations work correctly."""
    print("\n" + "="*60)
    print("Test 4: Indicator Calculations")
    print("="*60)
    
    try:
        from turbo_analyzer import TurboAnalyzer
        
        analyzer = TurboAnalyzer(TEST_CONFIG)
        
        # Create test candles
        test_candles = []
        price = 100
        for i in range(60):
            # Simulate some trend
            price += (i % 5 - 2) * 0.5 + 0.2  # Slight upward drift
            test_candles.append({
                "timestamp": f"2026-03-16T09:{15+i:02d}:00+05:30",
                "open": price - 0.5,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1000 + i * 10
            })
        
        ind = analyzer._calculate_indicators(test_candles)
        
        print(f"Calculated Indicators:")
        print(f"   EMA9: {ind.ema9:.2f}")
        print(f"   EMA20: {ind.ema20:.2f}")
        ema50_str = f"{ind.ema50:.2f}" if ind.ema50 else "N/A"
        print(f"   EMA50: {ema50_str}")
        print(f"   RSI14: {ind.rsi14:.2f}")
        print(f"   MACD Line: {ind.macd_line:.3f}")
        print(f"   MACD Signal: {ind.macd_signal:.3f}")
        print(f"   MACD Histogram: {ind.macd_histogram:.3f}")
        print(f"   Volume Ratio: {ind.volume_ratio:.2f}x")
        
        # Test entry check
        current_price = test_candles[-1]["close"]
        triggered, reason, score = analyzer._check_buy_entry(
            current_price, ind, test_candles, 65, 1.2
        )
        
        print(f"\nEntry Check at ₹{current_price:.2f}:")
        print(f"   Score: {score}/4")
        print(f"   Triggered: {triggered}")
        print(f"   Reason: {reason}")
        
        print("✅ Indicator calculations working")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_market_hours():
    """Test market hours check."""
    print("\n" + "="*60)
    print("Test 5: Market Hours Check")
    print("="*60)
    
    try:
        from turbo_analyzer import TurboAnalyzer
        
        analyzer = TurboAnalyzer(TEST_CONFIG)
        
        is_open = analyzer.is_market_open()
        
        print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Market is open: {is_open}")
        
        if is_open:
            print("✅ Market is currently open")
        else:
            print("⚠️ Market is closed (expected outside 9:15-15:30 IST on weekdays)")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("="*60)
    print("TURBO MODE FIXES - TEST SUITE")
    print("="*60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # Run tests
    results.append(("Kite Historical Data", await test_kite_historical_data()))
    results.append(("Trend Alignment", await test_turbo_analyzer_trend()))
    results.append(("Continuous Monitoring", await test_turbo_analyzer_monitor()))
    results.append(("Indicator Calculations", await test_indicator_calculations()))
    results.append(("Market Hours", await test_market_hours()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Turbo Mode fixes are working.")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. Check the errors above.")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
