"""
Signal Tracker - Daily Signal History for Duplicate Detection
=============================================================
Tracks all signals received from Chartink to prevent duplicate entries
on the same day. Resets daily at 8:00 AM.
"""

import json
import fcntl
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

SIGNALS_FILE = Path("signals_log.json")


def load_all_signals() -> List[Dict[str, Any]]:
    """Load all signals from JSON file with file locking."""
    if not SIGNALS_FILE.exists():
        return []
    
    try:
        with open(SIGNALS_FILE, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError:
        print("Signals file corrupted, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading signals: {e}")
        return []


def load_today_signals() -> List[Dict[str, Any]]:
    """
    Load today's signals from JSON file.
    Resets at 8:00 AM daily - signals before 8 AM are considered previous day.
    """
    all_signals = load_all_signals()
    
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    reset_time = datetime.strptime(f"{today_date} 08:00:00", "%Y-%m-%d %H:%M:%S")
    
    # If current time is before 8 AM, show yesterday's signals after 8 AM
    if now < reset_time:
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_reset = datetime.strptime(f"{yesterday} 08:00:00", "%Y-%m-%d %H:%M:%S")
        return [s for s in all_signals if s.get("timestamp") and 
                yesterday_reset <= datetime.fromisoformat(s.get("timestamp")) < reset_time]
    else:
        # Show today's signals after 8 AM
        return [s for s in all_signals if s.get("timestamp") and 
                datetime.fromisoformat(s.get("timestamp")) >= reset_time]


def save_signal_record(signal: Dict[str, Any]):
    """Save a signal record to the log file with file locking."""
    try:
        signals = load_all_signals()
        signals.append(signal)
        
        with open(SIGNALS_FILE, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(signals, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Error saving signal: {e}")
        raise


def record_signal(symbol: str, status: str, reason: str = None, metadata: Dict[str, Any] = None):
    """
    Record a signal for daily tracking.
    
    Args:
        symbol: Stock symbol
        status: EXECUTING, EXECUTED, REJECTED, FAILED
        reason: Rejection/failure reason (optional)
        metadata: Additional data (optional)
    """
    signal = {
        "id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}",
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol.upper(),
        "status": status,
        "reason": reason,
        "metadata": metadata or {}
    }
    
    save_signal_record(signal)
    
    # Log to console
    if reason:
        print(f"📝 Signal recorded: {symbol} -> {status} ({reason})")
    else:
        print(f"📝 Signal recorded: {symbol} -> {status}")


def is_duplicate_signal(symbol: str) -> bool:
    """
    Check if a signal for this symbol already exists today.
    Returns True if duplicate found.
    """
    if not symbol:
        return False
    
    symbol = symbol.upper()
    today_signals = load_today_signals()
    
    for signal in today_signals:
        if signal.get("symbol") == symbol:
            return True
    
    return False


def get_signal_stats() -> Dict[str, Any]:
    """Get statistics for today's signals."""
    signals = load_today_signals()
    
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": len(signals),
        "executing": len([s for s in signals if s["status"] == "EXECUTING"]),
        "executed": len([s for s in signals if s["status"] == "EXECUTED"]),
        "rejected": len([s for s in signals if s["status"] == "REJECTED"]),
        "failed": len([s for s in signals if s["status"] == "FAILED"]),
        "symbols": list(set(s["symbol"] for s in signals))
    }


def clear_old_signals(days: int = 7):
    """Clear signals older than specified days to keep file size manageable."""
    try:
        signals = load_all_signals()
        cutoff = datetime.now() - timedelta(days=days)
        
        filtered = [s for s in signals if 
                   s.get("timestamp") and 
                   datetime.fromisoformat(s["timestamp"]) > cutoff]
        
        with open(SIGNALS_FILE, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(filtered, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        
        removed = len(signals) - len(filtered)
        if removed > 0:
            print(f"🧹 Cleaned up {removed} old signal records")
            
    except Exception as e:
        print(f"Error clearing old signals: {e}")
