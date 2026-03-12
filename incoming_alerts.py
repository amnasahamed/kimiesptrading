"""
Incoming Alerts Logger - Records ALL ChartInk Webhook Alerts
=============================================================
This module records every single incoming alert from ChartInk,
regardless of whether it's processed, rejected, or invalid.

Features:
- Records raw payload from every webhook call
- Stores IP address and headers for security audit
- Maintains timestamp for latency analysis
- Auto-rotation to prevent file bloat
- Query/filter capabilities for analysis

Use cases:
- Debug missing alerts
- Audit webhook delivery from ChartInk
- Analyze alert patterns
- Verify rate limiting effectiveness
"""

import json
import os
import platform
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict

# File to store all incoming alerts
INCOMING_ALERTS_FILE = Path("incoming_alerts.json")
MAX_ALERTS_PER_DAY = 1000  # Limit to prevent file bloat
MAX_FILE_SIZE_MB = 10  # Rotate if file exceeds this size

# Cross-platform file locking setup
if platform.system() == 'Windows':
    fcntl = None
    _file_locks = {}
    _file_locks_lock = threading.Lock()
else:
    import fcntl


def _get_file_lock(filepath: str):
    """Get or create a file lock for the given filepath (Windows fallback)."""
    if fcntl is not None:
        return None
    with _file_locks_lock:
        if filepath not in _file_locks:
            _file_locks[filepath] = threading.Lock()
        return _file_locks[filepath]


def _acquire_lock(f, exclusive: bool = False):
    """Acquire file lock (cross-platform)."""
    if fcntl is not None:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(f.fileno(), lock_type)


def _release_lock(f):
    """Release file lock (cross-platform)."""
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@dataclass
class IncomingAlert:
    """Represents a single incoming webhook alert."""
    id: str
    timestamp: str
    received_at: str  # ISO format with microseconds
    source_ip: str
    user_agent: Optional[str]
    content_type: Optional[str]
    
    # Alert data (from ChartInk)
    alert_type: str  # 'json', 'form', 'get'
    stocks: Optional[str]
    trigger_prices: Optional[str]
    triggered_at: Optional[str]
    scan_name: Optional[str]
    scan_url: Optional[str]
    alert_name: Optional[str]
    
    # Parsed symbols (if multiple)
    symbols: List[str]
    
    # Raw payload (for debugging)
    raw_payload: Dict[str, Any]
    
    # Processing status
    processing_status: str  # 'pending', 'processing', 'processed', 'rejected', 'error'
    processing_result: Optional[str] = None
    
    # Latency tracking (in milliseconds)
    processing_started_at: Optional[str] = None
    processing_completed_at: Optional[str] = None
    total_latency_ms: Optional[float] = None


def load_all_incoming_alerts() -> List[Dict[str, Any]]:
    """Load all incoming alerts from JSON file with cross-platform file locking."""
    if not INCOMING_ALERTS_FILE.exists():
        return []
    
    lock = _get_file_lock(str(INCOMING_ALERTS_FILE))
    if lock:
        lock.acquire()
    
    try:
        with open(INCOMING_ALERTS_FILE, "r") as f:
            _acquire_lock(f, exclusive=False)
            try:
                return json.load(f)
            finally:
                _release_lock(f)
    except json.JSONDecodeError:
        print("Incoming alerts file corrupted, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading incoming alerts: {e}")
        return []
    finally:
        if lock:
            lock.release()


def load_today_incoming_alerts() -> List[Dict[str, Any]]:
    """
    Load today's incoming alerts from JSON file.
    Resets at 8:00 AM daily - alerts before 8 AM are considered previous day.
    """
    all_alerts = load_all_incoming_alerts()
    
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    reset_time = datetime.strptime(f"{today_date} 08:00:00", "%Y-%m-%d %H:%M:%S")
    
    # If current time is before 8 AM, show yesterday's alerts after 8 AM
    if now < reset_time:
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_reset = datetime.strptime(f"{yesterday} 08:00:00", "%Y-%m-%d %H:%M:%S")
        return [a for a in all_alerts if a.get("received_at") and 
                yesterday_reset <= datetime.fromisoformat(a.get("received_at")) < reset_time]
    else:
        # Show today's alerts after 8 AM
        return [a for a in all_alerts if a.get("received_at") and 
                datetime.fromisoformat(a.get("received_at")) >= reset_time]


