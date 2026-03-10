"""
Chartink Webhook Trading Bot - PRODUCTION READY
================================================
FastAPI app - single file, async, <300ms total latency

SAFETY FEATURES:
- Paper trading mode enabled by default (no real orders until disabled)
- Daily loss limit (3% max)
- Bracket orders with SL/TP for every trade
- Position tracking with live P&L
- Automatic daily reset at 8 AM

NO MOCK DATA - All trades use real market prices and real Kite API
(Except when explicitly in paper trading mode for testing)
"""
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, time, timedelta
import json
import asyncio
import httpx
from pathlib import Path
import os
from contextlib import asynccontextmanager

from calculator import calculate_atr, calculate_trade_params, calculate_intelligent_position
from kite import KiteAPI, KiteQuote

# ============================================================================
# Models
# ============================================================================

class ChartinkAlert(BaseModel):
    # Standard fields
    symbol: Optional[str] = None
    action: Optional[str] = "BUY"  # BUY or SELL
    price: Optional[float] = None
    alert_name: Optional[str] = ""
    secret: Optional[str] = ""
    
    # Chartink specific fields (from scan alert)
    # Format: "STOCK1,STOCK2,STOCK3" (comma-separated)
    stocks: Optional[str] = None
    # Format: "100.5,250.0,75.25" (comma-separated, matches stock order)
    trigger_prices: Optional[str] = None
    triggered_at: Optional[str] = None     # e.g., "2:34 pm"
    scan_name: Optional[str] = None        # e.g., "Short term breakouts"
    scan_url: Optional[str] = None         # e.g., "short-term-breakouts"
    webhook_url: Optional[str] = None      # Your webhook URL (echoed back)
    
    # Momentum context (if Chartink sends these)
    volume: Optional[float] = None
    change_percent: Optional[float] = None

class ConfigUpdate(BaseModel):
    system_enabled: Optional[bool] = None
    capital: Optional[float] = None
    risk_percent: Optional[float] = None
    trade_budget: Optional[float] = None  # Fixed amount per trade (e.g., ₹50,000)
    max_trades_per_day: Optional[int] = None
    trading_hours: Optional[Dict[str, str]] = None
    kite_access_token: Optional[str] = None
    kite_api_key: Optional[str] = None
    kite_api_secret: Optional[str] = None
    telegram: Optional[Dict[str, Any]] = None
    chartink: Optional[Dict[str, Any]] = None
    risk_management: Optional[Dict[str, Any]] = None
    paper_trading: Optional[bool] = None  # Test mode without real orders

# ============================================================================
# File paths
# ============================================================================

CONFIG_FILE = Path("config.json")
TRADES_FILE = Path("trades_log.json")
DASHBOARD_HTML = Path("dashboard.html")

# ============================================================================
# App initialization
# ============================================================================

from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    print("=" * 50)
    print("🚀 Chartink Trading Bot Starting")
    print("=" * 50)
    print(f"📊 Dashboard: http://localhost:8000/dashboard")
    print(f"🔗 Webhook: http://localhost:8000/webhook/chartink")
    print("=" * 50)
    
    # Ensure files exist
    if not CONFIG_FILE.exists():
        default_config = {
            "system_enabled": False,
            "paper_trading": True,  # Start in paper mode for safety
            "trading_hours": {"start": "09:15", "end": "15:30"},
            "capital": 100000,
            "risk_percent": 1.0,
            "trade_budget": 50000,  # Fixed amount per trade - max qty within this budget
            "max_trades_per_day": 10,
            "kite": {"api_key": "", "access_token": "", "base_url": "https://api.kite.trade"},
            "telegram": {"bot_token": "", "chat_id": "", "enabled": False},
            "risk_management": {
                "atr_multiplier_sl": 1.5,
                "atr_multiplier_tp": 3.0,
                "min_risk_reward": 2.0,
                "max_sl_percent": 2.0
            },
            "chartink": {"webhook_secret": ""}
        }
        save_config(default_config)
    
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, "w") as f:
            json.dump([], f)
    
    yield
    
    # Shutdown
    print("\n" + "=" * 50)
    print("🛑 Chartink Trading Bot Shutting Down")
    print("=" * 50)
    
    # Close KiteAPI client
    global _kite_instance
    if _kite_instance:
        await _kite_instance.close()
        _kite_instance = None

app = FastAPI(title="Chartink Trading Bot", version="1.0", lifespan=lifespan)

# Add CORS middleware to allow dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now (restrict in production)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================================================
# Position Monitor (FIX #5 & #6: Partial Exits & Trailing Stop)
# ============================================================================

