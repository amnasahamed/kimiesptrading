"""
Margin/Leverage Data Module
===========================
Loads and provides margin data from Zerodha CSV for intelligent position sizing.

CSV Columns:
- ISIN: International Securities Identification Number
- Symbol: Trading symbol
- Var+ ELM+Adhoc margin: Exchange margin requirement (%)
- MIS Margin(%): Margin required for MIS (Intraday) - typically 20%
- MIS Multiplier: Leverage multiplier - typically 5x (20% = 1/5)
- CO Margin(%): Cover Order margin requirement
- CO Upper Trigger: CO trigger percentage
- CO Multiplier: Cover Order leverage multiplier

Usage:
    from margins import get_margin_data, calculate_margin_required
    
    # Get margin info for a stock
    margin = get_margin_data("RELIANCE")
    print(f"Leverage: {margin['mis_multiplier']}x")
    
    # Calculate margin required for a trade
    margin_needed = calculate_margin_required("WABAG", quantity=10, price=1286)
    print(f"Margin required: ₹{margin_needed:,.2f}")
"""
import csv
import json
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

# Default CSV path
DEFAULT_CSV_PATH = Path("uploads/Zerodha - Intraday margins - EQ- MIS_CO leverages.csv")
CACHE_FILE = Path("uploads/margins_cache.json")

# In-memory cache
_margin_cache: Dict[str, dict] = {}
_cache_loaded = False


def load_margin_data(csv_path: Path = DEFAULT_CSV_PATH) -> Dict[str, dict]:
    """
    Load margin data from CSV file.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        Dictionary mapping symbol -> margin data
    """
    global _margin_cache, _cache_loaded
    
    if _cache_loaded:
        return _margin_cache
    
    # Try to load from JSON cache first (faster)
    if CACHE_FILE.exists():
        try:
            cache_mtime = CACHE_FILE.stat().st_mtime
            csv_mtime = csv_path.stat().st_mtime if csv_path.exists() else 0
            
            # Use cache only if it's newer than CSV
            if cache_mtime >= csv_mtime:
                with open(CACHE_FILE, 'r') as f:
                    _margin_cache = json.load(f)
                    _cache_loaded = True
                    print(f"Loaded margin data from cache: {len(_margin_cache)} stocks")
                    return _margin_cache
        except Exception as e:
            print(f"Cache load failed: {e}")
    
    # Load from CSV
    if not csv_path.exists():
        print(f"Warning: Margin CSV not found at {csv_path}")
        return {}
    
    symbols = {}
    
    try:
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
            
            # Skip header rows (rows 0, 1, 2), process from row 3
            data_rows = rows[3:]
            
            for row in data_rows:
                if len(row) >= 9:
                    symbol = row[1].strip().upper()
                    
                    if symbol and symbol != 'SYMBOL' and not symbol.startswith('NOT LISTED'):
                        # Parse numeric values, handling #N/A
                        def parse_float(val, default=0.0):
                            if val and val not in ['#N/A', '']:
                                try:
                                    return float(val)
                                except:
                                    return default
                            return default
                        
                        def parse_int(val, default=0):
                            if val and val not in ['#N/A', '']:
                                try:
                                    return int(float(val))
                                except:
                                    return default
                            return default
                        
                        symbols[symbol] = {
                            'isin': row[0],
                            'bse_symbol': row[2] if len(row) > 2 else '',
                            'var_margin': parse_float(row[3]),  # Exchange margin %
                            'mis_margin_pct': parse_float(row[4]),  # MIS margin %
                            'mis_multiplier': parse_int(row[5], 1),  # Leverage (5x = 5)
                            'co_margin_pct': parse_float(row[6]),  # CO margin %
                            'co_upper_trigger': parse_float(row[7]),  # CO trigger %
                            'co_multiplier': parse_int(row[8], 1),  # CO leverage
                        }
        
        _margin_cache = symbols
        _cache_loaded = True
        
        # Save to JSON cache for faster loading next time
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(symbols, f, indent=2)
        except Exception as e:
            print(f"Cache save failed: {e}")
        
        print(f"Loaded margin data from CSV: {len(symbols)} stocks")
        
        # Print stats
        stats = {'1x': 0, '2x': 0, '5x': 0, 'other': 0}
        for data in symbols.values():
            mult = data['mis_multiplier']
            if mult == 1:
                stats['1x'] += 1
            elif mult == 2:
                stats['2x'] += 1
            elif mult == 5:
                stats['5x'] += 1
            else:
                stats['other'] += 1
        
        print(f"  5x leverage: {stats['5x']} stocks")
        print(f"  2x leverage: {stats['2x']} stocks")
        print(f"  1x leverage: {stats['1x']} stocks")
        if stats['other'] > 0:
            print(f"  Other: {stats['other']} stocks")
        
        return symbols
        
    except Exception as e:
        print(f"Error loading margin data: {e}")
        return {}


