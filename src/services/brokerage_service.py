"""
Brokerage service — thin wrapper around root-level brokerage_calculator.py and margins.py.
"""
import sys
from pathlib import Path
from typing import Optional

_ROOT = str(Path(__file__).parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from brokerage_calculator import (  # noqa: E402
    calculate_trading_costs,
    calculate_net_pnl,
    TradingCosts,
)


def get_trading_costs(
    buy_price: float,
    sell_price: float,
    quantity: int,
    is_intraday: bool = True,
) -> TradingCosts:
    """Calculate all Zerodha trading costs for a round trip."""
    return calculate_trading_costs(
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
        is_intraday=is_intraday,
    )


def get_net_pnl(
    entry_price: float,
    exit_price: float,
    quantity: int,
    is_intraday: bool = True,
) -> dict:
    """Return gross P&L, costs, and net P&L."""
    return calculate_net_pnl(
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        is_intraday=is_intraday,
    )


def get_margin_requirement(
    symbol: str,
    quantity: int,
    price: float,
) -> Optional[float]:
    """
    Look up NRML/MIS margin requirement from the uploaded margins CSV.
    Returns None if margins data is not available.
    """
    try:
        from margins import get_margin  # type: ignore
        return get_margin(symbol=symbol, quantity=quantity, price=price)
    except ImportError:
        return None
    except Exception:
        return None