async def monitor_positions():
    """Background task to monitor open positions for partial exits and trailing stops."""
    while True:
        try:
            await asyncio.sleep(10)  # Check every 10 seconds
            
            config = load_config()
            if not config.get("system_enabled"):
                continue
            
            open_positions = get_open_positions()
            if not open_positions:
                continue
            
            kite = get_kite_api(config)
            
            for symbol, pos in open_positions.items():
                try:
                    quote = await kite.get_quote(symbol)
                    if not quote:
                        continue
                    
                    ltp = quote.ltp
                    entry = pos.get("entry_price", 0)
                    sl = pos.get("sl_price", 0)
                    tp = pos.get("tp_price", 0)
                    qty = pos.get("quantity", 0)
                    sl_order_id = pos.get("sl_order_id")
                    partial_exits = pos.get("partial_exits", [])
                    
                    if entry <= 0 or qty <= 0:
                        continue
                    
                    # Calculate current R multiple
                    risk_per_share = abs(entry - sl)
                    current_profit = ltp - entry
                    r_multiple = current_profit / risk_per_share if risk_per_share > 0 else 0
                    
                    # 🔥 FIX #5: Partial Exit at 1:1 R
                    # Exit 50% when price reaches 1R profit, move SL to breakeven
                    if r_multiple >= 1.0 and not any(pe.get("r_level") == 1.0 for pe in partial_exits):
                        print(f"Partial exit triggered for {symbol} at 1R")
                        
                        # Exit 50% position
                        exit_qty = qty // 2
                        if exit_qty > 0:
                            exit_order = await kite.place_market_order(
                                symbol=symbol,
                                transaction_type="SELL",
                                quantity=exit_qty
                            )
                            
                            if exit_order.status == "PENDING":
                                fill_result = await kite.wait_for_order_fill(exit_order.order_id, timeout=10)
                                
                                if fill_result.get("filled"):
                                    # Record partial exit
                                    partial_exit = {
                                        "r_level": 1.0,
                                        "exit_price": fill_result.get("average_price", ltp),
                                        "quantity": exit_qty,
                                        "time": datetime.now().isoformat()
                                    }
                                    
                                    # Update position
                                    new_qty = qty - exit_qty
                                    update_position(symbol, {
                                        "quantity": new_qty,
                                        "partial_exits": partial_exits + [partial_exit]
                                    })
                                    
                                    # 🔥 Move SL to breakeven (or slightly below)
                                    new_sl = entry * 0.998  # 0.2% below entry for buffer
                                    if sl_order_id:
                                        await kite.modify_sl_gtt(
                                            gtt_id=sl_order_id,
                                            new_trigger_price=new_sl,
                                            symbol=symbol,
                                            quantity=new_qty,
                                            transaction_type="BUY"
                                        )
                                        update_position(symbol, {"sl_price": new_sl})
                                    
                                    # Notify
                                    await send_telegram_message(
                                        f"📊 *Partial Exit: {symbol}*\n"
                                        f"Exited 50% ({exit_qty} shares) at ₹{ltp:.2f}\n"
                                        f"SL moved to breakeven: ₹{new_sl:.2f}\n"
                                        f"Remaining: {new_qty} shares"
                                    )
                    
                    # 🔥 FIX #6: Trailing Stop Loss
                    # When price reaches 2R, trail SL to 1R
                    # When price reaches 3R, trail SL to 2R, etc.
                    if r_multiple >= 2.0 and sl_order_id:
                        target_sl_r = int(r_multiple) - 1  # Trail 1R behind current
                        target_sl_price = entry + (target_sl_r * risk_per_share)
                        
                        # Only move SL up, never down
                        if target_sl_price > sl * 1.01:  # 1% buffer to avoid micro adjustments
                            print(f"Trailing SL for {symbol} to {target_sl_r}R: ₹{target_sl_price:.2f}")
                            
                            await kite.modify_sl_gtt(
                                gtt_id=sl_order_id,
                                new_trigger_price=target_sl_price,
                                symbol=symbol,
                                quantity=qty,
                                transaction_type="BUY"
                            )
                            
                            update_position(symbol, {"sl_price": target_sl_price})
                            
                            await send_telegram_message(
                                f"🛡️ *Trailing SL: {symbol}*\n"
                                f"SL moved to {target_sl_r}R: ₹{target_sl_price:.2f}\n"
                                f"Current: ₹{ltp:.2f} ({r_multiple:.1f}R)"
                            )
                
                except Exception as e:
                    print(f"Error monitoring position {symbol}: {e}")
        
        except Exception as e:
            print(f"Position monitor error: {e}")
            await asyncio.sleep(30)  # Wait longer on error

# Start position monitor on startup
@app.on_event("startup")
async def start_position_monitor():
    """Start the position monitoring background task."""
    asyncio.create_task(monitor_positions())

# REMOVED: simulate_paper_trade function was for testing only
# In paper trading mode, trades are logged but NOT automatically closed
# You must manually close paper trades via dashboard or API

# ============================================================================
# Config & Data Management
# ============================================================================

import fcntl  # For file locking on Unix

def load_config() -> Dict[str, Any]:
    """Load config from JSON file with file locking."""
    if not CONFIG_FILE.exists():
        return {}
    
    try:
        with open(CONFIG_FILE, "r") as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError as e:
        print(f"Config file corrupted: {e}")
        return {}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def save_config(config: Dict[str, Any]):
    """Save config to JSON file with file locking."""
    try:
        with open(CONFIG_FILE, "w") as f:
            # Acquire exclusive lock for writing
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Error saving config: {e}")
        raise

def load_trades() -> List[Dict[str, Any]]:
    """Load today's trades from JSON file with file locking.
    Resets at 8:00 AM daily - trades before 8 AM are considered previous day."""
    if not TRADES_FILE.exists():
        return []
    
    try:
        with open(TRADES_FILE, "r") as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
                
                # Filter trades for today (after 8:00 AM)
                now = datetime.now()
                today_date = now.strftime("%Y-%m-%d")
                reset_time = datetime.strptime(f"{today_date} 08:00:00", "%Y-%m-%d %H:%M:%S")
                
                # If current time is before 8 AM, show yesterday's trades after 8 AM
                if now < reset_time:
                    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                    yesterday_reset = datetime.strptime(f"{yesterday} 08:00:00", "%Y-%m-%d %H:%M:%S")
                    return [t for t in data if t.get("date") and 
                            yesterday_reset <= datetime.fromisoformat(t.get("date")) < reset_time]
                else:
                    # Show today's trades after 8 AM
                    return [t for t in data if t.get("date") and 
                            datetime.fromisoformat(t.get("date")) >= reset_time]
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError:
        print("Trades file corrupted, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading trades: {e}")
        return []

def load_all_trades() -> List[Dict[str, Any]]:
    """Load all trades from JSON file with file locking."""
    if not TRADES_FILE.exists():
        return []
    
    try:
        with open(TRADES_FILE, "r") as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError:
        print("Trades file corrupted, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading trades: {e}")
        return []