def get_margin_data(symbol: str) -> Optional[dict]:
    """
    Get margin data for a specific symbol.
    
    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "WABAG")
        
    Returns:
        Dictionary with margin data or None if not found
    """
    global _cache_loaded
    
    if not _cache_loaded:
        load_margin_data()
    
    return _margin_cache.get(symbol.upper())


def get_leverage_multiplier(symbol: str, default: int = 5) -> int:
    """
    Get the MIS leverage multiplier for a symbol.
    
    Args:
        symbol: Stock symbol
        default: Default multiplier if not found (default: 5 for most stocks)
        
    Returns:
        Leverage multiplier (e.g., 5 for 5x)
    """
    data = get_margin_data(symbol)
    if data and data.get('mis_multiplier', 0) > 0:
        return data['mis_multiplier']
    return default


def get_margin_percentage(symbol: str, default: float = 20.0) -> float:
    """
    Get the MIS margin percentage for a symbol.
    
    Args:
        symbol: Stock symbol
        default: Default margin % if not found (default: 20% for 5x)
        
    Returns:
        Margin percentage (e.g., 20.0 for 20%)
    """
    data = get_margin_data(symbol)
    if data and data.get('mis_margin_pct', 0) > 0:
        return data['mis_margin_pct']
    return default


def calculate_margin_required(symbol: str, quantity: int, price: float) -> float:
    """
    Calculate the margin required for a trade.
    
    Formula: Margin = (Quantity × Price) × (Margin% / 100)
    
    Args:
        symbol: Stock symbol
        quantity: Number of shares
        price: Price per share
        
    Returns:
        Margin required in currency
    """
    if quantity <= 0 or price <= 0:
        return 0.0
    
    trade_value = quantity * price
    margin_pct = get_margin_percentage(symbol)
    
    return trade_value * (margin_pct / 100)


def calculate_max_quantity_with_margin(symbol: str, available_margin: float, price: float) -> int:
    """
    Calculate maximum quantity that can be bought with given margin.
    
    Args:
        symbol: Stock symbol
        available_margin: Available margin amount
        price: Price per share
        
    Returns:
        Maximum quantity that can be purchased
    """
    if available_margin <= 0 or price <= 0:
        return 0
    
    margin_pct = get_margin_percentage(symbol)
    
    # Formula: Available Margin = (Qty × Price) × (Margin% / 100)
    # Therefore: Qty = Available Margin / (Price × Margin% / 100)
    #              Qty = Available Margin × 100 / (Price × Margin%)
    
    max_qty = int((available_margin * 100) / (price * margin_pct))
    return max(0, max_qty)


