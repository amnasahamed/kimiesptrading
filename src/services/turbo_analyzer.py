"""
Turbo Analyzer - Multi-Timeframe Signal Confirmation
====================================================

Provides advanced entry confirmation using:
- 4H & 1H timeframe for trend alignment
- 1M timeframe for optimal entry timing
- Technical indicators: EMA, MACD, RSI, Volume

Usage:
    analyzer = TurboAnalyzer(config)
    
    # Check trend alignment
    trend = await analyzer.check_trend_alignment("RELIANCE", "BUY")
    if trend.aligned:
        # Monitor for entry - CONTINUOUSLY until conditions are met
        entry = await analyzer.monitor_entry("RELIANCE", "BUY", max_duration=300)
        if entry.triggered:
            # Execute trade
            pass
"""

import json
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, time as dt_time
from src.utils.time_utils import ist_naive
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import statistics

# Import Kite API for data fetching
try:
    from src.services.kite_service import KiteService as KiteAPI
except ImportError:
    KiteAPI = Any


@dataclass
class TrendResult:
    """Result of trend alignment check"""
    aligned: bool
    direction: str  # 'LONG', 'SHORT', 'NEUTRAL'
    confidence: float  # 0-100
    reason: str
    details: Dict[str, Any]


@dataclass
class EntryResult:
    """Result of entry monitoring"""
    triggered: bool
    entry_price: Optional[float]
    trigger_reason: str
    confidence_score: float  # 0-100
    indicators_at_entry: Dict[str, Any]
    duration_seconds: float


@dataclass
class IndicatorSet:
    """Collection of technical indicators"""
    ema9: float
    ema20: float
    ema50: Optional[float]
    rsi14: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    volume_sma20: float
    current_volume: float
    volume_ratio: float


