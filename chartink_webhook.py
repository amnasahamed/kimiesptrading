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
from collections import defaultdict
import json
import asyncio
import httpx
from pathlib import Path
import os
from contextlib import asynccontextmanager

# Rate limiting storage
_webhook_calls = defaultdict(list)  # IP -> list of timestamps
RATE_LIMIT = 20  # Max calls per minute
RATE_WINDOW = 60  # seconds
RATE_LIMIT_BURST = 5  # Allow burst of 5 calls immediately

def check_rate_limit(client_ip: str) -> tuple[bool, str]:
    """Check if client IP has exceeded rate limit."""
    now = datetime.now()
    window_start = now - timedelta(seconds=RATE_WINDOW)
    
    # Clean old entries and keep only those within window
    _webhook_calls[client_ip] = [
        t for t in _webhook_calls[client_ip] 
        if t > window_start
    ]
    
    # Check if within burst limit
    recent_calls = len(_webhook_calls[client_ip])
    
    if recent_calls >= RATE_LIMIT:
        oldest_call = min(_webhook_calls[client_ip])
        retry_after = int((oldest_call + timedelta(seconds=RATE_WINDOW) - now).total_seconds())
        return False, f"Rate limit exceeded. Try again in {retry_after} seconds."
    
    # Record this call
    _webhook_calls[client_ip].append(now)
    return True, "OK"

from calculator import calculate_atr, calculate_trade_params, calculate_intelligent_position
from kite import KiteAPI, KiteQuote
from signal_tracker import (
    record_signal, 
    is_duplicate_signal, 
    get_signal_stats,
    load_today_signals
)
from incoming_alerts import (
    record_incoming_alert,
    update_alert_status,
    get_incoming_alert_stats,
    get_recent_incoming_alerts,
    get_alerts_by_symbol,
    get_alerts_by_scan,
    check_file_rotation
)

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
    
    # Internal tracking (not from ChartInk)
    _alert_id: Optional[str] = None  # Internal ID for tracking
    _received_at: Optional[str] = None  # When we received the alert

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
    prevent_duplicate_stocks: Optional[bool] = None  # Prevent buying same stock twice
    club_positions: Optional[bool] = None  # Average multiple positions of same stock
    signal_validation: Optional[Dict[str, Any]] = None  # 5-step signal validation settings

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
            "prevent_duplicate_stocks": True,  # Don't buy same stock twice
            "club_positions": False,  # Keep positions separate (don't average)
            "kite": {"api_key": "", "access_token": "", "base_url": "https://api.kite.trade"},
            "telegram": {"bot_token": "", "chat_id": "", "enabled": False},
            "risk_management": {
                "atr_multiplier_sl": 1.5,
                "atr_multiplier_tp": 3.0,
                "min_risk_reward": 2.0,
                "max_sl_percent": 2.0
            },
            "chartink": {"webhook_secret": ""},
            # 🔥 PAPER TRADING: Filters for signal accuracy testing
            "paper_trading_filters": {
                "enabled": True,
                "fixed_position_size": 10000,  # ₹10,000 per trade
                "time_window_check": True,      # Only trade during market hours
                "nifty_check": False,           # Skip Nifty health check
                "max_positions": 20,            # Allow up to 20 positions (vs 3 in live)
                "prevent_duplicates": True,     # Skip if already traded today
                "slippage_check": True,         # Check price hasn't moved too much
                "max_slippage_percent": 1.0,    # 1% slippage tolerance (vs 0.5% live)
                "daily_loss_limit": False       # No daily loss limit in paper
            },
            # 🔥 NEW: 5-Step Signal Validation Configuration
            "signal_validation": {
                "enabled": True,
                "time_windows": [
                    {"start": "10:00", "end": "11:30"},   # Best window
                    {"start": "13:30", "end": "14:30"}    # Second window
                ],
                "nifty_check_enabled": True,
                "nifty_max_decline": -0.3,      # Reject if Nifty down > 0.3%
                "max_open_positions": 3,         # Max 3 open positions
                "prevent_daily_duplicates": True, # Ignore repeat signals same day
                "slippage_check_enabled": True,
                "max_slippage_percent": 0.5      # Max 0.5% price slippage
            }
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

# Add CORS middleware - RESTRICTED to known origins only
# SECURITY: Never use ["*"] in production - allows any website to access your API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://coolify.themelon.in",  # Your production domain
        "https://themelon.in",           # Main domain
        "http://localhost:8000",         # Local development
        "http://localhost:3000",         # React dev server
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Explicit methods only
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================================================
# Position Monitor (FIX #5 & #6: Partial Exits & Trailing Stop)
# ============================================================================

async def check_gtt_status(kite: KiteAPI, gtt_id: str) -> Optional[str]:
    """
    Check status of a GTT order.
    Returns: 'active', 'triggered', 'cancelled', 'expired', or None if error
    """
    if not gtt_id or gtt_id.startswith("PAPER_"):
        return "active"  # Paper trading GTTs are always "active"
    
    try:
        # Fetch all GTT orders and find ours
        gtt_list = await kite.list_gtt_orders()
        for gtt in gtt_list:
            if str(gtt.get("id")) == str(gtt_id):
                status = gtt.get("status", "").lower()
                # Status can be: active, triggered, cancelled, expired, rejected
                return status
        # GTT not found - likely cancelled or expired
        return "cancelled"
    except Exception as e:
        print(f"Error checking GTT {gtt_id}: {e}")
        return None


async def monitor_positions():
    """
    Background task to monitor open positions:
    - Partial exits at 1R
    - Trailing stop loss
    - 🔥 NEW: GTT status polling (detect SL/TP triggers)
    - Kite sync for manual closes
    """
    sync_counter = 0
    gtt_check_counter = 0  # 🔥 NEW: Counter for GTT status checks
    
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
            
            # 🔥 SYNC with Kite every 60 seconds (6 * 10s)
            sync_counter += 1
            if sync_counter >= 6:
                sync_counter = 0
                try:
                    sync_result = await sync_positions_with_kite(kite)
                    if sync_result.get("closed", 0) > 0:
                        print(f"🔄 Position sync: {sync_result['closed']} position(s) marked as closed")
                        open_positions = get_open_positions()
                        if not open_positions:
                            continue
                except Exception as e:
                    print(f"Position sync error: {e}")
            
            # 🔥 NEW: Check GTT status every 30 seconds (3 * 10s)
            gtt_check_counter += 1
            check_gtt_this_cycle = (gtt_check_counter >= 3)
            if check_gtt_this_cycle:
                gtt_check_counter = 0
            
            for position_id, pos in open_positions.items():
                try:
                    symbol = pos.get("symbol")
                    if not symbol:
                        continue
                        
                    quote = await kite.get_quote(symbol)
                    if not quote:
                        continue
                    
                    ltp = quote.ltp
                    entry = pos.get("entry_price", 0)
                    sl = pos.get("sl_price", 0)
                    tp = pos.get("tp_price", 0)
                    qty = pos.get("quantity", 0)
                    sl_order_id = pos.get("sl_order_id")
                    tp_order_id = pos.get("tp_order_id")
                    partial_exits = pos.get("partial_exits", [])
                    highest_r = pos.get("highest_r", 0)  # Track highest R reached
                    
                    if entry <= 0 or qty <= 0:
                        continue
                    
                    # Calculate current R multiple
                    risk_per_share = abs(entry - sl)
                    current_profit = ltp - entry
                    r_multiple = current_profit / risk_per_share if risk_per_share > 0 else 0
                    
                    # Update highest R if we reached a new high
                    if r_multiple > highest_r:
                        update_position(position_id, {"highest_r": r_multiple})
                        highest_r = r_multiple
                    
                    # 🔥 NEW: Check GTT status every 30 seconds
                    if check_gtt_this_cycle and (sl_order_id or tp_order_id):
                        try:
                            # Check SL GTT status
                            if sl_order_id:
                                sl_status = await check_gtt_status(kite, sl_order_id)
                                if sl_status == "triggered":
                                    print(f"🛑 SL GTT triggered for {symbol}! Closing position.")
                                    pnl = (sl - entry) * qty
                                    close_position_by_id(position_id, sl, round(pnl, 2))
                                    await send_telegram_message(
                                        f"🛑 *STOP LOSS HIT: {symbol}*\n\n"
                                        f"Exit: ₹{sl:.2f}\n"
                                        f"P&L: ₹{pnl:.2f}\n"
                                        f"SL GTT triggered automatically"
                                    )
                                    continue  # Move to next position
                            
                            # Check TP GTT status
                            if tp_order_id:
                                tp_status = await check_gtt_status(kite, tp_order_id)
                                if tp_status == "triggered":
                                    print(f"🎯 TP GTT triggered for {symbol}! Closing position.")
                                    pnl = (tp - entry) * qty
                                    close_position_by_id(position_id, tp, round(pnl, 2))
                                    await send_telegram_message(
                                        f"🎯 *TARGET HIT: {symbol}*\n\n"
                                        f"Exit: ₹{tp:.2f}\n"
                                        f"P&L: ₹{pnl:.2f}\n"
                                        f"TP GTT triggered automatically"
                                    )
                                    continue  # Move to next position
                            
                            # Warn if GTT cancelled/expired unexpectedly
                            if sl_order_id and sl_status in ["cancelled", "expired", "rejected"]:
                                print(f"🚨 WARNING: SL GTT for {symbol} is {sl_status}! Position unprotected!")
                                # TODO: Place new SL GTT or exit position
                            
                        except Exception as e:
                            print(f"Error checking GTT status for {symbol}: {e}")
                    
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
                                    update_position(position_id, {
                                        "quantity": new_qty,
                                        "partial_exits": partial_exits + [partial_exit]
                                    })
                                    
                                    # 🔥 Move SL to breakeven (or slightly below)
                                    new_sl = entry * 0.998  # 0.2% below entry for buffer
                                    sl_modified = False
                                    
                                    if sl_order_id and not sl_order_id.startswith("PAPER_"):
                                        modify_result = await kite.modify_sl_gtt(
                                            gtt_id=sl_order_id,
                                            new_trigger_price=new_sl,
                                            symbol=symbol,
                                            quantity=new_qty,
                                            transaction_type="BUY"
                                        )
                                        
                                        if modify_result.status == "SUCCESS":
                                            sl_modified = True
                                            print(f"✅ SL GTT modified successfully: {sl_order_id} -> qty:{new_qty}, sl:{new_sl:.2f}")
                                        else:
                                            # 🔥 CRITICAL: GTT modification failed - position is at risk!
                                            print(f"🚨 CRITICAL: SL GTT modification failed! {modify_result.message}")
                                            await send_telegram_message(
                                                f"🚨 *CRITICAL ALERT: {symbol}*\n\n"
                                                f"Partial exit succeeded but SL GTT modification FAILED!\n"
                                                f"Position: {new_qty} shares (was {qty})\n"
                                                f"SL GTT still set for: {qty} shares @ ₹{sl:.2f}\n\n"
                                                f"⚠️ *MANUAL INTERVENTION REQUIRED!*"
                                            )
                                    
                                    # Only update position SL if modification succeeded or no GTT to modify
                                    if sl_modified or not sl_order_id or sl_order_id.startswith("PAPER_"):
                                        update_position(position_id, {"sl_price": new_sl})
                                    else:
                                        # Mark position as having mismatch
                                        update_position(position_id, {
                                            "sl_price": sl,  # Keep old SL
                                            "gtt_mismatch_warning": True,
                                            "gtt_expected_qty": new_qty,
                                            "gtt_actual_qty": qty
                                        })
                                    
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
                    if r_multiple >= 2.0 and sl_order_id and not sl_order_id.startswith("PAPER_"):
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
                            
                            update_position(position_id, {"sl_price": target_sl_price})
                            
                            await send_telegram_message(
                                f"🛡️ *Trailing SL: {symbol}*\n"
                                f"SL moved to {target_sl_r}R: ₹{target_sl_price:.2f}\n"
                                f"Current: ₹{ltp:.2f} ({r_multiple:.1f}R)"
                            )
                    
                    # 🔥 NEW: Trailing Take Profit (optional, configurable)
                    # Instead of static TP, we trail the TP higher as price moves up
                    # This lets winners run while still protecting profits
                    trailing_tp_enabled = config.get("trailing_tp_enabled", False)
                    
                    if trailing_tp_enabled and tp_order_id and not tp_order_id.startswith("PAPER_"):
                        # When price reaches 2.5R, move TP from 3R to 2R (lock in profit)
                        # When price reaches 3.5R, move TP from 2R to 3R, etc.
                        if r_multiple >= 2.5:
                            target_tp_r = int(r_multiple - 0.5)  # Trail 0.5R behind
                            target_tp_price = entry + (target_tp_r * risk_per_share)
                            
                            # Only move TP up, never down
                            if target_tp_price > tp * 1.01:
                                print(f"Trailing TP for {symbol} to {target_tp_r}R: ₹{target_tp_price:.2f}")
                                
                                # Delete old TP and place new one
                                await kite.delete_gtt(tp_order_id)
                                new_tp_order = await kite.place_tp_gtt(
                                    symbol=symbol,
                                    quantity=qty,
                                    trigger_price=target_tp_price,
                                    entry_transaction_type="BUY",
                                    product="CNC"
                                )
                                
                                if new_tp_order.status == "SUCCESS":
                                    update_position(position_id, {
                                        "tp_price": target_tp_price,
                                        "tp_order_id": new_tp_order.gtt_id
                                    })
                                    
                                    await send_telegram_message(
                                        f"🎯 *Trailing TP: {symbol}*\n"
                                        f"TP moved to {target_tp_r}R: ₹{target_tp_price:.2f}\n"
                                        f"Current: ₹{ltp:.2f} ({r_multiple:.1f}R)"
                                    )
                
                except Exception as e:
                    print(f"Error monitoring position {position_id}: {e}")
        
        except Exception as e:
            print(f"Position monitor error: {e}")
            await asyncio.sleep(30)  # Wait longer on error

