"""
ATR / SL / TP / Quantity Calculator
Pure Python, no dependencies, instant calculation
"""
from dataclasses import dataclass
from typing import List, Optional
import math


@dataclass
class TradeParams:
    entry: float
    stop_loss: float
    target: float
    quantity: int
    risk_amount: float
    risk_reward: float
    direction: str  # 'LONG' or 'SHORT'


def calculate_atr(ohlcv_data: List[dict], period: int = 14) -> float:
    """
    Calculate Average True Range from OHLCV data.
    ohlcv_data: list of dicts with 'high', 'low', 'close' keys
    """
    # Validate input
    if not ohlcv_data or not isinstance(ohlcv_data, list):
        raise ValueError("OHLCV data must be a non-empty list")
    
    # Validate each data point
    for i, d in enumerate(ohlcv_data):
        if not isinstance(d, dict):
            raise ValueError(f"Data point {i} must be a dictionary")
        if not all(k in d for k in ['high', 'low', 'close']):
            raise ValueError(f"Data point {i} missing required keys: high, low, close")
        if d['high'] < 0 or d['low'] < 0 or d['close'] < 0:
            raise ValueError(f"Data point {i} contains negative values")
        if d['high'] < d['low']:
            raise ValueError(f"Data point {i}: high ({d['high']}) must be >= low ({d['low']})")
    
    if len(ohlcv_data) < 2:
        # Single candle: use simple range
        return ohlcv_data[0]['high'] - ohlcv_data[0]['low']
    
    if len(ohlcv_data) < period + 1:
        # Fallback: use simple volatility estimate
        highs = [d['high'] for d in ohlcv_data]
        lows = [d['low'] for d in ohlcv_data]
        ranges = [h - l for h, l in zip(highs, lows) if h >= l and h > 0]
        if not ranges:
            return 0.0
        avg_range = sum(ranges) / len(ranges)
        return max(avg_range, 0.0001)  # Ensure non-zero
    
    true_ranges = []
    for i in range(1, len(ohlcv_data)):
        high = ohlcv_data[i]['high']
        low = ohlcv_data[i]['low']
        prev_close = ohlcv_data[i-1]['close']
        
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        
        true_range = max(tr1, tr2, tr3)
        true_ranges.append(true_range)
    
    # Simple average for ATR
    atr = sum(true_ranges[-period:]) / min(period, len(true_ranges))
    return round(atr, 4)


