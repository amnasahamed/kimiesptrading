"""
Calculator service — thin wrapper around root-level calculator.py.
"""
import sys
import os
from pathlib import Path

# Ensure project root is on path so we can import root-level modules
_ROOT = str(Path(__file__).parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from calculator import (  # noqa: E402
    calculate_atr,
    calculate_trade_params,
    calculate_intelligent_position,
    TradeParams,
)


def get_atr(ohlcv_data: list, period: int = 14) -> float:
    """Calculate Average True Range."""
    return calculate_atr(ohlcv_data, period)


def get_trade_params(
    entry_price: float,
    atr: float,
    capital: float,
    risk_percent: float,
    direction: str = "LONG",
    atr_sl_multiplier: float = 1.5,
    atr_tp_multiplier: float = 3.0,
    budget: float = 0,
) -> TradeParams:
    """Calculate SL, TP, and position size."""
    return calculate_trade_params(
        entry_price=entry_price,
        atr=atr,
        capital=capital,
        risk_percent=risk_percent,
        direction=direction,
        atr_sl_multiplier=atr_sl_multiplier,
        atr_tp_multiplier=atr_tp_multiplier,
        budget=budget,
    )


def get_intelligent_position(
    symbol: str,
    entry_price: float,
    capital: float,
    risk_percent: float,
    budget: float,
    high: float = 0,
    low: float = 0,
    volume: float = 0,
    change_percent: float = 0,
) -> TradeParams:
    """Calculate intelligent position size with market-context adjustments."""
    return calculate_intelligent_position(
        symbol=symbol,
        entry_price=entry_price,
        capital=capital,
        risk_percent=risk_percent,
        budget=budget,
        high=high,
        low=low,
        volume=volume,
        change_percent=change_percent,
    )