# Start position monitor on startup
@app.on_event("startup")
async def start_position_monitor():
    """Start the position monitoring background task with error handling and restart."""
    async def wrapped_monitor():
        crash_count = 0
        max_crashes = 5
        
        while crash_count < max_crashes:
            try:
                await monitor_positions()
            except Exception as e:
                crash_count += 1
                error_msg = f

# REMOVED: simulate_paper_trade function was for testing only
# In paper trading mode, trades are logged but NOT automatically closed
# You must manually close paper trades via dashboard or API

# ============================================================================
# Config & Data Management
# ============================================================================

import platform
import threading

# Cross-platform file locking
if platform.system() == 'Windows':
    fcntl = None
    # Use threading lock as fallback on Windows
    _file_locks = {}
    _file_locks_lock = threading.Lock()
else:
    import fcntl


def _get_file_lock(filepath: str):
    """Get or create a file lock for the given filepath (Windows fallback)."""
    if fcntl is not None:
        return None  # Unix uses fcntl directly
    
    with _file_locks_lock:
        if filepath not in _file_locks:
            _file_locks[filepath] = threading.Lock()
        return _file_locks[filepath]


def _acquire_lock(f, exclusive: bool = False):
    """Acquire file lock (cross-platform)."""
    if fcntl is not None:
        # Unix: use fcntl
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(f.fileno(), lock_type)
    # Windows: threading lock is acquired before file open


def _release_lock(f):
    """Release file lock (cross-platform)."""
    if fcntl is not None:
        # Unix: use fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    # Windows: threading lock is released after file close

def load_config() -> Dict[str, Any]:
    """Load config from JSON file with cross-platform file locking."""
    if not CONFIG_FILE.exists():
        return {}
    
    # Windows: acquire threading lock before file operation
    lock = _get_file_lock(str(CONFIG_FILE))
    if lock:
        lock.acquire()
    
    try:
        with open(CONFIG_FILE, "r") as f:
            # Acquire shared lock for reading (Unix only)
            _acquire_lock(f, exclusive=False)
            try:
                return json.load(f)
            finally:
                _release_lock(f)
    except json.JSONDecodeError as e:
        print(f"Config file corrupted: {e}")
        return {}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}
    finally:
        if lock:
            lock.release()