class TurboAnalyzer:
    """
    Multi-timeframe analyzer for optimal trade entries.
    
    Process:
    1. Verify 4H and 1H trend alignment (can be configured)
    2. Monitor 1M chart for pullback to EMA
    3. Confirm with MACD crossover and RSI
    4. Execute when volume confirms
    
    CONTINUOUS MONITORING: Keeps checking every few seconds until
    entry conditions are met OR max_duration is reached.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.turbo_config = config.get("turbo_mode", {})
        self.indicators_config = self.turbo_config.get("indicators", {})
        self.kite = None  # Will be initialized on first use
        
        # Cache for candle data (symbol -> {timeframe: {timestamp: candles}})
        self._candle_cache: Dict[str, Dict[str, Dict[str, List[dict]]]] = {}
        self._cache_ttl = 30  # seconds (reduced for more frequent updates)
        
        # Market hours (IST)
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
    
    def _get_kite(self) -> KiteAPI:
        """Lazy initialization of Kite API"""
        if self.kite is None:
            from src.services.kite_service import KiteService
            self.kite = KiteService()
        return self.kite
    
    def is_market_open(self) -> bool:
        """Check if market is currently open (IST)."""
        now = ist_naive()
        current_time = now.time()
        
        # Check if it's a weekday (Monday=0, Friday=4)
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        
        # Check market hours
        return self.market_open <= current_time <= self.market_close
    
    async def check_trend_alignment(self, symbol: str, direction: str) -> TrendResult:
        """
        Check if 4H and 1H trends align with signal direction.
        
        Args:
            symbol: Stock symbol
            direction: 'BUY' or 'SELL'
            
        Returns:
            TrendResult with alignment status
        """
        direction = direction.upper()
        
        # Get timeframe configuration
        timeframes = self.turbo_config.get("timeframes", {})
        trend_timeframes = timeframes.get("trend", ["4hour", "1hour"])
        
        # Allow single timeframe or multiple
        check_4h = "4hour" in trend_timeframes or "4hour" in trend_timeframes
        check_1h = "1hour" in trend_timeframes or "1hour" in trend_timeframes
        
        try:
            candles_4h = []
            candles_1h = []
            
            # Fetch 4H candles if needed
            if check_4h:
                candles_4h = await self._fetch_candles(symbol, "4hour", 50)
                if not candles_4h or len(candles_4h) < 20:
                    print(f"⚠️ TURBO: Insufficient 4H data for {symbol}, falling back to 1H only")
                    check_4h = False
            
            # Fetch 1H candles if needed
            if check_1h:
                candles_1h = await self._fetch_candles(symbol, "1hour", 50)
                if not candles_1h or len(candles_1h) < 20:
                    print(f"⚠️ TURBO: Insufficient 1H data for {symbol}")
                    if not check_4h:
                        return TrendResult(
                            aligned=False,
                            direction="NEUTRAL",
                            confidence=0,
                            reason="Insufficient data for trend analysis",
                            details={}
                        )
                    check_1h = False
            
            # If we have no data at all
            if not candles_4h and not candles_1h:
                return TrendResult(
                    aligned=False,
                    direction="NEUTRAL",
                    confidence=0,
                    reason="No historical data available",
                    details={}
                )
            
            # Calculate indicators for available timeframes
            indicators_4h = self._calculate_indicators(candles_4h) if candles_4h else None
            indicators_1h = self._calculate_indicators(candles_1h) if candles_1h else None
            
            # Use 1H price if available, else 4H
            current_price = (indicators_1h.ema20 if indicators_1h else 
                           indicators_4h.ema20 if indicators_4h else 0)
            
            if current_price == 0:
                return TrendResult(
                    aligned=False,
                    direction="NEUTRAL",
                    confidence=0,
                    reason="Could not determine current price",
                    details={}
                )
            
            # Determine trend for each timeframe
            def get_trend_direction(indicators, price):
                if not indicators:
                    return "NEUTRAL"
                if price > indicators.ema20:
                    return "BULLISH"
                elif price < indicators.ema20:
                    return "BEARISH"
                return "NEUTRAL"
            
            trend_4h = get_trend_direction(indicators_4h, current_price) if indicators_4h else None
            trend_1h = get_trend_direction(indicators_1h, current_price) if indicators_1h else None
            
            # Check alignment based on available timeframes
            if direction in ["BUY", "LONG"]:
                # For BUY: need bullish trend
                aligned_4h = trend_4h == "BULLISH" if indicators_4h else True  # If no data, assume OK
                aligned_1h = trend_1h == "BULLISH" if indicators_1h else True
                
                if aligned_4h and aligned_1h:
                    confidence = self._calculate_trend_confidence(
                        indicators_4h, indicators_1h, current_price, "BULLISH"
                    )
                    return TrendResult(
                        aligned=True,
                        direction="LONG",
                        confidence=confidence,
                        reason=f"Trend aligned bullish ({'4H+1H' if indicators_4h and indicators_1h else '1H' if indicators_1h else '4H'})",
                        details={
                            "price": current_price,
                            "trend_4h": trend_4h,
                            "trend_1h": trend_1h,
                            "ema20_1h": indicators_1h.ema20 if indicators_1h else None,
                            "rsi_1h": indicators_1h.rsi14 if indicators_1h else None,
                        }
                    )
                else:
                    return TrendResult(
                        aligned=False,
                        direction=trend_1h or trend_4h or "NEUTRAL",
                        confidence=0,
                        reason=f"Trend misaligned: 4H={trend_4h}, 1H={trend_1h}",
                        details={
                            "trend_4h": trend_4h,
                            "trend_1h": trend_1h,
                            "required": "BULLISH"
                        }
                    )
            
            else:  # SELL or SHORT
                # For SELL: need bearish trend
                aligned_4h = trend_4h == "BEARISH" if indicators_4h else True
                aligned_1h = trend_1h == "BEARISH" if indicators_1h else True
                
                if aligned_4h and aligned_1h:
                    confidence = self._calculate_trend_confidence(
                        indicators_4h, indicators_1h, current_price, "BEARISH"
                    )
                    return TrendResult(
                        aligned=True,
                        direction="SHORT",
                        confidence=confidence,
                        reason=f"Trend aligned bearish ({'4H+1H' if indicators_4h and indicators_1h else '1H' if indicators_1h else '4H'})",
                        details={
                            "price": current_price,
                            "trend_4h": trend_4h,
                            "trend_1h": trend_1h,
                            "ema20_1h": indicators_1h.ema20 if indicators_1h else None,
                            "rsi_1h": indicators_1h.rsi14 if indicators_1h else None,
                        }
                    )
                else:
                    return TrendResult(
                        aligned=False,
                        direction=trend_1h or trend_4h or "NEUTRAL",
                        confidence=0,
                        reason=f"Trend misaligned: 4H={trend_4h}, 1H={trend_1h}",
                        details={
                            "trend_4h": trend_4h,
                            "trend_1h": trend_1h,
                            "required": "BEARISH"
                        }
                    )
                    
        except Exception as e:
            print(f"❌ TURBO: Error checking trend for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return TrendResult(
                aligned=False,
                direction="NEUTRAL",
                confidence=0,
                reason=f"Error checking trend: {str(e)}",
                details={"error": str(e)}
            )
    
    def _get_seconds_until_market_close(self) -> int:
        """Calculate seconds until 2:30 PM market close for intraday."""
        now = ist_naive()
        market_close = now.replace(hour=14, minute=30, second=0, microsecond=0)
        
        # If already past 2:30 PM, return 0
        if now >= market_close:
            return 0
        
        return int((market_close - now).total_seconds())
    
    async def monitor_entry(
        self, 
        symbol: str, 
        direction: str, 
        max_duration: int = None,
        check_interval: int = 3,
        monitor_until_market_close: bool = True
    ) -> EntryResult:
        """
        CONTINUOUSLY monitor 1-minute chart for optimal entry.
        
        Args:
            symbol: Stock symbol
            direction: 'BUY' or 'SELL'
            max_duration: Max seconds to monitor (default: until 2:30 PM market close)
            check_interval: Seconds between checks (default 3 sec for faster response)
            monitor_until_market_close: If True, monitor until 2:30 PM instead of fixed duration
            
        Returns:
            EntryResult with trigger status
            
        NOTE: This keeps checking EVERY check_interval seconds until:
            1. Entry conditions are met (returns triggered=True)
            2. 2:30 PM market close (or max_duration if specified) is reached
            3. Market closes (returns triggered=False)
        """
        start_time = ist_naive()
        direction = direction.upper()
        
        # Calculate max duration - either until 2:30 PM or fixed duration
        if monitor_until_market_close and max_duration is None:
            max_duration = self._get_seconds_until_market_close()
            end_time_str = "14:30 (market close)"
        elif max_duration is None:
            max_duration = 300  # Default 5 minutes
            end_time_str = f"{max_duration}s"
        else:
            end_time_str = f"{max_duration}s"
        
        # Config thresholds
        rsi_overbought = self.indicators_config.get("rsi_overbought", 65)
        rsi_oversold = self.indicators_config.get("rsi_oversold", 35)
        volume_threshold = self.indicators_config.get("volume_threshold", 1.2)
        
        print(f"🎯 TURBO: CONTINUOUSLY monitoring {symbol} {direction} entry")
        print(f"   Monitoring until: {end_time_str} | Check interval: {check_interval}s")
        
        # Track best conditions seen (for reporting)
        best_score = 0
        best_conditions = ""
        checks_count = 0
        
        while True:
            elapsed = (ist_naive() - start_time).total_seconds()
            
            # Check max duration (time until 2:30 PM or specified limit)
            if elapsed >= max_duration:
                if monitor_until_market_close:
                    print(f"⏰ TURBO: Market close (2:30 PM) reached for {symbol}")
                else:
                    print(f"⏰ TURBO: Max duration ({max_duration}s) reached for {symbol}")
                print(f"   Best conditions seen: {best_conditions} (score: {best_score})")
                return EntryResult(
                    triggered=False,
                    entry_price=None,
                    trigger_reason=f"{'Market close reached' if monitor_until_market_close else 'Max duration reached'}. Best: {best_conditions}",
                    confidence_score=0,
                    indicators_at_entry={},
                    duration_seconds=elapsed
                )
            
            # Check market hours
            if not self.is_market_open():
                print(f"🔒 TURBO: Market closed, stopping monitor for {symbol}")
                return EntryResult(
                    triggered=False,
                    entry_price=None,
                    trigger_reason="Market closed",
                    confidence_score=0,
                    indicators_at_entry={},
                    duration_seconds=elapsed
                )
            
            try:
                # Fetch recent 1M candles
                candles_1m = await self._fetch_candles(symbol, "1minute", 50)
                checks_count += 1
                
                if not candles_1m or len(candles_1m) < 30:
                    print(f"⚠️ TURBO: Insufficient 1M data ({len(candles_1m) if candles_1m else 0} candles), waiting...")
                    await asyncio.sleep(check_interval)
                    continue
                
                # Calculate indicators
                ind = self._calculate_indicators(candles_1m)
                current_price = candles_1m[-1]["close"]
                
                # Check entry conditions
                if direction in ["BUY", "LONG"]:
                    entry_triggered, reason, score = self._check_buy_entry(
                        current_price, ind, candles_1m,
                        rsi_overbought, volume_threshold
                    )
                else:
                    entry_triggered, reason, score = self._check_sell_entry(
                        current_price, ind, candles_1m,
                        rsi_oversold, volume_threshold
                    )
                
                # Track best conditions
                if score > best_score:
                    best_score = score
                    best_conditions = reason
                
                # Log progress every 30 seconds
                if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                    print(f"⏱️  TURBO: {symbol} monitoring... {elapsed:.0f}s elapsed, current score: {score}/4")
                
                # Check if entry triggered
                if entry_triggered:
                    duration = (ist_naive() - start_time).total_seconds()
                    confidence = self._calculate_entry_confidence(ind, direction)
                    
                    print(f"✅ TURBO: ENTRY TRIGGERED for {symbol}!")
                    print(f"   Price: ₹{current_price:.2f} | Reason: {reason}")
                    print(f"   Time waited: {duration:.1f}s | Confidence: {confidence:.0f}%")
                    
                    return EntryResult(
                        triggered=True,
                        entry_price=current_price,
                        trigger_reason=reason,
                        confidence_score=confidence,
                        indicators_at_entry=asdict(ind),
                        duration_seconds=duration
                    )
                
                # Wait before next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                print(f"⚠️ TURBO: Error monitoring {symbol}: {e}")
                await asyncio.sleep(check_interval)
        
        # Should never reach here
        return EntryResult(
            triggered=False,
            entry_price=None,
            trigger_reason="Monitor loop exited unexpectedly",
            confidence_score=0,
            indicators_at_entry={},
            duration_seconds=(ist_naive() - start_time).total_seconds()
        )
    
    def _check_buy_entry(
        self, 
        price: float, 
        ind: IndicatorSet, 
        candles: List[dict],
        rsi_limit: float,
        volume_threshold: float
    ) -> Tuple[bool, str, int]:
        """
        Check if BUY entry conditions are met.
        
        Returns:
            Tuple of (triggered, reason, score)
        """
        reasons = []
        
        # 1. Price near EMA (pullback) - RELAXED thresholds
        near_ema9 = abs(price - ind.ema9) / price < 0.003  # Within 0.3% (was 0.2%)
        near_ema20 = abs(price - ind.ema20) / price < 0.008  # Within 0.8% (was 0.5%)
        above_ema20 = price > ind.ema20  # Price above trend
        
        if near_ema9:
            reasons.append("Near EMA9")
        elif near_ema20:
            reasons.append("Near EMA20")
        elif above_ema20:
            reasons.append("Above EMA20")
        
        # 2. RSI not overbought - RELAXED
        rsi_good = ind.rsi14 < rsi_limit + 5  # Allow slightly higher RSI
        if rsi_good:
            reasons.append(f"RSI {ind.rsi14:.0f}")
        
        # 3. MACD bullish or improving
        macd_bullish = ind.macd_histogram > 0
        macd_improving = ind.macd_histogram > -0.2 and ind.macd_line > ind.macd_signal * 0.95
        if macd_bullish:
            reasons.append("MACD bullish")
        elif macd_improving:
            reasons.append("MACD improving")
        
        # 4. Volume confirmation - RELAXED
        volume_good = ind.volume_ratio > volume_threshold - 0.3
        if volume_good:
            reasons.append(f"Vol {ind.volume_ratio:.1f}x")
        
        # Calculate score (relaxed criteria)
        # Near EMA (any) = 1 point
        ema_score = 1 if (near_ema9 or near_ema20 or above_ema20) else 0
        macd_score = 1 if (macd_bullish or macd_improving) else 0
        rsi_score = 1 if rsi_good else 0
        volume_score = 1 if volume_good else 0
        
        score = ema_score + macd_score + rsi_score + volume_score
        
        # Entry triggered if at least 3 of 4 conditions met (relaxed from 3 to 2.5 effectively)
        # Or 2 conditions including volume
        if score >= 3:
            return True, f"Score {score}/4: {', '.join(reasons)}", score
        elif score >= 2 and volume_good:
            return True, f"Score {score}/4 (vol confirmed): {', '.join(reasons)}", score
        
        return False, f"Score {score}/4", score
    
    def _check_sell_entry(
        self, 
        price: float, 
        ind: IndicatorSet, 
        candles: List[dict],
        rsi_limit: float,
        volume_threshold: float
    ) -> Tuple[bool, str, int]:
        """
        Check if SELL entry conditions are met.
        
        Returns:
            Tuple of (triggered, reason, score)
        """
        reasons = []
        
        # 1. Price near EMA (bounce) - RELAXED
        near_ema9 = abs(price - ind.ema9) / price < 0.003
        near_ema20 = abs(price - ind.ema20) / price < 0.008
        below_ema20 = price < ind.ema20
        
        if near_ema9:
            reasons.append("Near EMA9")
        elif near_ema20:
            reasons.append("Near EMA20")
        elif below_ema20:
            reasons.append("Below EMA20")
        
        # 2. RSI not oversold - RELAXED
        rsi_good = ind.rsi14 > rsi_limit - 5
        if rsi_good:
            reasons.append(f"RSI {ind.rsi14:.0f}")
        
        # 3. MACD bearish or weakening
        macd_bearish = ind.macd_histogram < 0
        macd_weakening = ind.macd_histogram < 0.2 and ind.macd_line < ind.macd_signal * 1.05
        if macd_bearish:
            reasons.append("MACD bearish")
        elif macd_weakening:
            reasons.append("MACD weakening")
        
        # 4. Volume confirmation - RELAXED
        volume_good = ind.volume_ratio > volume_threshold - 0.3
        if volume_good:
            reasons.append(f"Vol {ind.volume_ratio:.1f}x")
        
        # Calculate score
        ema_score = 1 if (near_ema9 or near_ema20 or below_ema20) else 0
        macd_score = 1 if (macd_bearish or macd_weakening) else 0
        rsi_score = 1 if rsi_good else 0
        volume_score = 1 if volume_good else 0
        
        score = ema_score + macd_score + rsi_score + volume_score
        
        if score >= 3:
            return True, f"Score {score}/4: {', '.join(reasons)}", score
        elif score >= 2 and volume_good:
            return True, f"Score {score}/4 (vol confirmed): {', '.join(reasons)}", score
        
        return False, f"Score {score}/4", score
    
    async def _fetch_candles(self, symbol: str, interval: str, count: int) -> List[dict]:
        """
        Fetch candles from Kite API with caching.
        
        Args:
            symbol: Stock symbol
            interval: Kite interval (minute, 5minute, 15minute, 30minute, 60minute, day)
            count: Number of candles to fetch
        """
        cache_key = f"{symbol}_{interval}"
        now = ist_naive()
        
        # Check cache
        if cache_key in self._candle_cache:
            cached = self._candle_cache[cache_key]
            if (now - cached["timestamp"]).total_seconds() < self._cache_ttl:
                return cached["data"]
        
        # Map turbo intervals to Kite intervals
        kite_interval = {
            "1minute": "minute",
            "minute": "minute",
            "5minute": "5minute",
            "15minute": "15minute",
            "30minute": "30minute",
            "60minute": "60minute",
            "1hour": "60minute",
            "4hour": "4hour",  # May not be supported, will fall back
            "day": "day"
        }.get(interval, interval)
        
        # Try to fetch from API
        kite = self._get_kite()
        
        try:
            candles = await kite.get_historical_data(
                symbol=symbol,
                interval=kite_interval,
                duration=count
            )
            
            if candles:
                self._candle_cache[cache_key] = {
                    "timestamp": now,
                    "data": candles
                }
            
            return candles
            
        except Exception as e:
            print(f"⚠️ TURBO: Error fetching candles for {symbol} {interval}: {e}")
            return []
    
    def _calculate_indicators(self, candles: List[dict]) -> IndicatorSet:
        """Calculate technical indicators from candle data"""
        closes = [c["close"] for c in candles]
        volumes = [c.get("volume", 0) for c in candles]
        
        # EMAs
        ema9 = self._calculate_ema(closes, 9)
        ema20 = self._calculate_ema(closes, 20)
        ema50 = self._calculate_ema(closes, 50) if len(closes) >= 50 else None
        
        # RSI
        rsi14 = self._calculate_rsi(closes, 14)
        
        # MACD
        macd_line, macd_signal, macd_histogram = self._calculate_macd(closes)
        
        # Volume
        volume_sma20 = statistics.mean(volumes[-20:]) if len(volumes) >= 20 else statistics.mean(volumes)
        current_volume = volumes[-1] if volumes else 0
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 1.0
        
        return IndicatorSet(
            ema9=ema9,
            ema20=ema20,
            ema50=ema50,
            rsi14=rsi14,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            volume_sma20=volume_sma20,
            current_volume=current_volume,
            volume_ratio=volume_ratio
        )
    
    def _calculate_ema(self, data: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(data) < period:
            return data[-1] if data else 0.0
        
        multiplier = 2.0 / (period + 1)
        ema = statistics.mean(data[:period])  # Start with SMA
        
        for price in data[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_rsi(self, data: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(data) < period + 1:
            return 50.0  # Neutral
        
        gains = []
        losses = []
        
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = statistics.mean(gains[-period:])
        avg_loss = statistics.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, data: List[float]) -> Tuple[float, float, float]:
        """Calculate MACD indicator"""
        ema12 = self._calculate_ema(data, 12)
        ema26 = self._calculate_ema(data, 26)
        
        macd_line = ema12 - ema26
        
        # For signal line, we need historical MACD values
        # Simplified: use current MACD as proxy
        macd_signal = macd_line * 0.9  # Approximation
        macd_histogram = macd_line - macd_signal
        
        return macd_line, macd_signal, macd_histogram
    
    def _calculate_trend_confidence(
        self, 
        ind_4h: Optional[IndicatorSet], 
        ind_1h: Optional[IndicatorSet], 
        price: float,
        direction: str
    ) -> float:
        """Calculate confidence score for trend alignment"""
        score = 50.0  # Base score
        
        if direction == "BULLISH":
            # 1H trend strength
            if ind_1h:
                dist_1h = (price - ind_1h.ema20) / ind_1h.ema20 * 100
                score += min(dist_1h * 3, 15)  # Max 15 points
                
                if ind_1h.macd_histogram > 0:
                    score += 10
                
                if 40 <= ind_1h.rsi14 <= 60:
                    score += 10
            
            # 4H trend strength (if available)
            if ind_4h:
                dist_4h = (price - ind_4h.ema20) / ind_4h.ema20 * 100
                score += min(dist_4h * 2, 10)
                
                if ind_4h.macd_histogram > 0:
                    score += 5
        
        else:  # BEARISH
            if ind_1h:
                dist_1h = (ind_1h.ema20 - price) / ind_1h.ema20 * 100
                score += min(dist_1h * 3, 15)
                
                if ind_1h.macd_histogram < 0:
                    score += 10
                
                if 40 <= ind_1h.rsi14 <= 60:
                    score += 10
            
            if ind_4h:
                dist_4h = (ind_4h.ema20 - price) / ind_4h.ema20 * 100
                score += min(dist_4h * 2, 10)
                
                if ind_4h.macd_histogram < 0:
                    score += 5
        
        return min(score, 100.0)
    
    def _calculate_entry_confidence(self, ind: IndicatorSet, direction: str) -> float:
        """Calculate confidence score for entry timing"""
        score = 50.0
        
        # Volume score
        if ind.volume_ratio > 2.0:
            score += 20
        elif ind.volume_ratio > 1.5:
            score += 15
        elif ind.volume_ratio > 1.0:
            score += 5
        
        # MACD score
        if abs(ind.macd_histogram) > 0.5:
            score += 15
        elif abs(ind.macd_histogram) > 0.2:
            score += 10
        
        # RSI score
        if direction in ["BUY", "LONG"]:
            if 30 <= ind.rsi14 <= 50:
                score += 15
            elif ind.rsi14 < 65:
                score += 5
        else:
            if 50 <= ind.rsi14 <= 70:
                score += 15
            elif ind.rsi14 > 35:
                score += 5
        
        # EMA alignment score
        if ind.ema9 > ind.ema20 and direction in ["BUY", "LONG"]:
            score += 10
        elif ind.ema9 < ind.ema20 and direction not in ["BUY", "LONG"]:
            score += 10
        
        return min(score, 100.0)


# Simple test
if __name__ == "__main__":
    # Test indicator calculations
    test_candles = [
        {"close": 100, "volume": 1000},
        {"close": 102, "volume": 1200},
        {"close": 101, "volume": 1100},
        {"close": 103, "volume": 1300},
        {"close": 104, "volume": 1400},
        {"close": 103, "volume": 1200},
        {"close": 105, "volume": 1500},
        {"close": 106, "volume": 1600},
        {"close": 105, "volume": 1400},
        {"close": 107, "volume": 1700},
    ] * 5  # 50 candles
    
    analyzer = TurboAnalyzer({})
    ind = analyzer._calculate_indicators(test_candles)
    
    print("Indicator Test Results:")
    print(f"  EMA9: {ind.ema9:.2f}")
    print(f"  EMA20: {ind.ema20:.2f}")
    print(f"  RSI14: {ind.rsi14:.2f}")
    print(f"  MACD: {ind.macd_line:.2f}")
    print(f"  Volume Ratio: {ind.volume_ratio:.2f}x")
    
    # Test entry check
    triggered, reason, score = analyzer._check_buy_entry(
        107, ind, test_candles, 60, 1.5
    )
    print(f"\nEntry Check: triggered={triggered}, score={score}, reason={reason}")