def save_incoming_alert(alert: Dict[str, Any]):
    """Save an incoming alert to the log file with cross-platform file locking."""
    lock = _get_file_lock(str(INCOMING_ALERTS_FILE))
    if lock:
        lock.acquire()
    
    try:
        alerts = load_all_incoming_alerts()
        alerts.append(alert)
        
        # Keep only last MAX_ALERTS_PER_DAY to prevent file bloat
        if len(alerts) > MAX_ALERTS_PER_DAY:
            alerts = alerts[-MAX_ALERTS_PER_DAY:]
        
        with open(INCOMING_ALERTS_FILE, "w") as f:
            _acquire_lock(f, exclusive=True)
            try:
                json.dump(alerts, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                _release_lock(f)
    except Exception as e:
        print(f"Error saving incoming alert: {e}")
        raise
    finally:
        if lock:
            lock.release()


def record_incoming_alert(
    alert_type: str,
    raw_payload: Dict[str, Any],
    source_ip: str,
    headers: Dict[str, str],
    symbols: List[str] = None
) -> str:
    """
    Record an incoming webhook alert immediately upon receipt.
    
    Args:
        alert_type: 'json', 'form', or 'get'
        raw_payload: The raw data received
        source_ip: Client IP address
        headers: Request headers
        symbols: Parsed list of symbols (if available)
    
    Returns:
        alert_id: Unique ID for this alert (can be used to update status later)
    """
    now = datetime.now()
    alert_id = f"ALT{now.strftime('%Y%m%d%H%M%S%f')[:-3]}"
    
    # Extract ChartInk specific fields if present
    stocks = raw_payload.get("stocks")
    trigger_prices = raw_payload.get("trigger_prices")
    triggered_at = raw_payload.get("triggered_at")
    scan_name = raw_payload.get("scan_name") or raw_payload.get("alert_name")
    scan_url = raw_payload.get("scan_url")
    alert_name = raw_payload.get("alert_name")
    
    # Parse symbols from stocks field if not provided
    if symbols is None and stocks:
        symbols = [s.strip().upper() for s in stocks.split(",") if s.strip()]
    symbols = symbols or []
    
    alert = IncomingAlert(
        id=alert_id,
        timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
        received_at=now.isoformat(),
        source_ip=source_ip,
        user_agent=headers.get("user-agent"),
        content_type=headers.get("content-type"),
        alert_type=alert_type,
        stocks=stocks,
        trigger_prices=trigger_prices,
        triggered_at=triggered_at,
        scan_name=scan_name,
        scan_url=scan_url,
        alert_name=alert_name,
        symbols=symbols,
        raw_payload=raw_payload,
        processing_status="pending"
    )
    
    save_incoming_alert(asdict(alert))
    print(f"📝 Incoming alert recorded: {alert_id} from {source_ip} - {len(symbols)} symbols")
    
    return alert_id


def update_alert_status(
    alert_id: str,
    status: str,
    result: Optional[str] = None,
    latency_ms: Optional[float] = None
):
    """
    Update the processing status of an alert.
    
    Args:
        alert_id: The alert ID returned by record_incoming_alert
        status: 'processing', 'processed', 'rejected', 'error'
        result: Optional result message
        latency_ms: Optional total processing latency
    """
    lock = _get_file_lock(str(INCOMING_ALERTS_FILE))
    if lock:
        lock.acquire()
    
    try:
        alerts = load_all_incoming_alerts()
        
        for alert in alerts:
            if alert.get("id") == alert_id:
                alert["processing_status"] = status
                if result:
                    alert["processing_result"] = result
                if latency_ms:
                    alert["total_latency_ms"] = latency_ms
                
                now = datetime.now().isoformat()
                if status == "processing":
                    alert["processing_started_at"] = now
                elif status in ("processed", "rejected", "error"):
                    alert["processing_completed_at"] = now
                
                with open(INCOMING_ALERTS_FILE, "w") as f:
                    _acquire_lock(f, exclusive=True)
                    try:
                        json.dump(alerts, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        _release_lock(f)
                
                print(f"📝 Alert {alert_id} status updated: {status}")
                return True
        
        return False
    except Exception as e:
        print(f"Error updating alert status: {e}")
        return False
    finally:
        if lock:
            lock.release()


def get_incoming_alert_stats() -> Dict[str, Any]:
    """Get statistics for today's incoming alerts."""
    alerts = load_today_incoming_alerts()
    
    if not alerts:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total": 0,
            "by_type": {},
            "by_status": {},
            "unique_sources": [],
            "avg_latency_ms": 0
        }
    
    # Count by type
    by_type = {}
    by_status = {}
    sources = set()
    latencies = []
    
    for alert in alerts:
        # By type
        alert_type = alert.get("alert_type", "unknown")
        by_type[alert_type] = by_type.get(alert_type, 0) + 1
        
        # By status
        status = alert.get("processing_status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        
        # Sources
        sources.add(alert.get("source_ip", "unknown"))
        
        # Latency
        latency = alert.get("total_latency_ms")
        if latency:
            latencies.append(latency)
    
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": len(alerts),
        "by_type": by_type,
        "by_status": by_status,
        "unique_sources": list(sources),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "max_latency_ms": round(max(latencies), 2) if latencies else 0
    }


def get_recent_incoming_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent incoming alerts (default: last 50)."""
    alerts = load_all_incoming_alerts()
    return alerts[-limit:] if alerts else []


def get_alerts_by_symbol(symbol: str) -> List[Dict[str, Any]]:
    """Get all alerts for a specific symbol today."""
    alerts = load_today_incoming_alerts()
    symbol = symbol.upper()
    
    return [
        a for a in alerts 
        if symbol in [s.upper() for s in a.get("symbols", [])]
    ]


def get_alerts_by_scan(scan_name: str) -> List[Dict[str, Any]]:
    """Get all alerts from a specific scan today."""
    alerts = load_today_incoming_alerts()
    
    return [
        a for a in alerts 
        if scan_name.lower() in (a.get("scan_name") or "").lower()
    ]


def clear_old_incoming_alerts(days: int = 7):
    """Clear alerts older than specified days to keep file size manageable."""
    lock = _get_file_lock(str(INCOMING_ALERTS_FILE))
    if lock:
        lock.acquire()
    
    try:
        alerts = load_all_incoming_alerts()
        cutoff = datetime.now() - timedelta(days=days)
        
        filtered = [a for a in alerts if 
                   a.get("received_at") and 
                   datetime.fromisoformat(a["received_at"]) > cutoff]
        
        with open(INCOMING_ALERTS_FILE, "w") as f:
            _acquire_lock(f, exclusive=True)
            try:
                json.dump(filtered, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                _release_lock(f)
        
        removed = len(alerts) - len(filtered)
        if removed > 0:
            print(f"🧹 Cleaned up {removed} old incoming alert records")
            
    except Exception as e:
        print(f"Error clearing old incoming alerts: {e}")
    finally:
        if lock:
            lock.release()


def check_file_rotation():
    """Check if file needs rotation based on size."""
    if not INCOMING_ALERTS_FILE.exists():
        return
    
    size_mb = INCOMING_ALERTS_FILE.stat().st_size / (1024 * 1024)
    
    if size_mb > MAX_FILE_SIZE_MB:
        # Rotate: keep only last 500 alerts
        alerts = load_all_incoming_alerts()
        if len(alerts) > 500:
            alerts = alerts[-500:]
            
            lock = _get_file_lock(str(INCOMING_ALERTS_FILE))
            if lock:
                lock.acquire()
            
            try:
                with open(INCOMING_ALERTS_FILE, "w") as f:
                    _acquire_lock(f, exclusive=True)
                    try:
                        json.dump(alerts, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        _release_lock(f)
                print(f"🔄 Rotated incoming alerts file (was {size_mb:.1f}MB)")
            finally:
                if lock:
                    lock.release()


def get_alerts_by_ip(source_ip: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Get alerts from a specific IP address."""
    alerts = load_all_incoming_alerts()
    
    matching = [a for a in alerts if a.get("source_ip") == source_ip]
    return matching[-limit:]


def export_alerts_to_csv(output_path: Optional[str] = None) -> str:
    """
    Export today's alerts to CSV format for analysis.
    
    Returns:
        Path to the CSV file
    """
    import csv
    
    alerts = load_today_incoming_alerts()
    
    if not output_path:
        output_path = f"alerts_export_{datetime.now().strftime('%Y%m%d')}.csv"
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'ID', 'Timestamp', 'Source IP', 'Type', 'Scan Name', 
            'Symbols', 'Stocks', 'Status', 'Latency (ms)'
        ])
        
        for alert in alerts:
            writer.writerow([
                alert.get('id'),
                alert.get('timestamp'),
                alert.get('source_ip'),
                alert.get('alert_type'),
                alert.get('scan_name'),
                ', '.join(alert.get('symbols', [])),
                alert.get('stocks'),
                alert.get('processing_status'),
                alert.get('total_latency_ms', '')
            ])
    
    print(f"📊 Exported {len(alerts)} alerts to {output_path}")
    return output_path