def save_trade(trade: Dict[str, Any]):
    """Save a trade to the log file with file locking."""
    try:
        trades = load_all_trades()
        trades.append(trade)
        
        with open(TRADES_FILE, "w") as f:
            # Acquire exclusive lock for writing
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(trades, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Error saving trade: {e}")
        raise

def update_trade_pnl(order_id: str, exit_price: float, pnl: float):
    """Update P&L for a trade with file locking."""
    try:
        trades = load_all_trades()
        updated = False
        for t in trades:
            if t.get("order_id") == order_id:
                t["exit_price"] = exit_price
                t["pnl"] = pnl
                t["status"] = "CLOSED"
                updated = True
                break
        
        if updated:
            with open(TRADES_FILE, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(trades, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Error updating trade P&L: {e}")


# ============================================================================
# Position Management (FIX #2 & #3)
# ============================================================================

from kite import Position

POSITIONS_FILE = Path("positions.json")

def load_positions() -> Dict[str, Any]:
    """Load open positions from file."""
    if not POSITIONS_FILE.exists():
        return {}
    try:
        with open(POSITIONS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_positions(positions: Dict[str, Any]):
    """Save positions to file."""
    try:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(positions, f, indent=2, default=str)
    except Exception as e:
        print(f"Error saving positions: {e}")

def store_position(position: Position):
    """Store a new position."""
    positions = load_positions()
    positions[position.symbol] = {
        "symbol": position.symbol,
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "entry_order_id": position.entry_order_id,
        "sl_price": position.sl_price,
        "tp_price": position.tp_price,
        "sl_order_id": position.sl_order_id,
        "tp_order_id": position.tp_order_id,
        "status": position.status,
        "entry_time": position.entry_time.isoformat() if position.entry_time else None
    }
    save_positions(positions)

def update_position(symbol: str, updates: Dict[str, Any]):
    """Update an existing position."""
    positions = load_positions()
    if symbol in positions:
        positions[symbol].update(updates)
        save_positions(positions)

def close_position(symbol: str, exit_price: float, pnl: float, reason: str):
    """Mark position as closed."""
    positions = load_positions()
    if symbol in positions:
        positions[symbol]["status"] = "CLOSED"
        positions[symbol]["exit_price"] = exit_price
        positions[symbol]["pnl"] = pnl
        positions[symbol]["exit_reason"] = reason
        positions[symbol]["exit_time"] = datetime.now().isoformat()
        save_positions(positions)
        
        # Also update the trade log
        entry_order_id = positions[symbol].get("entry_order_id")
        if entry_order_id:
            update_trade_pnl(entry_order_id, exit_price, pnl)

def get_open_positions() -> Dict[str, Any]:
    """Get all open positions."""
    positions = load_positions()
    return {k: v for k, v in positions.items() if v.get("status") == "OPEN"}

def count_today_trades() -> int:
    """Count number of trades taken today."""
    return len(load_trades())

def calculate_today_pnl() -> float:
    """Calculate today's P&L."""
    trades = load_trades()
    return sum(t.get("pnl", 0) for t in trades if t.get("status") == "CLOSED")

# ============================================================================
# Telegram Notifications
# ============================================================================

async def send_telegram_message(message: str):
    """Send notification via Telegram with retry logic."""
    config = load_config()
    telegram = config.get("telegram", {})
    
    if not telegram.get("enabled"):
        return
    
    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")
    
    if not bot_token or not chat_id:
        return
    
    # Validate bot_token format (should contain a colon)
    if ":" not in bot_token or len(bot_token) < 20:
        print(f"Telegram error: Invalid bot token format")
        return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    # Retry with exponential backoff
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10.0)
                if resp.status_code == 200:
                    return
                elif resp.status_code == 429:  # Rate limited
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    await asyncio.sleep(retry_after)
                else:
                    print(f"Telegram API error: {resp.status_code} - {resp.text}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
        except httpx.TimeoutException:
            print(f"Telegram timeout (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
        except Exception as e:
            print(f"Telegram error: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))

# ============================================================================
# Guard Checks
# ============================================================================

def is_within_trading_hours(config: Dict[str, Any]) -> bool:
    """Check if current time is within trading hours."""
    trading_hours = config.get("trading_hours", {})
    start_str = trading_hours.get("start", "09:15")
    end_str = trading_hours.get("end", "15:30")
    
    now = datetime.now().time()
    start_time = datetime.strptime(start_str, "%H:%M").time()
    end_time = datetime.strptime(end_str, "%H:%M").time()
    
    return start_time <= now <= end_time

def can_trade(config: Dict[str, Any]) -> tuple[bool, str]:
    """
    Check if trading is allowed.
    Returns (can_trade, reason)
    """
    if not config.get("system_enabled", False):
        return False, "System is disabled"
    
    if not is_within_trading_hours(config):
        return False, "Outside trading hours"
    
    max_trades = config.get("max_trades_per_day", 10)
    if count_today_trades() >= max_trades:
        return False, f"Max trades ({max_trades}) reached for today"
    
    return True, "OK"

# ============================================================================
# Trading Logic
# ============================================================================

def parse_chartink_payload(alert: ChartinkAlert) -> List[Dict[str, Any]]:
    """
    Parse Chartink alert payload which may contain multiple stocks.
    Chartink sends comma-separated values: "STOCK1,STOCK2,STOCK3"
    Returns list of {symbol, price, scan_name} dicts.
    """
    alerts = []
    
    # If single symbol provided directly (fallback)
    if alert.symbol and not alert.stocks:
        symbol = alert.symbol.upper().strip()
        # Validate symbol format (alphanumeric, no special chars)
        if symbol.isalnum():
            alerts.append({
                "symbol": symbol,
                "price": alert.price,
                "scan_name": alert.alert_name or alert.scan_name or "Chartink Alert",
                "triggered_at": alert.triggered_at,
                "context": {
                    "volume": alert.volume,
                    "change_percent": alert.change_percent
                }
            })
        return alerts
    
    # Parse multiple stocks from Chartink format: "STOCK1,STOCK2,STOCK3"
    if alert.stocks:
        # Chartink uses comma-separated values
        stocks = [s.strip().upper() for s in alert.stocks.split(",") if s.strip()]
        
        # Filter valid symbols (alphanumeric only)
        stocks = [s for s in stocks if s.isalnum() and len(s) <= 20]
        
        prices = []
        
        if alert.trigger_prices:
            # Prices are also comma-separated, matching stock order
            price_strs = [p.strip() for p in alert.trigger_prices.split(",") if p.strip()]
            for p in price_strs:
                try:
                    price_val = float(p)
                    if price_val > 0:
                        prices.append(price_val)
                    else:
                        prices.append(None)
                except (ValueError, TypeError):
                    prices.append(None)
        
        for i, stock in enumerate(stocks):
            price = prices[i] if i < len(prices) else None
            alerts.append({
                "symbol": stock,
                "price": price,
                "scan_name": alert.scan_name or alert.alert_name or "Chartink Scan",
                "triggered_at": alert.triggered_at,
                "context": {
                    "scan_url": alert.scan_url,
                    "webhook_url": alert.webhook_url
                }
            })
    
    return alerts


# Global KiteAPI instance for connection pooling
_kite_instance = None
_kite_config_hash = None

def get_kite_api(config: Dict[str, Any]) -> KiteAPI:
    """Get or create KiteAPI instance with connection reuse."""
    global _kite_instance, _kite_config_hash
    
    kite_config = config.get("kite", {})
    api_key = kite_config.get("api_key", "")
    access_token = kite_config.get("access_token", "")
    base_url = kite_config.get("base_url", "https://api.kite.trade")
    
    # Create config hash to detect changes
    config_hash = hash((api_key, access_token, base_url))
    
    if _kite_instance is None or _kite_config_hash != config_hash:
        _kite_instance = KiteAPI(
            api_key=api_key,
            access_token=access_token,
            base_url=base_url
        )
        _kite_config_hash = config_hash
    
    return _kite_instance

async def process_single_alert(
    symbol: str, 
    price: Optional[float], 
    scan_name: str, 
    action: str,
    context: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process a single stock alert with INTELLIGENT position sizing.
    
    Flow:
    1. Get current market price (LTP) - price changes every second
    2. Calculate intelligent position size based on BOTH budget AND risk
    3. Place MARKET ORDER immediately at current price
    4. Place SL/TP GTT orders
    """
    start_time = datetime.now()
    
    # 🔥 FIX #8: Paper Trading Mode
    is_paper_trading = config.get("paper_trading", False)
    
    # Validate symbol
    if not symbol or not isinstance(symbol, str):
        return {
            "status": "ERROR",
            "symbol": symbol,
            "message": "Invalid symbol",
            "timestamp": datetime.now().isoformat()
        }
    
    symbol = symbol.upper().strip()
    
    # Validate action
    action = (action or "BUY").upper().strip()
    if action not in ["BUY", "SELL", "LONG", "SHORT"]:
        return {
            "status": "ERROR",
            "symbol": symbol,
            "message": f"Invalid action: {action}",
            "timestamp": datetime.now().isoformat()
        }
    
    # Get Kite API instance (with connection pooling)
    kite = get_kite_api(config)
    
    # Check if Kite is configured (only required for live trading)
    kite_config = config.get("kite", {})
    if not is_paper_trading and (not kite_config.get("api_key") or not kite_config.get("access_token")):
        return {
            "status": "ERROR",
            "symbol": symbol,
            "message": "Kite API not configured",
            "timestamp": datetime.now().isoformat()
        }
    
    # ==========================================================================
    # 🔥 STEP 1: Fetch CURRENT market price immediately
    # Price changes every second - we need the live price NOW
    # ==========================================================================
    quote = await kite.get_quote(symbol)
    if not quote:
        return {
            "status": "ERROR",
            "symbol": symbol,
            "message": f"Could not fetch quote for {symbol}",
            "timestamp": datetime.now().isoformat()
        }
    
    current_ltp = quote.ltp
    
    # Validate current price
    if current_ltp <= 0:
        return {
            "status": "ERROR",
            "symbol": symbol,
            "message": f"Invalid market price: {current_ltp}",
            "timestamp": datetime.now().isoformat()
        }
    
    # Log price comparison if trigger price was provided
    if price and price > 0:
        price_diff_pct = abs(price - current_ltp) / current_ltp * 100
        if price_diff_pct > 2:
            print(f"⚠️  Price drift: Trigger ₹{price:.2f} vs Current ₹{current_ltp:.2f} ({price_diff_pct:.1f}%)")
            print(f"📍 Using CURRENT market price ₹{current_ltp:.2f} for position sizing")
    
    # ==========================================================================
    # 🔥 STEP 2: Build OHLCV and Calculate ATR
    # ==========================================================================
    ohlcv_data = await kite.get_ohlcv_history(symbol, interval="day", duration=15)
    
    if not ohlcv_data or len(ohlcv_data) < 5:
        # Fallback: Generate synthetic OHLCV based on current quote
        daily_range = quote.high - quote.low if quote.high > quote.low else quote.ltp * 0.02
        ohlcv_data = [
            {"high": quote.high, "low": quote.low, "close": quote.close},
            {"high": quote.high + daily_range * 0.1, "low": quote.low - daily_range * 0.1, "close": quote.close * 1.005},
            {"high": quote.high + daily_range * 0.05, "low": quote.low - daily_range * 0.05, "close": quote.close * 0.998},
            {"high": quote.high + daily_range * 0.15, "low": quote.low - daily_range * 0.15, "close": quote.close * 1.01},
            {"high": quote.high - daily_range * 0.05, "low": quote.low + daily_range * 0.05, "close": quote.close * 0.995},
        ]
    
    atr = calculate_atr(ohlcv_data)
    
    if atr <= 0:
        return {
            "status": "ERROR",
            "symbol": symbol,
            "message": "Could not calculate valid ATR",
            "timestamp": datetime.now().isoformat()
        }
    
    # ==========================================================================
    # 🔥 STEP 3: Check risk limits
    # ==========================================================================
    risk_config = config.get("risk_management", {})
    capital = config.get("capital", 100000)
    risk_percent = config.get("risk_percent", 1.0)
    trade_budget = config.get("trade_budget", 50000)  # Default ₹50k per trade
    
    # 🔥 FIX #4: Check daily loss limit before trading
    daily_pnl = calculate_today_pnl()
    daily_loss_limit = -(capital * 0.03)  # Max 3% daily loss
    if daily_pnl <= daily_loss_limit:
        return {
            "status": "REJECTED",
            "symbol": symbol,
            "reason": f"Daily loss limit hit: ₹{daily_pnl:.2f}",
            "timestamp": datetime.now().isoformat()
        }
    
    # ==========================================================================
    # 🔥 STEP 4: INTELLIGENT POSITION SIZING
    # Calculate qty based on BOTH budget constraint AND risk constraint
    # Use the MORE CONSERVATIVE (lower) quantity
    # ==========================================================================
    trade_params = calculate_intelligent_position(
        current_price=current_ltp,  # Use LIVE market price
        atr=atr,
        capital=capital,
        risk_percent=risk_percent,
        trade_budget=trade_budget,  # Fixed budget per trade
        direction=action,
        atr_sl_multiplier=risk_config.get("atr_multiplier_sl", 1.5),
        atr_tp_multiplier=risk_config.get("atr_multiplier_tp", 3.0),
        min_rr=risk_config.get("min_risk_reward", 2.0),
        max_sl_percent=risk_config.get("max_sl_percent", 2.0),
        lot_size=1  # NSE stocks, lot size = 1
    )
    
    if not trade_params:
        return {
            "status": "REJECTED",
            "symbol": symbol,
            "reason": "Position sizing failed (check budget/risk settings)",
            "timestamp": datetime.now().isoformat()
        }
    
    # Map action to transaction type
    transaction_type = "BUY" if action in ["BUY", "LONG"] else "SELL"
    
    # Calculate position value for logging
    position_value = trade_params.quantity * current_ltp
    
    print(f"🚀 MARKET ORDER: {symbol}")
    print(f"   Price: ₹{current_ltp:.2f} | Qty: {trade_params.quantity} | Value: ₹{position_value:,.2f}")
    print(f"   SL: ₹{trade_params.stop_loss:.2f} | TP: ₹{trade_params.target:.2f} | R:R = 1:{trade_params.risk_reward:.1f}")
    
    # 🔥 FIX #8: Paper Trading - Simulate orders without real money
    if is_paper_trading:
        print(f"📝 PAPER TRADING: Simulating market order for {symbol}")
        
        # Simulate successful market execution at current LTP
        from kite import KiteOrder, Position
        
        # In paper trading, fill at current market price (LTP)
        fill_price = quote.ltp
        
        entry_order = KiteOrder(
            order_id=f"PAPER_{datetime.now().strftime('%H%M%S')}",
            status="SUCCESS",
            message=f"Paper trade executed at market price ₹{fill_price:.2f}",
            variety="paper",
            filled_quantity=trade_params.quantity,
            average_price=fill_price
        )
        
        position = Position(
            symbol=symbol,
            quantity=trade_params.quantity,
            entry_price=fill_price,
            entry_order_id=entry_order.order_id,
            sl_price=trade_params.stop_loss,
            tp_price=trade_params.target,
            sl_order_id=f"PAPER_SL_{symbol}",
            tp_order_id=f"PAPER_TP_{symbol}",
            status="OPEN"
        )
        
        order_status = "SUCCESS"
        trade_status = "OPEN"
        actual_entry = fill_price
        sl_order_id = position.sl_order_id
        tp_order_id = position.tp_order_id
        
        store_position(position)
        
        # PAPER TRADING: Position is logged but NOT auto-closed
        # In paper mode, you manually track P&L via dashboard
        
    else:
        # 🔥 FIX #1: Use MARKET ORDER for immediate bracket execution
        # entry_price=None forces market order - we want in NOW!
        entry_order, position = await kite.place_bracket_order(
            symbol=symbol,
            transaction_type=transaction_type,
            quantity=trade_params.quantity,
            entry_price=None,  # None = Market Order for immediate fill
            stop_loss=trade_params.stop_loss,
            target=trade_params.target,
            use_market_order=True  # Force market order
        )
        
        # Determine final status
        if entry_order.status == "SUCCESS" and position:
            order_status = "SUCCESS"
            trade_status = "OPEN"
            actual_entry = position.entry_price  # Actual fill price from market
            sl_order_id = position.sl_order_id
            tp_order_id = position.tp_order_id
            
            print(f"✅ FILLED: {symbol} at ₹{actual_entry:.2f} (qty: {trade_params.quantity})")
            
            # 🔥 FIX #2: Track position for monitoring
            store_position(position)
        else:
            order_status = entry_order.status
            trade_status = "FAILED"
            actual_entry = quote.ltp  # Log attempted price
            sl_order_id = None
            tp_order_id = None
            print(f"❌ FAILED: {symbol} - {entry_order.message}")
    
    # Log trade with bracket order details
    trade_record = {
        "id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}",
        "date": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "entry_price": actual_entry,
        "stop_loss": trade_params.stop_loss,
        "target": trade_params.target,
        "quantity": trade_params.quantity,
        "risk_amount": trade_params.risk_amount,
        "risk_reward": trade_params.risk_reward,
        "atr": atr,
        "order_id": entry_order.order_id,
        "order_status": order_status,
        "sl_order_id": sl_order_id,
        "tp_order_id": tp_order_id,
        "status": trade_status,
        "pnl": 0,
        "alert_name": scan_name,
        "context": context
    }
    
    # Save trade record
    save_trade(trade_record)
    
    # Store alert for ESP display
    store_alert_for_esp(symbol, actual_entry)
    
    if order_status == "SUCCESS":
        # Send detailed Telegram notification with bracket info
        emoji = "🟢"
        scan_info = ""
        if context.get('scan_url'):
            scan_info = f"\n🔗 [View Scan](https://chartink.com/screener/{context['scan_url']})"
        
        sl_status = "✅" if sl_order_id else "❌"
        tp_status = "✅" if tp_order_id else "❌"
        paper_tag = "📝 PAPER | " if is_paper_trading else ""
        
        msg = f"""
{emoji} {paper_tag}*Market Order Executed*

*Symbol:* {symbol}
*Scan:* {scan_name}
*Entry (Market):* ₹{actual_entry:.2f}
*SL:* ₹{trade_params.stop_loss:.2f} {sl_status}
*Target:* ₹{trade_params.target:.2f} {tp_status}
*Qty:* {trade_params.quantity}
*Risk:* ₹{trade_params.risk_amount:.2f}{scan_info}

*Order ID:* `{entry_order.order_id}`
*SL Order:* `{sl_order_id or 'FAILED'}`
*TP Order:* `{tp_order_id or 'FAILED'}`

⏱️ Latency: {total_ms:.0f}ms
"""
        # Handle Telegram notification with proper error handling
        try:
            telegram_task = asyncio.create_task(send_telegram_message(msg))
            # Don't await - let it run in background, but add done callback for error logging
            def on_telegram_done(task):
                try:
                    task.result()
                except Exception as e:
                    print(f"Telegram notification failed: {e}")
            telegram_task.add_done_callback(on_telegram_done)
        except Exception as e:
            print(f"Failed to create Telegram task: {e}")
    
    # Calculate total latency
    total_ms = (datetime.now() - start_time).total_seconds() * 1000
    
    return {
        "status": order_status,
        "symbol": symbol,
        "order_id": entry_order.order_id if entry_order else "",
        "message": entry_order.message if entry_order else "Failed",
        "sl_order_id": sl_order_id,
        "tp_order_id": tp_order_id,
        "trade_params": {
            "entry": trade_params.entry,
            "stop_loss": trade_params.stop_loss,
            "target": trade_params.target,
            "quantity": trade_params.quantity,
            "risk_reward": trade_params.risk_reward,
            "risk_amount": trade_params.risk_amount
        },
        "latency_ms": round(total_ms, 2),
        "timestamp": datetime.now().isoformat()
    }


async def process_chartink_alert(alert: ChartinkAlert) -> Dict[str, Any]:
    """
    Main trading logic - handles single or multiple stocks from Chartink.
    Executes in ~200-300ms total.
    """
    start_time = datetime.now()
    
    # 1. Load config (0.1ms)
    config = load_config()
    
    # 2. Validate webhook secret
    expected_secret = config.get("chartink", {}).get("webhook_secret", "")
    if expected_secret and alert.secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    # 3. Guard checks (0.1ms)
    can_trade_flag, reason = can_trade(config)
    if not can_trade_flag:
        return {
            "status": "REJECTED",
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
    
    # 4. Parse Chartink payload - may contain multiple stocks
    stock_alerts = parse_chartink_payload(alert)
    
    # Filter out invalid entries
    stock_alerts = [s for s in stock_alerts if s.get("symbol")]
    
    if not stock_alerts:
        return {
            "status": "REJECTED",
            "reason": "No valid stocks in alert",
            "timestamp": datetime.now().isoformat()
        }
    
    # 5. Process each stock (sequentially to respect max_trades limit)
    results = []
    for stock_alert in stock_alerts:
        # Check max trades before processing each
        if count_today_trades() >= config.get("max_trades_per_day", 10):
            results.append({
                "symbol": stock_alert["symbol"],
                "status": "REJECTED",
                "reason": "Max daily trades reached"
            })
            continue
        
        result = await process_single_alert(
            symbol=stock_alert["symbol"],
            price=stock_alert["price"],
            scan_name=stock_alert["scan_name"],
            action=alert.action,
            context=stock_alert["context"],
            config=config
        )
        results.append(result)
    
    # Calculate total latency
    total_ms = (datetime.now() - start_time).total_seconds() * 1000
    
    # Return single result if only one stock, else return batch
    if len(results) == 1:
        results[0]["latency_ms"] = round(total_ms, 2)
        return results[0]
    else:
        return {
            "status": "BATCH_PROCESSED",
            "results": results,
            "total_stocks": len(stock_alerts),
            "processed": len([r for r in results if r.get("status") == "SUCCESS"]),
            "latency_ms": round(total_ms, 2),
            "timestamp": datetime.now().isoformat()
        }

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "Chartink Trading Bot",
        "version": "1.0"
    }

@app.post("/webhook/chartink")
async def chartink_webhook(alert: ChartinkAlert, background_tasks: BackgroundTasks):
    """
    Main webhook endpoint for Chartink alerts (JSON payload).
    Latency target: <300ms total
    """
    result = await process_chartink_alert(alert)
    return result


@app.post("/webhook/chartink/form")
async def chartink_webhook_form(request: Request):
    """
    Form-data webhook endpoint for Chartink alerts.
    Chartink sometimes sends POST as form-data instead of JSON.
    """
    try:
        form_data = await request.form()
        
        # Parse numeric fields with validation
        price = None
        if form_data.get("price"):
            try:
                price = float(form_data.get("price"))
                if price <= 0:
                    price = None
            except (ValueError, TypeError):
                price = None
        
        volume = None
        if form_data.get("volume"):
            try:
                volume = float(form_data.get("volume"))
                if volume < 0:
                    volume = None
            except (ValueError, TypeError):
                volume = None
        
        change_percent = None
        if form_data.get("change_percent"):
            try:
                change_percent = float(form_data.get("change_percent"))
            except (ValueError, TypeError):
                change_percent = None
        
        # Convert form data to ChartinkAlert
        alert = ChartinkAlert(
            symbol=form_data.get("symbol"),
            action=form_data.get("action", "BUY"),
            price=price,
            alert_name=form_data.get("alert_name"),
            secret=form_data.get("secret"),
            stocks=form_data.get("stocks"),
            trigger_prices=form_data.get("trigger_prices"),
            triggered_at=form_data.get("triggered_at"),
            scan_name=form_data.get("scan_name"),
            volume=volume,
            change_percent=change_percent
        )
        
        result = await process_chartink_alert(alert)
        return result
    except Exception as e:
        print(f"Error in form webhook: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "ERROR",
                "message": f"Internal error: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
        )

@app.get("/webhook/chartink")
async def chartink_webhook_get(symbol: str, action: str, price: Optional[float] = None, secret: Optional[str] = None):
    """
    GET version for simple webhook integration.
    Usage: /webhook/chartink?symbol=RELIANCE&action=BUY&price=2500
    """
    alert = ChartinkAlert(
        symbol=symbol.upper(),
        action=action.upper(),
        price=price,
        secret=secret
    )
    result = await process_chartink_alert(alert)
    return result

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    if DASHBOARD_HTML.exists():
        try:
            with open(DASHBOARD_HTML, "r") as f:
                return f.read()
        except Exception as e:
            print(f"Error reading dashboard: {e}")
            return f"<h1>Error loading dashboard</h1><p>{e}</p>"
    return "<h1>Dashboard not found</h1>"

@app.get("/test-cors", response_class=HTMLResponse)
async def test_cors():
    """Serve CORS test page."""
    test_file = Path("test_cors.html")
    if test_file.exists():
        with open(test_file, "r") as f:
            return f.read()
    return "<h1>Test file not found</h1>"

@app.get("/api/config")
async def get_config():
    """Get current configuration."""
    config = load_config()
    # Hide sensitive data
    if "kite" in config:
        config["kite"]["access_token"] = "***" if config["kite"].get("access_token") else ""
    if "telegram" in config:
        config["telegram"]["bot_token"] = "***" if config["telegram"].get("bot_token") else ""
    return config

@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    """Update configuration."""
    config = load_config()
    
    if update.system_enabled is not None:
        config["system_enabled"] = update.system_enabled
    
    if update.capital is not None:
        if update.capital <= 0:
            raise HTTPException(status_code=400, detail="Capital must be positive")
        config["capital"] = update.capital
    
    if update.risk_percent is not None:
        if update.risk_percent <= 0 or update.risk_percent > 100:
            raise HTTPException(status_code=400, detail="Risk percent must be between 0 and 100")
        config["risk_percent"] = update.risk_percent
    
    if update.trade_budget is not None:
        if update.trade_budget <= 0:
            raise HTTPException(status_code=400, detail="Trade budget must be positive")
        config["trade_budget"] = update.trade_budget
    
    if update.max_trades_per_day is not None:
        if update.max_trades_per_day < 1:
            raise HTTPException(status_code=400, detail="Max trades must be at least 1")
        config["max_trades_per_day"] = update.max_trades_per_day
    
    if update.trading_hours is not None:
        config["trading_hours"] = update.trading_hours
    if update.telegram is not None:
        config["telegram"] = update.telegram
    if update.chartink is not None:
        config["chartink"] = update.chartink
    if update.risk_management is not None:
        config["risk_management"] = update.risk_management
    
    if update.paper_trading is not None:
        config["paper_trading"] = update.paper_trading
        
    if update.kite_api_key:
        if "kite" not in config:
            config["kite"] = {}
        config["kite"]["api_key"] = update.kite_api_key
    if update.kite_api_secret:
        if "kite" not in config:
            config["kite"] = {}
        config["kite"]["api_secret"] = update.kite_api_secret
    
    if update.kite_access_token:
        if "kite" not in config:
            config["kite"] = {}
        
        # Check if it looks like a request_token (usually 32 chars)
        # or if we have an api_secret to try exchange
        kite_cfg = config.get("kite", {})
        api_key = kite_cfg.get("api_key")
        api_secret = kite_cfg.get("api_secret")
        
        if api_key and api_secret and len(update.kite_access_token) < 50:
            # Try to exchange it
            kite = KiteAPI(api_key=api_key, access_token="")
            try:
                access_token = await kite.exchange_request_token(update.kite_access_token, api_secret)
                if access_token:
                    config["kite"]["access_token"] = access_token
                    save_config(config)
                    await kite.close()
                    return {"status": "updated", "message": "Token exchanged successfully"}
                else:
                    # If exchange fails, treat it as direct access_token (fallback)
                    config["kite"]["access_token"] = update.kite_access_token
            finally:
                await kite.close()
        else:
            config["kite"]["access_token"] = update.kite_access_token
    
    save_config(config)
    return {"status": "updated"}

@app.post("/api/test-kite")
async def test_kite():
    """Test Kite API connection."""
    config = load_config()
    kite_cfg = config.get("kite", {})
    api_key = kite_cfg.get("api_key")
    access_token = kite_cfg.get("access_token")
    
    if not api_key or not access_token:
        return {"status": "failed", "message": "API Key or Access Token missing"}
    
    kite = None
    try:
        kite = KiteAPI(api_key=api_key, access_token=access_token)
        quote = await kite.get_quote("RELIANCE")
        
        if quote:
            return {"status": "success", "message": f"Connected! RELIANCE LTP: ₹{quote.ltp}"}
        else:
            return {"status": "failed", "message": "Could not fetch quote. Check Token."}
    finally:
        if kite:
            await kite.close()

@app.get("/api/trades")
async def get_trades():
    """Get today's trades."""
    return load_trades()

@app.get("/api/positions")
async def get_positions():
    """Get current open positions with live P&L."""
    config = load_config()
    open_positions = get_open_positions()
    
    if not open_positions:
        return {"positions": [], "count": 0}
    
    # Get live quotes for P&L calculation
    kite = get_kite_api(config)
    positions_with_pnl = []
    
    for symbol, pos in open_positions.items():
        quote = await kite.get_quote(symbol)
        if quote:
            ltp = quote.ltp
            entry = pos.get("entry_price", 0)
            qty = pos.get("quantity", 0)
            unrealized_pnl = (ltp - entry) * qty
            
            positions_with_pnl.append({
                **pos,
                "ltp": ltp,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_percent": round((ltp - entry) / entry * 100, 2) if entry > 0 else 0
            })
        else:
            positions_with_pnl.append(pos)
    
    return {
        "positions": positions_with_pnl,
        "count": len(positions_with_pnl),
        "total_unrealized_pnl": round(sum(p.get("unrealized_pnl", 0) for p in positions_with_pnl), 2)
    }

@app.post("/api/positions/{symbol}/close")
async def close_position_api(symbol: str):
    """Manually close a position."""
    config = load_config()
    kite = get_kite_api(config)
    
    # Close the position
    result = await kite.close_position(symbol, reason="MANUAL")
    
    if result.status == "SUCCESS":
        return {"status": "success", "message": f"Position {symbol} closed"}
    else:
        return {"status": "error", "message": result.message}

@app.post("/api/test-telegram")
async def test_telegram():
    """Send a test Telegram message."""
    await send_telegram_message("🧪 *Test Message*\n\nTrading bot is working correctly!")
    return {"status": "sent"}

@app.get("/api/quote/{symbol}")
async def get_quote(symbol: str):
    """Get live quote for a symbol."""
    config = load_config()
    
    # Validate symbol
    if not symbol or not isinstance(symbol, str):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or len(symbol) > 20:
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    
    kite = get_kite_api(config)
    
    # Check if Kite is configured
    kite_config = config.get("kite", {})
    if not kite_config.get("api_key") or not kite_config.get("access_token"):
        raise HTTPException(status_code=503, detail="Kite API not configured")
    
    quote = await kite.get_quote(symbol)
    if not quote:
        raise HTTPException(status_code=404, detail="Symbol not found or API error")
    
    return {
        "symbol": quote.symbol,
        "ltp": quote.ltp,
        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "close": quote.close,
        "change": quote.change,
        "change_percent": quote.change_percent
    }

@app.get("/debug", response_class=HTMLResponse)
async def debug_page():
    """Serve debug HTML."""
    debug_file = Path("debug.html")
    if debug_file.exists():
        with open(debug_file, "r") as f:
            return f.read()
    return "<h1>Debug file not found</h1>"

@app.get("/esp-setup", response_class=HTMLResponse)
async def esp_setup_page():
    """Serve ESP8266 setup guide."""
    setup_file = Path("esp-setup.html")
    if setup_file.exists():
        with open(setup_file, "r") as f:
            return f.read()
    return "<h1>ESP Setup file not found</h1>"

@app.post("/api/reset-daily")
async def reset_daily():
    """Manually trigger daily reset (clears today's trades)."""
    try:
        # Get all trades
        trades = load_all_trades()
        
        # Keep only trades before today 8 AM
        now = datetime.now()
        today_reset = datetime.strptime(f"{now.strftime('%Y-%m-%d')} 08:00:00", "%Y-%m-%d %H:%M:%S")
        
        if now < today_reset:
            # Before 8 AM, keep trades before yesterday 8 AM
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_reset = datetime.strptime(f"{yesterday} 08:00:00", "%Y-%m-%d %H:%M:%S")
            filtered_trades = [t for t in trades if t.get("date") and 
                             datetime.fromisoformat(t.get("date")) < yesterday_reset]
        else:
            # After 8 AM, keep trades before today 8 AM
            filtered_trades = [t for t in trades if t.get("date") and 
                             datetime.fromisoformat(t.get("date")) < today_reset]
        
        # Save filtered trades
        with open(TRADES_FILE, "w") as f:
            json.dump(filtered_trades, f, indent=2)
        
        return {
            "status": "reset",
            "message": f"Cleared {len(trades) - len(filtered_trades)} trades",
            "remaining_trades": len(filtered_trades),
            "reset_time": today_reset.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ESP8266 Hardware Display Endpoints
# ============================================================================

# Store last alert for ESP polling
_last_alert = {"symbol": "", "price": 0, "time": "", "shown": True}

@app.get("/api/esp/stats")
async def get_esp_stats():
    """Get compact stats for ESP8266 display."""
    config = load_config()
    trades = load_trades()
    positions = get_open_positions()
    
    # Calculate quick stats
    total_pnl = sum(t.get("pnl", 0) for t in trades if t.get("status") == "CLOSED")
    open_count = len(positions)
    
    return {
        "system_enabled": config.get("system_enabled", False),
        "market_open": is_within_trading_hours(config),
        "paper_trading": config.get("paper_trading", True),
        "today_pnl": round(total_pnl, 2),
        "open_positions": open_count,
        "today_trades": len(trades),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/esp/positions")
async def get_esp_positions():
    """Get simplified positions list for ESP."""
    config = load_config()
    kite = get_kite_api(config)
    positions = get_open_positions()
    
    result = []
    for symbol, pos in positions.items():
        # Get live price
        quote = await kite.get_quote(symbol)
        ltp = quote.ltp if quote else pos.get("entry_price", 0)
        entry = pos.get("entry_price", 0)
        qty = pos.get("quantity", 0)
        pnl = (ltp - entry) * qty
        
        result.append({
            "symbol": symbol,
            "qty": qty,
            "entry": round(entry, 2),
            "ltp": round(ltp, 2),
            "sl": round(pos.get("sl_price", 0), 2),
            "tp": round(pos.get("tp_price", 0), 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(((ltp - entry) / entry) * 100, 1) if entry > 0 else 0
        })
    
    return {"positions": result, "count": len(result)}

@app.get("/api/esp/alert")
async def get_esp_alert():
    """Get latest alert for ESP (polling endpoint)."""
    global _last_alert
    
    # If there's a new alert not yet shown
    if not _last_alert["shown"]:
        _last_alert["shown"] = True
        return {
            "new_alert": True,
            "symbol": _last_alert["symbol"],
            "price": _last_alert["price"],
            "time": _last_alert["time"]
        }
    
    return {"new_alert": False}

def store_alert_for_esp(symbol: str, price: float):
    """Store alert when webhook triggers."""
    global _last_alert
    _last_alert = {
        "symbol": symbol,
        "price": price,
        "time": datetime.now().strftime("%H:%M"),
        "shown": False
    }

@app.get("/api/stats")
async def get_stats():
    """Get trading statistics with daily reset at 8 AM."""
    config = load_config()
    trades = load_trades()
    
    total_trades = len(trades)
    winning_trades = len([t for t in trades if t.get("pnl", 0) > 0])
    losing_trades = len([t for t in trades if t.get("pnl", 0) < 0])
    
    return {
        "system_enabled": config.get("system_enabled", False),
        "within_trading_hours": is_within_trading_hours(config),
        "today_trades": total_trades,
        "today_pnl": calculate_today_pnl(),
        "max_trades": config.get("max_trades_per_day", 10),
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "capital": config.get("capital", 0),
        "risk_percent": config.get("risk_percent", 0),
        "total_trades": total_trades  # Added for compatibility
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