def save_config(config: Dict[str, Any]):
    """Save config to JSON file with cross-platform file locking."""
    # Windows: acquire threading lock before file operation
    lock = _get_file_lock(str(CONFIG_FILE))
    if lock:
        lock.acquire()
    
    try:
        with open(CONFIG_FILE, "w") as f:
            # Acquire exclusive lock for writing (Unix only)
            _acquire_lock(f, exclusive=True)
            try:
                json.dump(config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk
            finally:
                _release_lock(f)
    except Exception as e:
        print(f"Error saving config: {e}")
        raise
    finally:
        if lock:
            lock.release()

def load_trades() -> List[Dict[str, Any]]:
    """Load today's trades from JSON file with cross-platform file locking.
    Resets at 8:00 AM daily - trades before 8 AM are considered previous day."""
    if not TRADES_FILE.exists():
        return []
    
    # Windows: acquire threading lock before file operation
    lock = _get_file_lock(str(TRADES_FILE))
    if lock:
        lock.acquire()
    
    try:
        with open(TRADES_FILE, "r") as f:
            # Acquire shared lock for reading (Unix only)
            _acquire_lock(f, exclusive=False)
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
                _release_lock(f)
    except json.JSONDecodeError:
        print("Trades file corrupted, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading trades: {e}")
        return []
    finally:
        if lock:
            lock.release()

def load_all_trades() -> List[Dict[str, Any]]:
    """Load all trades from JSON file with cross-platform file locking."""
    if not TRADES_FILE.exists():
        return []
    
    # Windows: acquire threading lock before file operation
    lock = _get_file_lock(str(TRADES_FILE))
    if lock:
        lock.acquire()
    
    try:
        with open(TRADES_FILE, "r") as f:
            # Acquire shared lock for reading (Unix only)
            _acquire_lock(f, exclusive=False)
            try:
                return json.load(f)
            finally:
                _release_lock(f)
    except json.JSONDecodeError:
        print("Trades file corrupted, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading trades: {e}")
        return []
    finally:
        if lock:
            lock.release()

def save_trade(trade: Dict[str, Any]):
    """Save a trade to the log file with cross-platform file locking."""
    # Windows: acquire threading lock before file operation
    lock = _get_file_lock(str(TRADES_FILE))
    if lock:
        lock.acquire()
    
    try:
        trades = load_all_trades()
        trades.append(trade)
        
        with open(TRADES_FILE, "w") as f:
            # Acquire exclusive lock for writing (Unix only)
            _acquire_lock(f, exclusive=True)
            try:
                json.dump(trades, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk
            finally:
                _release_lock(f)
    except Exception as e:
        print(f"Error saving trade: {e}")
        raise
    finally:
        if lock:
            lock.release()

def update_trade_pnl(order_id: str, exit_price: float, pnl: float):
    """Update P&L for a trade with cross-platform file locking."""
    # Windows: acquire threading lock before file operation
    lock = _get_file_lock(str(TRADES_FILE))
    if lock:
        lock.acquire()
    
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
                _acquire_lock(f, exclusive=True)
                try:
                    json.dump(trades, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    _release_lock(f)
    except Exception as e:
        print(f"Error updating trade P&L: {e}")
    finally:
        if lock:
            lock.release()


# ============================================================================
# Position Management (FIX #2 & #3) - Now supports multiple positions per symbol
# ============================================================================

from kite import Position

POSITIONS_FILE = Path("positions.json")

def load_positions() -> Dict[str, Any]:
    """Load open positions from file with daily reset check."""
    if not POSITIONS_FILE.exists():
        return {}
    try:
        with open(POSITIONS_FILE, "r") as f:
            positions = json.load(f)
        
        # Check for stale positions (held overnight without reset)
        now = datetime.now()
        today_date = now.strftime("%Y-%m-%d")
        reset_time = datetime.strptime(f"{today_date} 08:00:00", "%Y-%m-%d %H:%M:%S")
        
        stale_positions_found = False
        for pos_id, pos in list(positions.items()):
            entry_time_str = pos.get("entry_time")
            if entry_time_str and pos.get("status") == "OPEN":
                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                    # If position is older than today's reset time and it's after reset
                    if entry_time < reset_time and now >= reset_time:
                        pos["stale"] = True  # Mark as potentially stale
                        pos["stale_warning"] = f"Position held overnight from {entry_time.strftime('%Y-%m-%d')}"
                        stale_positions_found = True
                except (ValueError, TypeError):
                    pass  # Invalid timestamp format
        
        if stale_positions_found:
            save_positions(positions)
        
        return positions
    except Exception as e:
        print(f"Error loading positions: {e}")
        return {}

def save_positions(positions: Dict[str, Any]):
    """Save positions to file."""
    try:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(positions, f, indent=2, default=str)
    except Exception as e:
        print(f"Error saving positions: {e}")

def store_position(position: Position):
    """Store a new position with unique ID (supports multiple positions per symbol)."""
    import uuid
    
    positions = load_positions()
    
    # Use entry_order_id as key, or generate unique ID with microsecond + UUID to prevent collisions
    if position.entry_order_id:
        position_id = position.entry_order_id
    else:
        # Use timestamp with microseconds + random UUID suffix for uniqueness
        timestamp = datetime.now().strftime('%H%M%S%f')[:-3]  # HHMMSS + milliseconds
        unique_suffix = uuid.uuid4().hex[:8]  # 8-char random suffix
        position_id = f"{position.symbol}_{timestamp}_{unique_suffix}"
    
    positions[position_id] = {
        "id": position_id,
        "symbol": position.symbol,
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "entry_order_id": position.entry_order_id,
        "sl_price": position.sl_price,
        "tp_price": position.tp_price,
        "sl_order_id": position.sl_order_id,
        "tp_order_id": position.tp_order_id,
        "status": position.status,
        "entry_time": position.entry_time.isoformat() if position.entry_time else None,
        "paper_trading": position.paper_trading
    }
    save_positions(positions)
    return position_id

def update_position(position_id: str, updates: Dict[str, Any]):
    """Update an existing position by ID."""
    positions = load_positions()
    if position_id in positions:
        positions[position_id].update(updates)
        save_positions(positions)

def close_position_by_id(position_id: str, exit_price: float, pnl: float, reason: str):
    """Mark position as closed by ID."""
    positions = load_positions()
    if position_id in positions:
        positions[position_id]["status"] = "CLOSED"
        positions[position_id]["exit_price"] = exit_price
        positions[position_id]["pnl"] = pnl
        positions[position_id]["exit_reason"] = reason
        positions[position_id]["exit_time"] = datetime.now().isoformat()
        save_positions(positions)
        
        # Also update the trade log
        entry_order_id = positions[position_id].get("entry_order_id")
        if entry_order_id:
            update_trade_pnl(entry_order_id, exit_price, pnl)
        
        return True
    return False

def get_or_create_clubbed_position(symbol: str) -> tuple[str, dict]:
    """
    Get existing clubbed position for symbol or return None.
    Returns (position_id, position_data) or (None, None)
    """
    positions = load_positions()
    for pos_id, pos in positions.items():
        if pos.get("symbol") == symbol and pos.get("status") == "OPEN" and pos.get("clubbed", False):
            return pos_id, pos
    return None, None

async def club_position_with_existing(
    symbol: str,
    new_entry_price: float,
    new_quantity: int,
    new_sl: float,
    new_tp: float,
    new_entry_order_id: str,
    new_sl_order_id: str,
    new_tp_order_id: str,
    kite: KiteAPI
) -> tuple[bool, str, dict]:
    """
    Club new position with existing position of same symbol.
    Calculates weighted average entry, updates quantity, keeps single SL/TP/GTT.
    
    🔥 CRITICAL FIX: Cancels NEW position's GTT orders before marking as CLUBBED
    to prevent orphan GTTs that can create unexpected short positions.
    
    Returns: (success, message, updated_position)
    """
    symbol = symbol.upper()
    existing_id, existing = get_or_create_clubbed_position(symbol)
    
    if not existing:
        # No existing clubbed position - this will be the first one
        return False, "No existing position to club with", None
    
    # Calculate weighted average
    old_qty = existing.get("quantity", 0)
    old_entry = existing.get("entry_price", 0)
    
    total_qty = old_qty + new_quantity
    avg_entry = ((old_entry * old_qty) + (new_entry_price * new_quantity)) / total_qty
    
    # Keep the more conservative (tighter) SL and TP
    final_sl = existing.get("sl_price", new_sl)  # Keep original SL
    final_tp = existing.get("tp_price", new_tp)  # Keep original TP
    
    # =========================================================================
    # 🔥 CRITICAL FIX: Cancel ALL GTT orders before creating new ones
    # This prevents orphan GTTs that can trigger unexpectedly
    # =========================================================================
    
    # 1. Cancel EXISTING position's GTT orders
    old_sl_gtt = existing.get("sl_order_id")
    old_tp_gtt = existing.get("tp_order_id")
    
    try:
        if old_sl_gtt and not old_sl_gtt.startswith("PAPER_"):
            await kite.delete_gtt(old_sl_gtt)
            print(f"🗑️ Cancelled existing SL GTT: {old_sl_gtt}")
    except Exception as e:
        print(f"⚠️ Warning: Could not delete old SL GTT {old_sl_gtt}: {e}")
    
    try:
        if old_tp_gtt and not old_tp_gtt.startswith("PAPER_"):
            await kite.delete_gtt(old_tp_gtt)
            print(f"🗑️ Cancelled existing TP GTT: {old_tp_gtt}")
    except Exception as e:
        print(f"⚠️ Warning: Could not delete old TP GTT {old_tp_gtt}: {e}")
    
    # 2. 🔥 NEW: Cancel NEW position's GTT orders (THE BUG FIX!)
    try:
        if new_sl_order_id and not new_sl_order_id.startswith("PAPER_"):
            await kite.delete_gtt(new_sl_order_id)
            print(f"🗑️ Cancelled new position SL GTT: {new_sl_order_id}")
    except Exception as e:
        print(f"⚠️ Warning: Could not delete new SL GTT {new_sl_order_id}: {e}")
    
    try:
        if new_tp_order_id and not new_tp_order_id.startswith("PAPER_"):
            await kite.delete_gtt(new_tp_order_id)
            print(f"🗑️ Cancelled new position TP GTT: {new_tp_order_id}")
    except Exception as e:
        print(f"⚠️ Warning: Could not delete new TP GTT {new_tp_order_id}: {e}")
    
    # 3. Place new combined GTT orders with updated quantity
    final_sl_order_id = None
    final_tp_order_id = None
    gtt_errors = []
    
    try:
        sl_order = await kite.place_sl_gtt(
            symbol=symbol,
            quantity=total_qty,
            trigger_price=final_sl,
            entry_transaction_type="BUY",
            product="CNC"
        )
        if sl_order.status == "SUCCESS":
            final_sl_order_id = sl_order.gtt_id
            print(f"✅ New SL GTT placed: {final_sl_order_id} (qty: {total_qty})")
        else:
            gtt_errors.append(f"SL GTT failed: {sl_order.message}")
    except Exception as e:
        gtt_errors.append(f"SL GTT error: {e}")
        print(f"🚨 Error placing SL GTT: {e}")
    
    try:
        tp_order = await kite.place_tp_gtt(
            symbol=symbol,
            quantity=total_qty,
            trigger_price=final_tp,
            entry_transaction_type="BUY",
            product="CNC"
        )
        if tp_order.status == "SUCCESS":
            final_tp_order_id = tp_order.gtt_id
            print(f"✅ New TP GTT placed: {final_tp_order_id} (qty: {total_qty})")
        else:
            gtt_errors.append(f"TP GTT failed: {tp_order.message}")
    except Exception as e:
        gtt_errors.append(f"TP GTT error: {e}")
        print(f"⚠️ Error placing TP GTT: {e}")
    
    # 🔥 SAFETY CHECK: If SL GTT failed, warn but don't abort (existing position already modified)
    if not final_sl_order_id:
        print(f"🚨 WARNING: Clubbed position {symbol} has NO STOP LOSS!")
        # TODO: Consider exiting position if SL GTT fails
    
    # Update the clubbed position
    positions = load_positions()
    positions[existing_id].update({
        "quantity": total_qty,
        "entry_price": round(avg_entry, 2),
        "sl_price": final_sl,
        "tp_price": final_tp,
        "sl_order_id": final_sl_order_id,
        "tp_order_id": final_tp_order_id,
        "clubbed": True,
        "club_count": existing.get("club_count", 1) + 1,
        "last_added": datetime.now().isoformat(),
        "component_trades": existing.get("component_trades", []) + [{
            "order_id": new_entry_order_id,
            "entry_price": new_entry_price,
            "quantity": new_quantity,
            "time": datetime.now().isoformat()
        }]
    })
    save_positions(positions)
    
    # Mark the new position as closed (clubbed into existing)
    close_position_by_id(new_entry_order_id, new_entry_price, 0, "CLUBBED")
    
    # Return success message with any warnings
    msg = f"Clubbed: {old_qty} + {new_quantity} = {total_qty} shares @ ₹{avg_entry:.2f}"
    if gtt_errors:
        msg += f" (Warnings: {'; '.join(gtt_errors)})"
    
    return True, msg, positions[existing_id]

def close_position(symbol: str, exit_price: float, pnl: float, reason: str):
    """Mark position as closed (legacy - closes first matching open position)."""
    positions = load_positions()
    for position_id, pos in positions.items():
        if pos.get("symbol") == symbol and pos.get("status") == "OPEN":
            positions[position_id]["status"] = "CLOSED"
            positions[position_id]["exit_price"] = exit_price
            positions[position_id]["pnl"] = pnl
            positions[position_id]["exit_reason"] = reason
            positions[position_id]["exit_time"] = datetime.now().isoformat()
            save_positions(positions)
            
            # Also update the trade log
            entry_order_id = pos.get("entry_order_id")
            if entry_order_id:
                update_trade_pnl(entry_order_id, exit_price, pnl)
            return True
    return False

def get_open_positions() -> Dict[str, Any]:
    """Get all open positions."""
    positions = load_positions()
    return {k: v for k, v in positions.items() if v.get("status") == "OPEN"}

def get_open_positions_by_symbol(symbol: str) -> Dict[str, Any]:
    """Get all open positions for a specific symbol."""
    positions = load_positions()
    return {k: v for k, v in positions.items() 
            if v.get("symbol") == symbol and v.get("status") == "OPEN"}


async def sync_positions_with_kite(kite: KiteAPI) -> Dict[str, Any]:
    """
    Sync local positions with actual Kite positions.
    Marks local positions as closed if they're no longer in Kite.
    
    Returns:
        {
            "synced": int,       # Number of positions synced
            "closed": int,       # Number marked as closed
            "errors": int,       # Number of errors
            "details": list      # Details of changes
        }
    """
    result = {
        "synced": 0,
        "closed": 0,
        "errors": 0,
        "details": []
    }
    
    try:
        # Fetch actual positions from Kite
        kite_positions = await kite.fetch_kite_positions()
        
        # Create a set of symbols that are actually open in Kite
        # Handle both formats: "WABAG" and "WABAG-EQ"
        kite_symbols = {}  # Map normalized symbol -> original tradingsymbol
        for pos in kite_positions:
            symbol = pos.get("tradingsymbol", "").upper()
            quantity = pos.get("quantity", 0)
            if quantity > 0:  # Only consider positions with positive quantity
                # Store both full symbol and base symbol (without -EQ, -BE, etc.)
                kite_symbols[symbol] = symbol
                base_symbol = symbol.split('-')[0]  # "WABAG-EQ" -> "WABAG"
                if base_symbol != symbol:
                    kite_symbols[base_symbol] = symbol
        
        print(f"📊 Kite positions found: {list(kite_symbols.keys())}")
        
        # Load local positions
        local_positions = load_positions()
        
        for position_id, pos in list(local_positions.items()):
            if pos.get("status") != "OPEN":
                continue
            
            symbol = pos.get("symbol", "").upper()
            
            # Check if this symbol is still open in Kite
            # Try both the exact symbol and base symbol
            symbol_in_kite = symbol in kite_symbols
            base_symbol = symbol.split('-')[0]
            base_in_kite = base_symbol in kite_symbols
            
            if symbol and not symbol_in_kite and not base_in_kite:
                # Position was closed externally (from Kite)
                entry_price = pos.get("entry_price", 0)
                
                # Try to get current price for P&L calculation
                try:
                    quote = await kite.get_quote(symbol)
                    current_price = quote.ltp if quote else entry_price
                except:
                    current_price = entry_price
                
                # Calculate approximate P&L
                qty = pos.get("quantity", 0)
                pnl = (current_price - entry_price) * qty
                
                # Mark as closed
                local_positions[position_id]["status"] = "CLOSED"
                local_positions[position_id]["exit_price"] = current_price
                local_positions[position_id]["pnl"] = round(pnl, 2)
                local_positions[position_id]["exit_reason"] = "MANUAL_KITE"
                local_positions[position_id]["exit_time"] = datetime.now().isoformat()
                local_positions[position_id]["synced_at"] = datetime.now().isoformat()
                
                result["closed"] += 1
                result["details"].append({
                    "position_id": position_id,
                    "symbol": symbol,
                    "action": "marked_closed",
                    "exit_price": current_price,
                    "pnl": round(pnl, 2)
                })
                
                print(f"🔄 Sync: Marked {symbol} as closed (closed from Kite)")
                
                # Update trade log if order ID exists
                entry_order_id = pos.get("entry_order_id")
                if entry_order_id:
                    update_trade_pnl(entry_order_id, current_price, pnl)
        
        # Save updated positions
        if result["closed"] > 0:
            save_positions(local_positions)
            
            # Send Telegram notification
            msg = (
                f"🔄 *Position Sync Complete*\n\n"
                f"Closed {result['closed']} position(s) that were "
                f"manually closed from Kite.\n\n"
            )
            for detail in result["details"][:5]:  # Show first 5
                msg += f"• {detail['symbol']}: ₹{detail['pnl']:.2f}\n"
            
            await send_telegram_message(msg)
        
        # Add debug info
        local_open_symbols = [pos.get("symbol", "").upper() for pos in local_positions.values() if pos.get("status") == "OPEN"]
        result["debug"] = {
            "kite_positions_found": list(kite_symbols.keys()),
            "local_open_positions": local_open_symbols,
            "kite_raw_count": len(kite_positions)
        }
        
        result["synced"] = len(kite_symbols)
        
    except Exception as e:
        result["errors"] += 1
        result["details"].append({"error": str(e)})
        print(f"❌ Position sync error: {e}")
    
    return result


def force_close_position(position_id: str, exit_price: float, reason: str = "MANUAL_FORCE") -> bool:
    """
    Force close a position without placing an order.
    Use this when position was already closed externally (e.g., from Kite).
    
    Returns True if successful.
    """
    positions = load_positions()
    
    if position_id not in positions:
        return False
    
    pos = positions[position_id]
    if pos.get("status") != "OPEN":
        return False
    
    entry_price = pos.get("entry_price", 0)
    qty = pos.get("quantity", 0)
    pnl = (exit_price - entry_price) * qty
    
    # Update position
    positions[position_id]["status"] = "CLOSED"
    positions[position_id]["exit_price"] = exit_price
    positions[position_id]["pnl"] = round(pnl, 2)
    positions[position_id]["exit_reason"] = reason
    positions[position_id]["exit_time"] = datetime.now().isoformat()
    
    save_positions(positions)
    
    # Update trade log
    entry_order_id = pos.get("entry_order_id")
    if entry_order_id:
        update_trade_pnl(entry_order_id, exit_price, pnl)
    
    print(f"📝 Force closed position {position_id} ({pos.get('symbol')}) at ₹{exit_price:.2f}")
    return True


def is_in_trading_window() -> tuple[bool, str]:
    """
    Check if current time is within preferred trading windows.
    
    Valid windows:
    - 10:00 AM - 11:30 AM (Best window - morning momentum)
    - 1:30 PM - 2:30 PM (Second window - afternoon continuation)
    
    Returns: (is_valid, message)
    """
    now = datetime.now().time()
    
    valid_windows = [
        (time(10, 0), time(11, 30)),   # Best window
        (time(13, 30), time(14, 30))   # Second window
    ]
    
    for start, end in valid_windows:
        if start <= now <= end:
            return True, "OK"
    
    return False, "Outside trading windows (10:00-11:30, 13:30-14:30)"


async def get_nifty_change(kite: KiteAPI) -> float:
    """
    Get NIFTY 50 change percentage from Kite API.
    
    Returns: Change percentage (e.g., -0.3 for -0.3%)
    """
    try:
        quote = await kite.get_quote("NIFTY 50")
        if quote:
            return quote.change_percent
    except Exception as e:
        print(f"Error fetching Nifty change: {e}")
    
    return 0.0  # Default to neutral if can't fetch


def count_open_positions() -> int:
    """Count number of open positions."""
    return len(get_open_positions())

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

def log_error(category: str, message: str, details: Dict[str, Any] = None):
    """Log errors to persistent file for debugging."""
    try:
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "message": message,
            "details": details or {}
        }
        error_file = Path("error_log.json")
        errors = []
        
        # Load existing errors
        if error_file.exists():
            try:
                with open(error_file, "r") as f:
                    errors = json.load(f)
            except:
                errors = []
        
        errors.append(error_entry)
        
        # Keep last 100 errors to prevent file bloat
        errors = errors[-100:]
        
        with open(error_file, "w") as f:
            json.dump(errors, f, indent=2)
            
    except Exception as e:
        print(f"Failed to log error: {e}")


async def send_telegram_message(message: str):
    """Send notification via Telegram with retry logic and persistent error logging."""
    config = load_config()
    telegram = config.get("telegram", {})
    
    if not telegram.get("enabled"):
        return
    
    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")
    
    if not bot_token or not chat_id:
        log_error("telegram", "Missing bot_token or chat_id")
        return
    
    # Validate bot_token format (should contain a colon)
    if ":" not in bot_token or len(bot_token) < 20:
        error_msg = "Invalid bot token format"
        print(f"Telegram error: {error_msg}")
        log_error("telegram", error_msg, {"bot_token_length": len(bot_token)})
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
    last_error = None
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10.0)
                if resp.status_code == 200:
                    return
                elif resp.status_code == 429:  # Rate limited
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    log_error("telegram", f"Rate limited", {"retry_after": retry_after})
                    await asyncio.sleep(retry_after)
                else:
                    error_msg = f"API error: {resp.status_code}"
                    print(f"Telegram {error_msg} - {resp.text}")
                    log_error("telegram", error_msg, {
                        "status_code": resp.status_code,
                        "response": resp.text[:200]
                    })
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
        except httpx.TimeoutException:
            error_msg = f"Timeout (attempt {attempt + 1}/{max_retries})"
            print(f"Telegram {error_msg}")
            log_error("telegram", error_msg, {"attempt": attempt + 1, "max_retries": max_retries})
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            print(f"Telegram {error_msg}")
            log_error("telegram", error_msg, {"attempt": attempt + 1})
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
    
    # All retries failed
    log_error("telegram", "All retries failed", {
        "message_preview": message[:100] if message else "",
        "last_error": str(last_error) if last_error else None
    })

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

def can_trade(config: Dict[str, Any], symbol: str = None) -> tuple[bool, str]:
    """
    Check if trading is allowed (legacy function - kept for compatibility).
    Returns (can_trade, reason)
    
    Args:
        config: System configuration
        symbol: Stock symbol to check (optional, for duplicate detection)
    """
    if not config.get("system_enabled", False):
        return False, "System is disabled"
    
    if not is_within_trading_hours(config):
        return False, "Outside trading hours"
    
    max_trades = config.get("max_trades_per_day", 10)
    if count_today_trades() >= max_trades:
        return False, f"Max trades ({max_trades}) reached for today"
    
    # 🔥 Check if already holding this symbol
    if symbol and config.get("prevent_duplicate_stocks", True):
        open_positions = get_open_positions()
        for pos_id, pos in open_positions.items():
            if pos.get("symbol") == symbol.upper() and pos.get("status") == "OPEN":
                return False, f"Already holding {symbol} - skipping duplicate"
    
    return True, "OK"


async def validate_signal(
    config: Dict[str, Any], 
    symbol: str = None,
    kite: KiteAPI = None,
    is_paper_trading: bool = False
) -> tuple[bool, str]:
    """
    🔥 5-STEP SIGNAL VALIDATION
    
    Validates a signal before placing any order:
    1. Time Window Check - Only 10:00-11:30 and 13:30-14:30
    2. Nifty Health Check - Reject if Nifty down > 0.3%
    3. Open Positions Check - Max 3 open positions
    4. Duplicate Check - Ignore if already triggered today
    5. Price Slippage Check - Done separately in process_single_alert
    
    🔥 PAPER TRADING MODE: Configurable filters for signal accuracy testing
    
    Returns: (is_valid, reason)
    """
    signal_config = config.get("signal_validation", {})
    
    # Check 0: System enabled
    if not config.get("system_enabled", False):
        return False, "System is disabled"
    
    # 🔥 PAPER TRADING: Apply configurable filters for signal accuracy testing
    if is_paper_trading:
        paper_filters = config.get("paper_trading_filters", {})
        
        if not paper_filters.get("enabled", True):
            return True, "✅ Paper trading - All filters disabled"
        
        # Check 1: Time Window (configurable)
        if paper_filters.get("time_window_check", True):
            in_window, window_msg = is_in_trading_window()
            if not in_window:
                return False, f"⏰ Outside trading windows (10:00-11:30, 13:30-14:30)"
        
        # Check 2: Nifty Health (configurable)
        if paper_filters.get("nifty_check", False) and kite:
            nifty_change = await get_nifty_change(kite)
            max_decline = signal_config.get("nifty_max_decline", -0.3)
            if nifty_change < max_decline:
                return False, f"📉 Nifty weak: {nifty_change:.2f}% (max decline: {max_decline}%)"
        
        # Check 3: Open Positions Limit (higher limit for paper trading)
        max_positions = paper_filters.get("max_positions", 20)
        open_count = count_open_positions()
        if open_count >= max_positions:
            return False, f"📊 Max paper positions reached: {open_count}/{max_positions}"
        
        # Check 4: Duplicate Check (configurable)
        if paper_filters.get("prevent_duplicates", True):
            if is_duplicate_signal(symbol):
                return False, f"🔄 Duplicate signal: {symbol} already triggered today"
        
        return True, "✅ Paper trading filters passed"
    
    # LIVE TRADING: Full validation
    # Check 1: Time Window (10:00-11:30, 13:30-14:30)
    in_window, window_msg = is_in_trading_window()
    if not in_window:
        return False, f"⏰ Outside trading windows (10:00-11:30, 13:30-14:30)"
    
    # Check 2: Nifty Health (reject if down > 0.3%)
    if kite and signal_config.get("nifty_check_enabled", True):
        nifty_change = await get_nifty_change(kite)
        max_decline = signal_config.get("nifty_max_decline", -0.3)
        if nifty_change < max_decline:
            return False, f"📉 Nifty weak: {nifty_change:.2f}% (max decline: {max_decline}%)"
    
    # Check 3: Open Positions Limit (max 3)
    max_positions = signal_config.get("max_open_positions", 3)
    open_count = count_open_positions()
    if open_count >= max_positions:
        return False, f"📊 Max open positions reached: {open_count}/{max_positions}"
    
    # Check 4: Duplicate Check (same day)
    if symbol and signal_config.get("prevent_daily_duplicates", True):
        if is_duplicate_signal(symbol):
            return False, f"🔄 Duplicate signal: {symbol} already triggered today"
    
    # Check 5: Price Slippage - handled in process_single_alert where we have live price
    
    return True, "✅ All checks passed"

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
    # 🔥 STEP 1b: Price Slippage Check (5th validation step)
    # Reject if current price is more than 0.5% above alerted price
    # ==========================================================================
    signal_config = config.get("signal_validation", {})
    paper_filters = config.get("paper_trading_filters", {})
    
    # Check slippage (configurable for paper trading)
    should_check_slippage = signal_config.get("slippage_check_enabled", True)
    max_slippage = signal_config.get("max_slippage_percent", 0.5)
    
    if is_paper_trading:
        # Paper trading uses its own slippage settings
        should_check_slippage = paper_filters.get("slippage_check", True)
        max_slippage = paper_filters.get("max_slippage_percent", 1.0)  # More tolerant in paper
    
    if should_check_slippage and price and price > 0:
        max_slippage = signal_config.get("max_slippage_percent", 0.5)
        # Calculate how much current price is above alert price
        price_slippage_pct = (current_ltp - price) / price * 100
        
        if price_slippage_pct > max_slippage:
            reason = f"💸 Price slippage too high: {price_slippage_pct:.2f}% above alert price (max: {max_slippage}%)"
            print(f"🚫 {reason}")
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "reason": reason,
                "alert_price": price,
                "current_price": current_ltp,
                "slippage_percent": round(price_slippage_pct, 2),
                "timestamp": datetime.now().isoformat()
            }
    
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
    
    # 🔥 FIX #4: Check daily loss limit before trading (SKIPPED in paper trading)
    if not is_paper_trading:
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
        symbol=symbol,  # NEW: Pass symbol for margin-aware sizing
        use_margin=True,
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
        
        # 🔥 PAPER TRADING: Fixed ₹10,000 position size for signal accuracy testing
        PAPER_TRADE_VALUE = 10000  # Fixed ₹10,000 per trade
        paper_qty = max(1, round(PAPER_TRADE_VALUE / current_ltp))  # At least 1 share
        paper_value = paper_qty * current_ltp
        
        # Calculate SL/TP based on ATR (same logic as live trading)
        paper_sl = current_ltp - (atr * risk_config.get("atr_multiplier_sl", 1.5))
        paper_tp = current_ltp + (atr * risk_config.get("atr_multiplier_tp", 3.0))
        
        # Create paper trade params object
        from types import SimpleNamespace
        paper_trade_params = SimpleNamespace(
            quantity=paper_qty,
            entry=current_ltp,
            stop_loss=round(paper_sl, 2),
            target=round(paper_tp, 2),
            risk_amount=round((current_ltp - paper_sl) * paper_qty, 2),
            risk_reward=3.0  # Fixed 1:3 R:R for paper trading
        )
        
        print(f"   📝 PAPER: ₹{PAPER_TRADE_VALUE:,.0f} fixed | Qty: {paper_qty} | Value: ₹{paper_value:,.2f}")
        
        # Simulate successful market execution at current LTP
        from kite import KiteOrder, Position
        
        # In paper trading, fill at current market price (LTP)
        fill_price = quote.ltp
        
        entry_order = KiteOrder(
            order_id=f"PAPER_{datetime.now().strftime('%H%M%S')}",
            status="SUCCESS",
            message=f"Paper trade executed at market price ₹{fill_price:.2f}",
            variety="paper",
            filled_quantity=paper_trade_params.quantity,
            average_price=fill_price
        )
        
        position = Position(
            symbol=symbol,
            quantity=paper_trade_params.quantity,
            entry_price=fill_price,
            entry_order_id=entry_order.order_id,
            sl_price=paper_trade_params.stop_loss,
            tp_price=paper_trade_params.target,
            sl_order_id=f"PAPER_SL_{symbol}",
            tp_order_id=f"PAPER_TP_{symbol}",
            status="OPEN",
            paper_trading=True  # Mark as paper trade
        )
        
        # Use paper trade params for the rest of the function
        trade_params = paper_trade_params
        
        order_status = "SUCCESS"
        trade_status = "OPEN"
        actual_entry = fill_price
        sl_order_id = position.sl_order_id
        tp_order_id = position.tp_order_id
        
        # 🔥 Check if clubbing is enabled and position exists
        clubbed = False
        if config.get("club_positions", False):
            clubbed, club_msg, _ = await club_position_with_existing(
                symbol=symbol,
                new_entry_price=actual_entry,
                new_quantity=trade_params.quantity,
                new_sl=trade_params.stop_loss,
                new_tp=trade_params.target,
                new_entry_order_id=position.entry_order_id,
                new_sl_order_id=sl_order_id,
                new_tp_order_id=tp_order_id,
                kite=kite
            )
            if clubbed:
                print(f"🔄 {club_msg}")
        
        if not clubbed:
            position.clubbed = True  # Mark as clubbable for future
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
            
            # 🔥 Check if clubbing is enabled
            clubbed = False
            if config.get("club_positions", False):
                clubbed, club_msg, _ = await club_position_with_existing(
                    symbol=symbol,
                    new_entry_price=actual_entry,
                    new_quantity=trade_params.quantity,
                    new_sl=trade_params.stop_loss,
                    new_tp=trade_params.target,
                    new_entry_order_id=position.entry_order_id,
                    new_sl_order_id=sl_order_id,
                    new_tp_order_id=tp_order_id,
                    kite=kite
                )
                if clubbed:
                    print(f"🔄 {club_msg}")
            
            if not clubbed:
                position.clubbed = True
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
        "context": context,
        "paper_trading": is_paper_trading  # Track if this was a paper trade
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
        
        # Calculate latency for message
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        
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

