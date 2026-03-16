"""
Zerodha Brokerage & Tax Calculator
===================================

Calculates all trading costs for accurate P&L reporting.

Fee Structure (as of March 2026):
- Brokerage: 0.03% or ₹20 per order (whichever is lower)
- STT: 0.025% on sell side only
- Transaction Charges: 0.00297% on both sides
- SEBI Charges: ₹10 per crore (0.0001%)
- Stamp Duty: 0.003% on buy side only
- GST: 18% on (brokerage + SEBI + transaction charges)

Additional Charges:
- Auto square-off: ₹50 + GST (if not closed by 3:20 PM)
- Call & trade: ₹50 + GST

Example for ₹1,00,000 turnover (buy + sell):
- Brokerage: ₹20 + ₹20 = ₹40
- STT: ₹25 (sell side only)
- Transaction: ₹2.97 + ₹2.97 = ₹5.94
- SEBI: ₹0.10 + ₹0.10 = ₹0.20
- Stamp Duty: ₹3.00 (buy side)
- GST: 18% of (40 + 0.20 + 5.94) = ₹8.30
- Total: ~₹82.44 (0.082% of turnover)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TradingCosts:
    """Complete breakdown of trading costs"""
    # Brokerage
    brokerage_buy: float
    brokerage_sell: float
    brokerage_total: float
    
    # Statutory charges
    stt: float  # Sell side only
    transaction_charges: float
    sebi_charges: float
    stamp_duty: float  # Buy side only
    
    # Tax
    gst: float
    
    # Totals
    total_before_gst: float
    total_costs: float
    
    # Metadata
    turnover_buy: float
    turnover_sell: float
    total_turnover: float
    cost_percentage: float


# Rate constants (as of March 2026)
BROKERAGE_RATE = 0.0003  # 0.03%
BROKERAGE_MAX = 20.0  # ₹20 per order cap
STT_RATE = 0.00025  # 0.025% on sell
TRANSACTION_RATE = 0.0000297  # 0.00297%
SEBI_RATE = 0.000001  # ₹10 per crore = 0.0001%
STAMP_DUTY_RATE = 0.00003  # 0.003% on buy
GST_RATE = 0.18  # 18%

# Additional charges
AUTO_SQUARE_OFF_CHARGE = 50.0
CALL_TRADE_CHARGE = 50.0


def calculate_brokerage(turnover: float) -> float:
    """
    Calculate brokerage (lower of 0.03% or ₹20)
    
    Args:
        turnover: Trade value (price × quantity)
        
    Returns:
        Brokerage amount (max ₹20)
    """
    calculated = turnover * BROKERAGE_RATE
    return min(calculated, BROKERAGE_MAX)


def calculate_trading_costs(
    buy_value: float,
    sell_value: float,
    auto_square_off: bool = False,
    call_trade: bool = False
) -> TradingCosts:
    """
    Calculate complete trading costs for a round trip (buy + sell)
    
    Args:
        buy_value: Buy turnover (entry_price × quantity)
        sell_value: Sell turnover (exit_price × quantity)
        auto_square_off: Whether auto square-off was applied
        call_trade: Whether order was placed via call & trade
        
    Returns:
        TradingCosts breakdown
    """
    # Brokerage (₹20 cap per order)
    brokerage_buy = calculate_brokerage(buy_value)
    brokerage_sell = calculate_brokerage(sell_value)
    brokerage_total = brokerage_buy + brokerage_sell
    
    # STT - sell side only
    stt = sell_value * STT_RATE
    
    # Transaction charges - both sides
    transaction_buy = buy_value * TRANSACTION_RATE
    transaction_sell = sell_value * TRANSACTION_RATE
    transaction_charges = transaction_buy + transaction_sell
    
    # SEBI charges - both sides
    sebi_buy = buy_value * SEBI_RATE
    sebi_sell = sell_value * SEBI_RATE
    sebi_charges = sebi_buy + sebi_sell
    
    # Stamp duty - buy side only
    stamp_duty = buy_value * STAMP_DUTY_RATE
    
    # Additional charges
    additional = 0.0
    if auto_square_off:
        additional += AUTO_SQUARE_OFF_CHARGE
    if call_trade:
        additional += CALL_TRADE_CHARGE
    
    # Total before GST
    total_before_gst = (
        brokerage_total +
        stt +
        transaction_charges +
        sebi_charges +
        stamp_duty +
        additional
    )
    
    # GST on brokerage + SEBI + transaction + additional
    gst_base = brokerage_total + sebi_charges + transaction_charges + additional
    gst = gst_base * GST_RATE
    
    # Total costs
    total_costs = total_before_gst + gst
    
    # Turnover
    total_turnover = buy_value + sell_value
    cost_percentage = (total_costs / total_turnover * 100) if total_turnover > 0 else 0
    
    return TradingCosts(
        brokerage_buy=round(brokerage_buy, 2),
        brokerage_sell=round(brokerage_sell, 2),
        brokerage_total=round(brokerage_total, 2),
        stt=round(stt, 2),
        transaction_charges=round(transaction_charges, 2),
        sebi_charges=round(sebi_charges, 2),
        stamp_duty=round(stamp_duty, 2),
        gst=round(gst, 2),
        total_before_gst=round(total_before_gst, 2),
        total_costs=round(total_costs, 2),
        turnover_buy=round(buy_value, 2),
        turnover_sell=round(sell_value, 2),
        total_turnover=round(total_turnover, 2),
        cost_percentage=round(cost_percentage, 4)
    )


def calculate_net_pnl(
    entry_price: float,
    exit_price: float,
    quantity: int,
    auto_square_off: bool = False
) -> dict:
    """
    Calculate net P&L after all costs
    
    Args:
        entry_price: Entry price per share
        exit_price: Exit price per share
        quantity: Number of shares
        auto_square_off: Whether auto square-off was applied
        
    Returns:
        Dict with gross_pnl, total_costs, net_pnl, etc.
    """
    buy_value = entry_price * quantity
    sell_value = exit_price * quantity
    
    # Gross P&L (before costs)
    gross_pnl = sell_value - buy_value
    
    # Calculate all costs
    costs = calculate_trading_costs(buy_value, sell_value, auto_square_off)
    
    # Net P&L (after costs)
    net_pnl = gross_pnl - costs.total_costs
    
    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "gross_pnl": round(gross_pnl, 2),
        "total_costs": costs.total_costs,
        "net_pnl": round(net_pnl, 2),
        "cost_percentage": costs.cost_percentage,
        "cost_breakdown": {
            "brokerage": costs.brokerage_total,
            "stt": costs.stt,
            "transaction": costs.transaction_charges,
            "sebi": costs.sebi_charges,
            "stamp_duty": costs.stamp_duty,
            "gst": costs.gst
        }
    }


def get_minimum_profitable_trade(
    entry_price: float,
    quantity: int,
    target_profit_percent: float = 0.1
) -> dict:
    """
    Calculate minimum exit price needed for profitable trade after costs
    
    Args:
        entry_price: Entry price per share
        quantity: Number of shares
        target_profit_percent: Minimum desired profit % (default 0.1%)
        
    Returns:
        Dict with minimum exit price, required move, etc.
    """
    buy_value = entry_price * quantity
    
    # Estimate sell value (assume same as buy for cost calculation)
    estimated_sell_value = buy_value
    
    # Get approximate costs
    costs = calculate_trading_costs(buy_value, estimated_sell_value)
    
    # Minimum gross profit needed to cover costs + target profit
    min_gross_profit = costs.total_costs + (buy_value * target_profit_percent / 100)
    
    # Minimum exit price
    min_exit_price = entry_price + (min_gross_profit / quantity)
    
    # Required price move percentage
    required_move_pct = ((min_exit_price - entry_price) / entry_price) * 100
    
    # Points needed
    points_needed = min_exit_price - entry_price
    
    return {
        "entry_price": entry_price,
        "quantity": quantity,
        "min_exit_price": round(min_exit_price, 2),
        "points_needed": round(points_needed, 2),
        "required_move_percent": round(required_move_pct, 3),
        "total_costs": costs.total_costs,
        "break_even_price": round(entry_price + (costs.total_costs / quantity), 2)
    }


def format_cost_summary(costs: TradingCosts) -> str:
    """Format costs as readable summary"""
    return f"""