def calculate_trade_params(
    entry_price: float,
    atr: float,
    capital: float,
    risk_percent: float,
    direction: str,
    atr_sl_multiplier: float = 1.5,
    atr_tp_multiplier: float = 3.0,
    min_rr: float = 2.0,
    max_sl_percent: float = 2.0
) -> Optional[TradeParams]:
    """
    Calculate SL, TP, and Quantity based on ATR and risk parameters.
    Returns None if trade doesn't meet criteria.
    """
    # Validate inputs
    if entry_price <= 0:
        return None
    if atr <= 0:
        return None
    if capital <= 0:
        return None
    if risk_percent <= 0 or risk_percent > 100:
        return None
    if atr_sl_multiplier <= 0 or atr_tp_multiplier <= 0:
        return None
    if min_rr <= 0:
        return None
    if max_sl_percent <= 0:
        return None
    
    if direction.upper() not in ['LONG', 'SHORT', 'BUY', 'SELL']:
        return None
    
    is_long = direction.upper() in ['LONG', 'BUY']
    
    # Calculate SL and TP based on ATR
    sl_distance = atr * atr_sl_multiplier
    tp_distance = atr * atr_tp_multiplier
    
    # Cap SL at max percentage of entry
    max_sl_distance = entry_price * (max_sl_percent / 100)
    if sl_distance > max_sl_distance:
        sl_distance = max_sl_distance
        tp_distance = sl_distance * min_rr  # Maintain minimum R:R
    
    if is_long:
        stop_loss = entry_price - sl_distance
        target = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        target = entry_price - tp_distance
    
    # Ensure minimum risk:reward
    actual_rr = tp_distance / sl_distance if sl_distance > 0 else 0
    if actual_rr < min_rr:
        # Adjust TP to meet minimum R:R
        tp_distance = sl_distance * min_rr
        if is_long:
            target = entry_price + tp_distance
        else:
            target = entry_price - tp_distance
    
    # Calculate quantity based on risk
    risk_amount = capital * (risk_percent / 100)
    risk_per_unit = abs(entry_price - stop_loss)
    
    if risk_per_unit <= 0.001:  # Minimum 0.001 to avoid division issues
        return None
    
    quantity = int(risk_amount / risk_per_unit)
    
    # Adjust for lot size (assuming NSE stocks, lot size = 1)
    # For F&O, you'd need to fetch actual lot sizes
    lot_size = 1
    quantity = max(lot_size, (quantity // lot_size) * lot_size)
    
    # Cap quantity to not exceed available capital
    max_qty = int((capital * 0.95) / entry_price)  # 95% to leave buffer
    quantity = min(quantity, max_qty)
    
    if quantity < 1:
        return None
    
    # Recalculate actual risk
    actual_risk = quantity * risk_per_unit
    final_rr = tp_distance / sl_distance
    
    return TradeParams(
        entry=round(entry_price, 2),
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        quantity=quantity,
        risk_amount=round(actual_risk, 2),
        risk_reward=round(final_rr, 2),
        direction='LONG' if is_long else 'SHORT'
    )


def quick_calculate(
    entry: float,
    atr: float,
    capital: float,
    risk_percent: float = 1.0,
    direction: str = 'LONG'
) -> Optional[TradeParams]:
    """Quick calculation with default risk parameters."""
    return calculate_trade_params(
        entry_price=entry,
        atr=atr,
        capital=capital,
        risk_percent=risk_percent,
        direction=direction
    )


def calculate_intelligent_position(
    current_price: float,
    atr: float,
    capital: float,
    risk_percent: float,
    trade_budget: float,
    direction: str,
    atr_sl_multiplier: float = 1.5,
    atr_tp_multiplier: float = 3.0,
    min_rr: float = 2.0,
    max_sl_percent: float = 2.0,
    lot_size: int = 1
) -> Optional[TradeParams]:
    """
    Calculate position size intelligently based on BOTH budget AND risk constraints.
    
    Logic:
    1. Calculate max quantity from trade_budget (how many shares can we buy with our budget)
    2. Calculate max quantity from risk_percent (how many shares can we risk given SL distance)
    3. Use the MINIMUM of the two (conservative approach - satisfy both constraints)
    4. Place market order immediately at current_price
    
    This ensures we:
    - Don't exceed our trade budget (e.g., ₹50,000 per trade)
    - Don't risk more than our risk_percent allows (e.g., 1% of capital)
    - Get the best possible fill at market price when signal hits
    """
    if current_price <= 0 or atr <= 0 or capital <= 0 or trade_budget <= 0:
        return None
    
    is_long = direction.upper() in ['LONG', 'BUY']
    
    # Calculate SL and TP distances
    sl_distance = atr * atr_sl_multiplier
    tp_distance = atr * atr_tp_multiplier
    
    # Cap SL at max percentage of entry
    max_sl_distance = current_price * (max_sl_percent / 100)
    if sl_distance > max_sl_distance:
        sl_distance = max_sl_distance
        tp_distance = sl_distance * min_rr
    
    # Ensure minimum risk:reward
    actual_rr = tp_distance / sl_distance if sl_distance > 0 else 0
    if actual_rr < min_rr:
        tp_distance = sl_distance * min_rr
    
    if is_long:
        stop_loss = current_price - sl_distance
        target = current_price + tp_distance
    else:
        stop_loss = current_price + sl_distance
        target = current_price - tp_distance
    
    # 🔥 INTELLIGENT POSITION SIZING - Two constraints
    
    # 1. Budget-based quantity: How many shares can we buy with trade_budget?
    # Leave 2% buffer for price movement/slippage
    effective_budget = trade_budget * 0.98
    qty_from_budget = int(effective_budget / current_price)
    
    # 2. Risk-based quantity: How many shares can we risk?
    risk_amount = capital * (risk_percent / 100)
    risk_per_share = abs(current_price - stop_loss)
    
    if risk_per_share <= 0.001:
        return None
    
    qty_from_risk = int(risk_amount / risk_per_share)
    
    # Use MINIMUM of both (conservative - satisfy both constraints)
    quantity = min(qty_from_budget, qty_from_risk)
    
    # Adjust for lot size
    quantity = max(lot_size, (quantity // lot_size) * lot_size)
    
    # Ensure at least 1 share
    if quantity < lot_size:
        return None
    
    # Final safety check: total value should not exceed trade_budget
    total_value = quantity * current_price
    if total_value > trade_budget * 1.02:  # 2% tolerance
        # Reduce by one lot
        quantity = max(lot_size, quantity - lot_size)
    
    # Recalculate actual risk
    actual_risk = quantity * risk_per_share
    final_rr = tp_distance / sl_distance
    
    return TradeParams(
        entry=round(current_price, 2),
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        quantity=quantity,
        risk_amount=round(actual_risk, 2),
        risk_reward=round(final_rr, 2),
        direction='LONG' if is_long else 'SHORT'
    )


if __name__ == '__main__':
    # Test
    test_data = [
        {'high': 100, 'low': 95, 'close': 98},
        {'high': 102, 'low': 97, 'close': 101},
        {'high': 105, 'low': 100, 'close': 103},
        {'high': 104, 'low': 99, 'close': 101},
        {'high': 106, 'low': 101, 'close': 105},
        {'high': 108, 'low': 103, 'close': 107},
        {'high': 110, 'low': 105, 'close': 109},
        {'high': 112, 'low': 107, 'close': 111},
        {'high': 115, 'low': 110, 'close': 114},
        {'high': 118, 'low': 113, 'close': 116},
        {'high': 120, 'low': 115, 'close': 118},
        {'high': 122, 'low': 117, 'close': 120},
        {'high': 125, 'low': 120, 'close': 123},
        {'high': 128, 'low': 123, 'close': 126},
        {'high': 130, 'low': 125, 'close': 128},
    ]
    
    atr = calculate_atr(test_data)
    print(f"ATR: {atr}")
    
    params = calculate_trade_params(
        entry_price=128,
        atr=atr,
        capital=100000,
        risk_percent=1,
        direction='LONG'
    )
    print(f"Trade Params: {params}")