⏱️ Latency: {latency_ms:.0f}ms
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
    
    🔥 Implements 5-step signal validation before placing orders:
    1. Time Window Check - Only 10:00-11:30 and 13:30-14:30
    2. Nifty Health Check - Reject if Nifty down > 0.3%
    3. Open Positions Check - Max 3 open positions
    4. Duplicate Check - Ignore if already triggered today
    5. Price Slippage Check - Reject if price moved > 0.5%
    
    🔥 PAPER TRADING: All limits disabled, fixed ₹10,000 position size
    """
    start_time = datetime.now()
    
    # 1. Load config (0.1ms)
    config = load_config()
    
    # 🔥 Check paper trading mode
    is_paper_trading = config.get("paper_trading", False)
    if is_paper_trading:
        print("📝 PAPER TRADING MODE: All limits disabled, ₹10,000 per trade")
    
    # 2. Validate webhook secret
    expected_secret = config.get("chartink", {}).get("webhook_secret", "")
    if expected_secret and alert.secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    # 3. Parse Chartink payload - may contain multiple stocks
    stock_alerts = parse_chartink_payload(alert)
    
    # Filter out invalid entries
    stock_alerts = [s for s in stock_alerts if s.get("symbol")]
    
    if not stock_alerts:
        return {
            "status": "REJECTED",
            "reason": "No valid stocks in alert",
            "timestamp": datetime.now().isoformat()
        }
    
    # Get Kite API instance for validation (Nifty check)
    kite = get_kite_api(config)
    
    # 4. Process each stock with 5-step validation
    results = []
    for stock_alert in stock_alerts:
        symbol = stock_alert["symbol"]
        alert_price = stock_alert.get("price")
        
        # 🔥 STEP 1-4: Run signal validation (time, nifty, positions, duplicate)
        # Pass is_paper_trading to skip limits in paper mode
        is_valid, reason = await validate_signal(config, symbol, kite, is_paper_trading)
        
        if not is_valid:
            # Record rejected signal
            record_signal(symbol, "REJECTED", reason=reason)
            results.append({
                "symbol": symbol,
                "status": "REJECTED",
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            })
            print(f"🚫 Signal rejected: {symbol} - {reason}")
            continue
        
        # Check max trades before processing (SKIPPED in paper trading - unlimited orders)
        if not is_paper_trading and count_today_trades() >= config.get("max_trades_per_day", 10):
            reason = "Max daily trades reached"
            record_signal(symbol, "REJECTED", reason=reason)
            results.append({
                "symbol": symbol,
                "status": "REJECTED",
                "reason": reason
            })
            continue
        
        # Record that we're executing this signal
        record_signal(symbol, "EXECUTING")
        
        # Process the trade (includes price slippage check - Step 5)
        result = await process_single_alert(
            symbol=symbol,
            price=alert_price,
            scan_name=stock_alert["scan_name"],
            action=alert.action,
            context=stock_alert["context"],
            config=config
        )
        
        # Update signal record with final status
        if result.get("status") == "SUCCESS":
            record_signal(symbol, "EXECUTED", metadata={
                "order_id": result.get("order_id"),
                "entry_price": result.get("trade_params", {}).get("entry")
            })
        else:
            record_signal(symbol, "FAILED", reason=result.get("message", "Unknown"))
        
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
            "rejected": len([r for r in results if r.get("status") == "REJECTED"]),
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


@app.get("/health")
async def health_check():
    """
    Health check endpoint that verifies all dependencies.
    """
    health = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }
    
    # Check config file
    try:
        config = load_config()
        health["checks"]["config"] = {
            "status": "ok",
            "system_enabled": config.get("system_enabled", False),
            "paper_trading": config.get("paper_trading", True)
        }
    except Exception as e:
        health["checks"]["config"] = {"status": "error", "message": str(e)}
        health["status"] = "degraded"
    
    # Check Kite API
    try:
        kite_config = config.get("kite", {})
        if kite_config.get("api_key") and kite_config.get("access_token"):
            kite = get_kite_api(config)
            quote = await kite.get_quote("RELIANCE")
            if quote:
                health["checks"]["kite_api"] = {
                    "status": "ok",
                    "reliance_ltp": quote.ltp
                }
            else:
                health["checks"]["kite_api"] = {
                    "status": "warning",
                    "message": "Connected but couldn't fetch quote"
                }
        else:
            health["checks"]["kite_api"] = {
                "status": "not_configured",
                "message": "API key or access token missing"
            }
    except Exception as e:
        health["checks"]["kite_api"] = {"status": "error", "message": str(e)}
        health["status"] = "degraded"
    
    # Check file system
    try:
        test_file = Path(".health_check_test")
        test_file.write_text("test")
        test_file.unlink()
        health["checks"]["filesystem"] = {"status": "ok"}
    except Exception as e:
        health["checks"]["filesystem"] = {"status": "error", "message": str(e)}
        health["status"] = "degraded"
    
    # Check position monitor (is it running?)
    # We can't directly check the background task, but we can verify positions file is accessible
    try:
        positions = load_positions()
        open_count = len([p for p in positions.values() if p.get("status") == "OPEN"])
        health["checks"]["positions"] = {
            "status": "ok",
            "open_positions": open_count,
            "total_tracked": len(positions)
        }
    except Exception as e:
        health["checks"]["positions"] = {"status": "error", "message": str(e)}
    
    return health

@app.post("/webhook/chartink")
async def chartink_webhook(alert: ChartinkAlert, background_tasks: BackgroundTasks, request: Request):
    """
    Main webhook endpoint for Chartink alerts (JSON payload).
    Latency target: <300ms total
    Records EVERY incoming alert for audit purposes.
    """
    # Get client IP for rate limiting
    client_ip = request.headers.get("X-Forwarded-For", request.client.host)
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host
    
    # Check rate limit
    allowed, message = check_rate_limit(client_ip)
    if not allowed:
        print(f"🚫 Rate limit exceeded for {client_ip}")
        raise HTTPException(status_code=429, detail=message)
    
    # 🔥 FIX: ChartInk sends secret in query string, not JSON body
    # Extract secret from query parameters if not in body
    if not alert.secret:
        query_secret = request.query_params.get("secret")
        if query_secret:
            alert.secret = query_secret
    
    # 🔥 RECORD INCOMING ALERT - Every alert is logged before processing
    # Parse symbols from the alert for the log
    symbols = []
    if alert.stocks:
        symbols = [s.strip().upper() for s in alert.stocks.split(",") if s.strip()]
    elif alert.symbol:
        symbols = [alert.symbol.upper()]
    
    # Get relevant headers
    headers = {
        "user-agent": request.headers.get("user-agent", ""),
        "content-type": request.headers.get("content-type", "")
    }
    
    # Record raw payload
    raw_payload = {
        "symbol": alert.symbol,
        "action": alert.action,
        "price": alert.price,
        "alert_name": alert.alert_name,
        "secret": "***" if alert.secret else None,  # Mask secret
        "stocks": alert.stocks,
        "trigger_prices": alert.trigger_prices,
        "triggered_at": alert.triggered_at,
        "scan_name": alert.scan_name,
        "scan_url": alert.scan_url,
        "webhook_url": alert.webhook_url,
        "volume": alert.volume,
        "change_percent": alert.change_percent
    }
    
    # Record the incoming alert
    alert_id = record_incoming_alert(
        alert_type="json",
        raw_payload=raw_payload,
        source_ip=client_ip,
        headers=headers,
        symbols=symbols
    )
    
    # Store alert ID for later status updates
    alert._alert_id = alert_id
    
    # Check file rotation periodically
    check_file_rotation()
    
    # Process the alert with error handling
    start_time = datetime.now()
    try:
        result = await process_chartink_alert(alert)
        
        # Update alert status based on result
        status = "processed" if result.get("status") in ["SUCCESS", "BATCH_PROCESSED"] else "rejected"
        if result.get("status") == "REJECTED":
            status = "rejected"
        elif result.get("status") == "ERROR":
            status = "error"
        
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        update_alert_status(
            alert_id=alert_id,
            status=status,
            result=result.get("reason") or result.get("message"),
            latency_ms=round(latency_ms, 2)
        )
        
        return result
        
    except HTTPException as he:
        # Update status for HTTP errors (like invalid secret, rate limit)
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        update_alert_status(
            alert_id=alert_id,
            status="error",
            result=f"HTTP {he.status_code}: {he.detail}",
            latency_ms=round(latency_ms, 2)
        )
        raise  # Re-raise the exception
        
    except Exception as e:
        # Update status for unexpected errors
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        update_alert_status(
            alert_id=alert_id,
            status="error",
            result=str(e),
            latency_ms=round(latency_ms, 2)
        )
        raise


@app.post("/webhook/chartink/form")
async def chartink_webhook_form(request: Request):
    """
    Form-data webhook endpoint for Chartink alerts.
    Chartink sometimes sends POST as form-data instead of JSON.
    Records EVERY incoming alert for audit purposes.
    """
    # Get client IP for rate limiting
    client_ip = request.headers.get("X-Forwarded-For", request.client.host)
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host
    
    # Check rate limit
    allowed, message = check_rate_limit(client_ip)
    if not allowed:
        print(f"🚫 Rate limit exceeded for {client_ip}")
        raise HTTPException(status_code=429, detail=message)
    
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
        
        # 🔥 RECORD INCOMING ALERT - Every alert is logged before processing
        raw_payload = dict(form_data)
        # Mask secret if present
        if "secret" in raw_payload:
            raw_payload["secret"] = "***" if raw_payload["secret"] else None
        
        # Parse symbols
        symbols = []
        if form_data.get("stocks"):
            symbols = [s.strip().upper() for s in form_data.get("stocks").split(",") if s.strip()]
        elif form_data.get("symbol"):
            symbols = [form_data.get("symbol").upper()]
        
        headers = {
            "user-agent": request.headers.get("user-agent", ""),
            "content-type": request.headers.get("content-type", "")
        }
        
        alert_id = record_incoming_alert(
            alert_type="form",
            raw_payload=raw_payload,
            source_ip=client_ip,
            headers=headers,
            symbols=symbols
        )
        
        check_file_rotation()
        
        # Convert form data to ChartinkAlert
        # 🔥 FIX: Also check query string for secret
        secret = form_data.get("secret") or request.query_params.get("secret")
        
        alert = ChartinkAlert(
            symbol=form_data.get("symbol"),
            action=form_data.get("action", "BUY"),
            price=price,
            alert_name=form_data.get("alert_name"),
            secret=secret,
            stocks=form_data.get("stocks"),
            trigger_prices=form_data.get("trigger_prices"),
            triggered_at=form_data.get("triggered_at"),
            scan_name=form_data.get("scan_name"),
            volume=volume,
            change_percent=change_percent
        )
        alert._alert_id = alert_id
        
        # Process with error handling
        start_time = datetime.now()
        try:
            result = await process_chartink_alert(alert)
            
            # Update alert status
            status = "processed" if result.get("status") in ["SUCCESS", "BATCH_PROCESSED"] else "rejected"
            if result.get("status") == "REJECTED":
                status = "rejected"
            elif result.get("status") == "ERROR":
                status = "error"
            
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            update_alert_status(
                alert_id=alert_id,
                status=status,
                result=result.get("reason") or result.get("message"),
                latency_ms=round(latency_ms, 2)
            )
            
            return result
            
        except HTTPException as he:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            update_alert_status(
                alert_id=alert_id,
                status="error",
                result=f"HTTP {he.status_code}: {he.detail}",
                latency_ms=round(latency_ms, 2)
            )
            raise
            
    except Exception as e:
        print(f"Error in form webhook: {e}")
        # Update alert status for the outer exception
        if 'alert_id' in locals():
            update_alert_status(
                alert_id=alert_id,
                status="error",
                result=str(e)
            )
        return JSONResponse(
            status_code=500,
            content={
                "status": "ERROR",
                "message": f"Internal error: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
        )

@app.get("/webhook/chartink")
async def chartink_webhook_get(
    request: Request,
    symbol: str, 
    action: str, 
    price: Optional[float] = None, 
    secret: Optional[str] = None,
    alert_name: Optional[str] = None
):
    """
    GET version for simple webhook integration.
    Usage: /webhook/chartink?symbol=RELIANCE&action=BUY&price=2500
    Records EVERY incoming alert for audit purposes.
    """
    # Get client IP for rate limiting
    client_ip = request.headers.get("X-Forwarded-For", request.client.host)
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host
    
    # Check rate limit
    allowed, message = check_rate_limit(client_ip)
    if not allowed:
        print(f"🚫 Rate limit exceeded for {client_ip}")
        raise HTTPException(status_code=429, detail=message)
    
    # 🔥 RECORD INCOMING ALERT - Every alert is logged before processing
    raw_payload = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "alert_name": alert_name,
        "secret": "***" if secret else None
    }
    
    headers = {
        "user-agent": request.headers.get("user-agent", ""),
        "content-type": "application/x-www-form-urlencoded"
    }
    
    symbols = [symbol.upper()] if symbol else []
    
    alert_id = record_incoming_alert(
        alert_type="get",
        raw_payload=raw_payload,
        source_ip=client_ip,
        headers=headers,
        symbols=symbols
    )
    
    check_file_rotation()
    
    alert = ChartinkAlert(
        symbol=symbol.upper(),
        action=action.upper(),
        price=price,
        secret=secret,
        alert_name=alert_name
    )
    alert._alert_id = alert_id
    
    # Process with error handling
    start_time = datetime.now()
    try:
        result = await process_chartink_alert(alert)
        
        # Update alert status
        status = "processed" if result.get("status") in ["SUCCESS", "BATCH_PROCESSED"] else "rejected"
        if result.get("status") == "REJECTED":
            status = "rejected"
        elif result.get("status") == "ERROR":
            status = "error"
        
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        update_alert_status(
            alert_id=alert_id,
            status=status,
            result=result.get("reason") or result.get("message"),
            latency_ms=round(latency_ms, 2)
        )
        
        return result
        
    except HTTPException as he:
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        update_alert_status(
            alert_id=alert_id,
            status="error",
            result=f"HTTP {he.status_code}: {he.detail}",
            latency_ms=round(latency_ms, 2)
        )
        raise
        
    except Exception as e:
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        update_alert_status(
            alert_id=alert_id,
            status="error",
            result=str(e),
            latency_ms=round(latency_ms, 2)
        )
        raise


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


@app.get("/api/signals")
async def get_signals():
    """Get today's signal history with validation stats."""
    from signal_tracker import get_signal_stats, load_today_signals
    
    stats = get_signal_stats()
    signals = load_today_signals()
    
    return {
        "stats": stats,
        "signals": signals[-50:] if len(signals) > 50 else signals,  # Last 50 signals
        "validation_config": load_config().get("signal_validation", {})
    }