def get_position_sizing_info(symbol: str, capital: float, price: float, 
                              risk_percent: float = 1.0) -> dict:
    """
    Get comprehensive position sizing information including margin requirements.
    
    Args:
        symbol: Stock symbol
        capital: Total capital available
        price: Current stock price
        risk_percent: Risk percentage per trade
        
    Returns:
        Dictionary with sizing recommendations
    """
    margin_data = get_margin_data(symbol)
    
    if not margin_data:
        # Default to standard 5x
        margin_data = {
            'mis_multiplier': 5,
            'mis_margin_pct': 20.0,
            'var_margin': 20.0
        }
    
    leverage = margin_data['mis_multiplier']
    margin_pct = margin_data['mis_margin_pct']
    
    # Risk-based quantity
    risk_amount = capital * (risk_percent / 100)
    
    # Assuming 1% stop loss for risk calculation
    estimated_sl_distance = price * 0.01
    risk_based_qty = int(risk_amount / estimated_sl_distance) if estimated_sl_distance > 0 else 0
    
    # Margin-based quantity (how many shares can we afford with our capital)
    # With leverage, we can buy more
    effective_capital = capital * leverage
    margin_based_qty = int(effective_capital / price)
    
    # Conservative: take minimum
    recommended_qty = min(risk_based_qty, margin_based_qty)
    
    trade_value = recommended_qty * price
    margin_required = trade_value * (margin_pct / 100)
    
    return {
        'symbol': symbol,
        'price': price,
        'capital': capital,
        'leverage': leverage,
        'margin_percentage': margin_pct,
        'risk_based_quantity': risk_based_qty,
        'margin_based_quantity': margin_based_qty,
        'recommended_quantity': recommended_qty,
        'trade_value': trade_value,
        'margin_required': margin_required,
        'margin_data': margin_data
    }


def list_stocks_by_leverage(multiplier: int = 5) -> list:
    """
    List all stocks with a specific leverage multiplier.
    
    Args:
        multiplier: Leverage multiplier to filter by (1, 2, 5)
        
    Returns:
        List of symbol names
    """
    global _cache_loaded
    
    if not _cache_loaded:
        load_margin_data()
    
    return [
        symbol for symbol, data in _margin_cache.items()
        if data.get('mis_multiplier') == multiplier
    ]


# Load data on module import
if __name__ != "__main__":
    # Auto-load in background
    try:
        load_margin_data()
    except Exception as e:
        print(f"Auto-load margin data failed: {e}")


if __name__ == "__main__":
    # Test the module
    print("=" * 60)
    print("Margin Data Module Test")
    print("=" * 60)
    
    # Load data
    data = load_margin_data()
    print(f"\nLoaded {len(data)} stocks")
    
    # Test specific stocks
    test_symbols = ['WABAG', 'RELIANCE', 'TCS', 'INFY', 'SBIN']
    
    print("\n" + "=" * 60)
    print("Stock Margin Data")
    print("=" * 60)
    
    for symbol in test_symbols:
        margin = get_margin_data(symbol)
        if margin:
            print(f"\n{symbol}:")
            print(f"  MIS Multiplier: {margin['mis_multiplier']}x")
            print(f"  MIS Margin: {margin['mis_margin_pct']}%")
            print(f"  Exchange Margin (VaR+ELM): {margin['var_margin']}%")
            
            # Calculate for 1 share at current price
            price = 1000  # hypothetical
            margin_req = calculate_margin_required(symbol, 1, price)
            print(f"  Margin for 1 share @ ₹{price}: ₹{margin_req:.2f}")
    
    # Test position sizing
    print("\n" + "=" * 60)
    print("Position Sizing Example (WABAG)")
    print("=" * 60)
    
    info = get_position_sizing_info('WABAG', capital=5000, price=1286)
    print(f"Capital: ₹{info['capital']:,.2f}")
    print(f"Price: ₹{info['price']:,.2f}")
    print(f"Leverage: {info['leverage']}x")
    print(f"Margin %: {info['margin_percentage']}%")
    print(f"Recommended Qty: {info['recommended_quantity']} shares")
    print(f"Trade Value: ₹{info['trade_value']:,.2f}")
    print(f"Margin Required: ₹{info['margin_required']:,.2f}")