Trade Cost Breakdown:
====================
Turnover: ₹{costs.total_turnover:,.2f} (Buy: ₹{costs.turnover_buy:,.2f}, Sell: ₹{costs.turnover_sell:,.2f})

Brokerage:
  Buy:  ₹{costs.brokerage_buy:,.2f}
  Sell: ₹{costs.brokerage_sell:,.2f}
  Total: ₹{costs.brokerage_total:,.2f}

Statutory Charges:
  STT:          ₹{costs.stt:,.2f}
  Transaction:  ₹{costs.transaction_charges:,.2f}
  SEBI:         ₹{costs.sebi_charges:,.2f}
  Stamp Duty:   ₹{costs.stamp_duty:,.2f}

Tax:
  GST (18%):    ₹{costs.gst:,.2f}

Total Costs:    ₹{costs.total_costs:,.2f} ({costs.cost_percentage:.3f}% of turnover)
"""


# Simple test
if __name__ == "__main__":
    print("=" * 60)
    print("Zerodha Brokerage Calculator Test")
    print("=" * 60)
    
    # Test 1: ₹1,00,000 turnover
    print("\nTest 1: ₹1,00,000 turnover (Buy ₹50k, Sell ₹50k)")
    costs = calculate_trading_costs(50000, 50000)
    print(format_cost_summary(costs))
    
    # Test 2: ₹10,00,000 turnover (large trade)
    print("\nTest 2: ₹10,00,000 turnover (Buy ₹5L, Sell ₹5L)")
    costs = calculate_trading_costs(500000, 500000)
    print(format_cost_summary(costs))
    
    # Test 3: Net P&L calculation
    print("\nTest 3: Net P&L for 100 shares @ ₹1000 entry, ₹1010 exit")
    pnl = calculate_net_pnl(1000, 1010, 100)
    print(f"  Gross P&L: ₹{pnl['gross_pnl']:,.2f}")
    print(f"  Costs: ₹{pnl['total_costs']:,.2f}")
    print(f"  Net P&L: ₹{pnl['net_pnl']:,.2f}")
    print(f"  Cost %: {pnl['cost_percentage']:.3f}%")
    
    # Test 4: Minimum profitable exit
    print("\nTest 4: Minimum profitable exit for ₹1000 entry, 100 shares")
    min_trade = get_minimum_profitable_trade(1000, 100, target_profit_percent=0.1)
    print(f"  Break-even exit: ₹{min_trade['break_even_price']:,.2f}")
    print(f"  Min profitable exit (0.1%): ₹{min_trade['min_exit_price']:,.2f}")
    print(f"  Points needed above break-even: {min_trade['points_needed']:,.2f}")
    print(f"  Required move: {min_trade['required_move_percent']:.3f}%")