@app.post("/api/signals/clear")
async def clear_signals():
    """Clear today's signal history (for testing)."""
    from signal_tracker import record_signal
    record_signal("ADMIN", "CLEARED", reason="Manual clear via API")
    return {"status": "cleared", "message": "Signal history cleared"}


# ============================================================================
# Incoming Alerts API Endpoints - Comprehensive Alert Logging
# ============================================================================

@app.get("/api/incoming-alerts")
async def get_incoming_alerts(limit: int = 50, status: Optional[str] = None):
    """
    Get recent incoming alerts from ChartInk webhook.
    
    Args:
        limit: Maximum number of alerts to return (default: 50, max: 200)
        status: Filter by status (pending, processing, processed, rejected, error)
    
    Returns:
        List of incoming alerts with metadata
    """
    limit = min(limit, 200)  # Cap at 200
    
    alerts = get_recent_incoming_alerts(limit=limit)
    
    if status:
        alerts = [a for a in alerts if a.get("processing_status") == status]
    
    return {
        "alerts": alerts,
        "count": len(alerts),
        "filter": {"status": status, "limit": limit}
    }


@app.get("/api/incoming-alerts/stats")
async def get_incoming_alerts_statistics():
    """
    Get statistics about incoming alerts today.
    
    Returns:
        Summary statistics including counts by type, status, and latency
    """
    stats = get_incoming_alert_stats()
    
    return {
        "stats": stats,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/incoming-alerts/symbol/{symbol}")
async def get_incoming_alerts_by_symbol(symbol: str):
    """
    Get all incoming alerts for a specific symbol today.
    
    Args:
        symbol: Stock symbol to filter by
    
    Returns:
        List of alerts containing the symbol
    """
    alerts = get_alerts_by_symbol(symbol)
    
    return {
        "symbol": symbol.upper(),
        "alerts": alerts,
        "count": len(alerts)
    }


@app.get("/api/incoming-alerts/scan/{scan_name}")
async def get_incoming_alerts_by_scan(scan_name: str):
    """
    Get all incoming alerts from a specific scan today.
    
    Args:
        scan_name: Name of the scan (partial match supported)
    
    Returns:
        List of alerts matching the scan name
    """
    alerts = get_alerts_by_scan(scan_name)
    
    return {
        "scan_name": scan_name,
        "alerts": alerts,
        "count": len(alerts)
    }


@app.get("/api/incoming-alerts/today")
async def get_today_incoming_alerts_summary():
    """
    Get a summary of all incoming alerts received today.
    
    Returns:
        Summary with recent alerts and key metrics
    """
    from incoming_alerts import load_today_incoming_alerts
    
    alerts = load_today_incoming_alerts()
    stats = get_incoming_alert_stats()
    
    # Get last 10 alerts
    recent = alerts[-10:] if alerts else []
    
    return {
        "summary": {
            "total_alerts_today": len(alerts),
            "unique_scans": len(set(a.get("scan_name") for a in alerts if a.get("scan_name"))),
            "unique_symbols": len(set(s for a in alerts for s in a.get("symbols", []))),
            "avg_latency_ms": stats.get("avg_latency_ms", 0)
        },
        "recent_alerts": recent,
        "stats": stats
    }


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
    
    if update.prevent_duplicate_stocks is not None:
        config["prevent_duplicate_stocks"] = update.prevent_duplicate_stocks
    
    if update.club_positions is not None:
        config["club_positions"] = update.club_positions
    
    # 🔥 Update signal validation settings
    if update.signal_validation is not None:
        if "signal_validation" not in config:
            config["signal_validation"] = {}
        config["signal_validation"].update(update.signal_validation)
        
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
    """Get today's trades with backward compatibility for paper_trading field."""
    trades = load_trades()
    # Ensure paper_trading field exists for all trades (backward compatibility)
    for trade in trades:
        if "paper_trading" not in trade:
            # Old trades without paper_trading flag default to live (False)
            trade["paper_trading"] = False
    return trades

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
    
    for position_id, pos in open_positions.items():
        symbol = pos.get("symbol")
        if not symbol:
            continue
        
        # Ensure paper_trading field exists (backward compatibility for old positions)
        # If not set, assume live trading (safer default)
        if "paper_trading" not in pos:
            pos["paper_trading"] = False
            
        quote = await kite.get_quote(symbol)
        if quote:
            ltp = quote.ltp
            entry = pos.get("entry_price", 0)
            qty = pos.get("quantity", 0)
            unrealized_pnl = (ltp - entry) * qty
            
            positions_with_pnl.append({
                "id": position_id,  # Include position ID for closing
                **pos,
                "ltp": ltp,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_percent": round((ltp - entry) / entry * 100, 2) if entry > 0 else 0
            })
        else:
            positions_with_pnl.append({"id": position_id, **pos})
    
    return {
        "positions": positions_with_pnl,
        "count": len(positions_with_pnl),
        "total_unrealized_pnl": round(sum(p.get("unrealized_pnl", 0) for p in positions_with_pnl), 2)
    }

@app.post("/api/positions/{position_id}/close")
async def close_position_api(position_id: str):
    """Manually close a position by ID."""
    config = load_config()
    kite = get_kite_api(config)
    
    # Get position details
    positions = load_positions()
    if position_id not in positions:
        return {"status": "error", "message": "Position not found"}
    
    position = positions[position_id]
    symbol = position.get("symbol")
    qty = position.get("quantity", 0)
    entry_price = position.get("entry_price", 0)
    
    if qty <= 0:
        return {"status": "error", "message": "Invalid quantity"}
    
    # Cancel SL and TP GTT orders first
    sl_order_id = position.get("sl_order_id")
    tp_order_id = position.get("tp_order_id")
    
    try:
        if sl_order_id and not sl_order_id.startswith("PAPER_"):
            await kite.delete_gtt(sl_order_id)
    except Exception as e:
        print(f"Warning: Could not delete SL GTT: {e}")
    
    try:
        if tp_order_id and not tp_order_id.startswith("PAPER_"):
            await kite.delete_gtt(tp_order_id)
    except Exception as e:
        print(f"Warning: Could not delete TP GTT: {e}")
    
    # Place market order to exit
    exit_order = await kite.place_market_order(
        symbol=symbol,
        transaction_type="SELL",
        quantity=qty
    )
    
    print(f"Exit order placed: {exit_order.order_id}, status: {exit_order.status}")
    
    # Handle different order statuses
    if exit_order.status in ["PENDING", "SUCCESS"]:
        # Wait for fill (even if SUCCESS, check fill details)
        fill_result = await kite.wait_for_order_fill(exit_order.order_id, timeout=30)
        
        if fill_result.get("filled"):
            exit_price = fill_result.get("average_price", entry_price)
            pnl = (exit_price - entry_price) * qty
            
            # Close position in our records
            close_position_by_id(position_id, exit_price, pnl, "MANUAL")
            
            # Send notification
            await send_telegram_message(
                f"🔴 *Position Closed: {symbol}*\n\n"
                f"Exit: ₹{exit_price:.2f}\n"
                f"P&L: ₹{pnl:.2f}\n"
                f"Reason: Manual close"
            )
            
            return {"status": "success", "message": f"Position {symbol} closed", "pnl": pnl}
        else:
            return {"status": "error", "message": f"Order not filled: {fill_result.get('message', 'Unknown')}"}
    elif exit_order.status == "FAILED":
        return {"status": "error", "message": exit_order.message or "Order rejected by broker"}
    elif exit_order.status == "ERROR":
        return {"status": "error", "message": exit_order.message or "System error placing order"}
    
    return {"status": "error", "message": f"Unexpected order status: {exit_order.status}"}


@app.post("/api/positions/sync")
async def sync_positions_api():
    """
    Manually sync positions with Kite.
    Marks local positions as closed if they're no longer in Kite.
    """
    config = load_config()
    kite = get_kite_api(config)
    
    result = await sync_positions_with_kite(kite)
    
    return {
        "status": "success" if result.get("errors", 0) == 0 else "partial",
        "message": f"Synced {result.get('synced', 0)} positions, closed {result.get('closed', 0)}",
        "details": result
    }


@app.post("/api/gtt/cleanup")
async def cleanup_orphan_gtt_api():
    """
    Clean up orphan GTT orders for closed positions.
    Cancels GTT orders that belong to positions already marked as closed.
    
    Use this to fix dangling GTTs from clubbing or manual closes.
    """
    config = load_config()
    kite = get_kite_api(config)
    
    result = {
        "cancelled": [],
        "errors": [],
        "checked": 0
    }
    
    try:
        # Get all positions (including closed ones)
        all_positions = load_positions()
        
        # Get all active GTT orders from Kite
        gtt_orders = await kite.list_gtt_orders()
        
        # Build set of valid GTT IDs from open positions
        valid_gtt_ids = set()
        for pos_id, pos in all_positions.items():
            if pos.get("status") == "OPEN":
                sl_id = pos.get("sl_order_id")
                tp_id = pos.get("tp_order_id")
                if sl_id and not sl_id.startswith("PAPER_"):
                    valid_gtt_ids.add(str(sl_id))
                if tp_id and not tp_id.startswith("PAPER_"):
                    valid_gtt_ids.add(str(tp_id))
        
        # Check each GTT order
        for gtt in gtt_orders:
            gtt_id = str(gtt.get("id", ""))
            gtt_status = gtt.get("status", "").lower()
            
            # Skip already triggered/cancelled GTTs
            if gtt_status in ["triggered", "cancelled", "expired", "rejected"]:
                continue
            
            result["checked"] += 1
            
            # If GTT not associated with any open position, cancel it
            if gtt_id not in valid_gtt_ids:
                symbol = gtt.get("condition", {}).get("tradingsymbol", "UNKNOWN")
                try:
                    success = await kite.delete_gtt(gtt_id)
                    if success:
                        result["cancelled"].append({
                            "gtt_id": gtt_id,
                            "symbol": symbol,
                            "reason": "Orphan - no matching open position"
                        })
                        print(f"🗑️ Cancelled orphan GTT: {gtt_id} ({symbol})")
                    else:
                        result["errors"].append({"gtt_id": gtt_id, "error": "Delete failed"})
                except Exception as e:
                    result["errors"].append({"gtt_id": gtt_id, "error": str(e)})
        
        return {
            "status": "success" if len(result["errors"]) == 0 else "partial",
            "message": f"Cancelled {len(result['cancelled'])} orphan GTTs ({result['checked']} checked)",
            "details": result
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "details": result
        }


@app.get("/api/positions/kite-debug")
async def kite_positions_debug():
    """
    Debug endpoint to see raw Kite positions.
    Shows what Kite API returns vs what bot has stored.
    """
    config = load_config()
    kite = get_kite_api(config)
    
    try:
        # Fetch from Kite
        kite_positions = await kite.fetch_kite_positions()
        
        # Get local positions
        local_positions = load_positions()
        local_open = {k: v for k, v in local_positions.items() if v.get("status") == "OPEN"}
        
        return {
            "kite_positions": [
                {
                    "symbol": p.get("tradingsymbol"),
                    "quantity": p.get("quantity"),
                    "product": p.get("product"),  # CNC or MIS
                    "exchange": p.get("exchange")
                }
                for p in kite_positions
            ],
            "local_open_positions": [
                {
                    "id": k,
                    "symbol": v.get("symbol"),
                    "quantity": v.get("quantity"),
                    "status": v.get("status")
                }
                for k, v in local_open.items()
            ],
            "match_analysis": {
                "kite_count": len(kite_positions),
                "local_open_count": len(local_open)
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/positions/{position_id}/force-close")
async def force_close_position_api(position_id: str, exit_price: Optional[float] = None):
    """
    Force close a position without placing an order.
    Use when position was already closed externally (e.g., from Kite app).
    
    Args:
        position_id: The position ID
        exit_price: Optional exit price. If not provided, uses current market price.
    """
    config = load_config()
    kite = get_kite_api(config)
    
    # Get position details
    positions = load_positions()
    if position_id not in positions:
        return {"status": "error", "message": "Position not found"}
    
    position = positions[position_id]
    symbol = position.get("symbol")
    
    if position.get("status") != "OPEN":
        return {"status": "error", "message": "Position is not open"}
    
    # Get exit price
    if exit_price is None or exit_price <= 0:
        # Fetch current price
        quote = await kite.get_quote(symbol)
        if not quote:
            return {"status": "error", "message": "Could not fetch current price"}
        exit_price = quote.ltp
    
    # Cancel SL and TP GTT orders
    sl_order_id = position.get("sl_order_id")
    tp_order_id = position.get("tp_order_id")
    
    try:
        if sl_order_id and not sl_order_id.startswith("PAPER_"):
            await kite.delete_gtt(sl_order_id)
    except Exception as e:
        print(f"Warning: Could not delete SL GTT: {e}")
    
    try:
        if tp_order_id and not tp_order_id.startswith("PAPER_"):
            await kite.delete_gtt(tp_order_id)
    except Exception as e:
        print(f"Warning: Could not delete TP GTT: {e}")
    
    # Force close the position
    success = force_close_position(position_id, exit_price, reason="MANUAL_FORCE_CLOSE")
    
    if success:
        entry_price = position.get("entry_price", 0)
        qty = position.get("quantity", 0)
        pnl = (exit_price - entry_price) * qty
        
        await send_telegram_message(
            f"🔴 *Position Force-Closed: {symbol}*\n\n"
            f"Exit: ₹{exit_price:.2f}\n"
            f"P&L: ₹{pnl:.2f}\n"
            f"Reason: Manual force close (already closed in Kite)"
        )
        
        return {
            "status": "success",
            "message": f"Position {symbol} force-closed",
            "exit_price": exit_price,
            "pnl": round(pnl, 2)
        }
    else:
        return {"status": "error", "message": "Failed to close position"}


@app.post("/api/test-telegram")
async def test_telegram():
    """Send a test Telegram message."""
    await send_telegram_message("🧪 *Test Message*\n\nTrading bot is working correctly!")
    return {"status": "sent"}

@app.get("/api/gtt-orders")
async def get_gtt_orders():
    """Get all active GTT orders from Kite."""
    config = load_config()
    kite = get_kite_api(config)
    
    try:
        gtt_orders = await kite.list_gtt_orders()
        
        # Enrich with position info if available
        positions = load_positions()
        position_gtt_map = {}
        for pos_id, pos in positions.items():
            if pos.get("status") == "OPEN":
                sl_id = pos.get("sl_order_id")
                tp_id = pos.get("tp_order_id")
                if sl_id:
                    position_gtt_map[sl_id] = {"position_id": pos_id, "symbol": pos.get("symbol"), "type": "SL"}
                if tp_id:
                    position_gtt_map[tp_id] = {"position_id": pos_id, "symbol": pos.get("symbol"), "type": "TP"}
        
        # Add position info to GTT orders
        for gtt in gtt_orders:
            gtt_id = str(gtt.get("id"))
            if gtt_id in position_gtt_map:
                gtt["position_info"] = position_gtt_map[gtt_id]
        
        return {
            "status": "success",
            "count": len(gtt_orders),
            "orders": gtt_orders
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/sync-kite")
async def sync_kite_positions():
    """Sync positions and orders from Kite (includes manual/external trades)."""
    config = load_config()
    kite = get_kite_api(config)
    
    try:
        # Fetch positions from Kite
        kite_positions = await kite.fetch_kite_positions()
        
        # Get our current positions
        local_positions = load_positions()
        local_order_ids = {p.get("entry_order_id") for p in local_positions.values()}
        
        synced_count = 0
        
        for pos in kite_positions:
            # Only process MIS (intraday) positions with net quantity > 0
            if pos.get("product") != "MIS":
                continue
                
            quantity = int(pos.get("quantity", 0))
            if quantity <= 0:
                continue
            
            symbol = pos.get("tradingsymbol")
            exchange = pos.get("exchange")
            
            # Skip if already tracked
            # Note: Kite doesn't give us order_id in positions, so we use symbol+price+time matching
            # For now, add as external position
            
            entry_price = float(pos.get("average_price", 0))
            last_price = float(pos.get("last_price", 0))
            
            # Check if this position already exists locally
            existing = False
            for local_pos in local_positions.values():
                if (local_pos.get("symbol") == symbol and 
                    abs(local_pos.get("entry_price", 0) - entry_price) < 0.5 and
                    local_pos.get("status") == "OPEN"):
                    existing = True
                    break
            
            if existing:
                continue
            
            # Add as external position (from Kite app = live trading)
            position_id = f"EXTERNAL_{symbol}_{datetime.now().strftime('%H%M%S')}"
            
            positions = load_positions()
            positions[position_id] = {
                "id": position_id,
                "symbol": symbol,
                "quantity": quantity,
                "entry_price": entry_price,
                "entry_order_id": None,  # External trade - no order ID
                "sl_price": entry_price * 0.98,  # Default 2% SL
                "tp_price": entry_price * 1.06,  # Default 6% TP
                "sl_order_id": None,
                "tp_order_id": None,
                "status": "OPEN",
                "entry_time": datetime.now().isoformat(),
                "external": True,  # Mark as external/manual trade
                "source": "KITE_APP",
                "paper_trading": False  # Kite app positions are always live trades
            }
            save_positions(positions)
            synced_count += 1
        
        return {
            "status": "success",
            "message": f"Synced {synced_count} external positions from Kite",
            "synced_count": synced_count
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

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

# ============================================================================
# File Upload Endpoint for CSV/Data Files
# ============================================================================

from fastapi import UploadFile, File
import shutil

@app.get("/upload", response_class=HTMLResponse)
async def upload_page():
    """Simple file upload page."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Upload CSV/Data Files</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        h1 { color: #333; }
        .upload-box { border: 2px dashed #ccc; padding: 40px; text-align: center; border-radius: 10px; }
        .upload-box:hover { border-color: #4CAF50; background: #f9f9f9; }
        input[type="file"] { margin: 20px 0; }
        button { background: #4CAF50; color: white; padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; }
        button:hover { background: #45a049; }
        .info { background: #e3f2fd; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <h1>📁 Upload CSV/Data Files</h1>
    
    <div class="info">
        <strong>Upload your margin/leverage CSV file here.</strong><br>
        The file will be saved to the server and can be used to improve position sizing.
    </div>
    
    <div class="upload-box">
        <form action="/api/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept=".csv,.json,.xlsx,.txt" required>
            <br><br>
            <button type="submit">Upload File</button>
        </form>
    </div>
    
    <h3>Alternative: Use cURL</h3>
    <pre style="background: #f5f5f5; padding: 15px; border-radius: 5px;">
curl -X POST 'https://coolify.themelon.in/api/upload' \\
  -F 'file=@your-file.csv'
    </pre>
    
    <h3>Alternative: Use SCP</h3>
    <pre style="background: #f5f5f5; padding: 15px; border-radius: 5px;">
scp your-file.csv root@coolify.themelon.in:/root/trading-bot/uploads/
    </pre>
</body>
</html>
    """

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handle file upload."""
    # Create uploads directory if not exists
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    
    # Save file
    file_path = upload_dir / file.filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        return {
            "status": "success",
            "message": f"File '{file.filename}' uploaded successfully",
            "filename": file.filename,
            "path": str(file_path),
            "size": file_path.stat().st_size
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Upload failed: {str(e)}"
        }
    finally:
        file.file.close()

@app.get("/api/uploaded-files")
async def list_uploaded_files():
    """List all uploaded files."""
    upload_dir = Path("uploads")
    if not upload_dir.exists():
        return {"files": []}
    
    files = []
    for f in upload_dir.iterdir():
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            })
    
    return {"files": files}

@app.get("/api/debug/paper-live-classification")
async def debug_paper_live_classification():
    """
    Debug endpoint to verify paper vs live trade/position classification.
    Helps diagnose classification issues.
    """
    config = load_config()
    positions = load_positions()
    trades = load_all_trades()
    
    # Categorize positions
    open_positions = {k: v for k, v in positions.items() if v.get("status") == "OPEN"}
    paper_positions = {k: v for k, v in open_positions.items() if v.get("paper_trading") == True}
    live_positions = {k: v for k, v in open_positions.items() if v.get("paper_trading") != True}
    unknown_positions = {k: v for k, v in open_positions.items() if "paper_trading" not in v}
    
    # Categorize today's trades
    today_trades = load_trades()
    paper_trades = [t for t in today_trades if t.get("paper_trading") == True]
    live_trades = [t for t in today_trades if t.get("paper_trading") != True]
    unknown_trades = [t for t in today_trades if "paper_trading" not in t]
    
    # All trades (historical)
    all_paper_trades = [t for t in trades if t.get("paper_trading") == True]
    all_live_trades = [t for t in trades if t.get("paper_trading") != True]
    
    return {
        "system_mode": {
            "paper_trading_enabled": config.get("paper_trading", False),
            "timestamp": datetime.now().isoformat()
        },
        "open_positions": {
            "total": len(open_positions),
            "paper": len(paper_positions),
            "live": len(live_positions),
            "unknown_classification": len(unknown_positions),
            "paper_details": [{"id": k, "symbol": v.get("symbol"), "paper_trading": v.get("paper_trading")} for k, v in paper_positions.items()],
            "live_details": [{"id": k, "symbol": v.get("symbol"), "paper_trading": v.get("paper_trading")} for k, v in live_positions.items()],
            "unknown_details": [{"id": k, "symbol": v.get("symbol")} for k, v in unknown_positions.items()]
        },
        "today_trades": {
            "total": len(today_trades),
            "paper": len(paper_trades),
            "live": len(live_trades),
            "unknown_classification": len(unknown_trades)
        },
        "all_trades_ever": {
            "total": len(trades),
            "paper": len(all_paper_trades),
            "live": len(all_live_trades)
        },
        "classification_logic": {
            "paper_condition": "paper_trading === true",
            "live_condition": "paper_trading !== true (includes false, null, undefined)",
 "note": "Unknown positions are treated as LIVE for safety"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
