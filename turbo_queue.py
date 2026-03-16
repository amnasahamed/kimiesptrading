"""
Turbo Queue - Asynchronous Signal Processing
============================================

Manages signals that need multi-timeframe confirmation before execution.

Features:
- Non-blocking queue (webhook returns immediately)
- Background processing with asyncio
- Persistent queue (survives restarts)
- Configurable max monitoring duration
- Automatic cleanup of stale entries

Usage:
    from turbo_queue import add_to_turbo_queue, start_turbo_processor
    
    # On webhook
    await add_to_turbo_queue(signal)
    
    # On startup
    await start_turbo_processor()
"""

import json
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import threading

# Queue file for persistence
QUEUE_FILE = Path("turbo_queue.json")
PROCESSING_FILE = Path("turbo_processing.json")

# In-memory queue
_turbo_queue: List[Dict[str, Any]] = []
_processing: Dict[str, Dict[str, Any]] = {}  # symbol -> processing info
_queue_lock = asyncio.Lock()
_processor_task: Optional[asyncio.Task] = None
_stop_processor = False


@dataclass
class TurboSignal:
    """Signal waiting for turbo confirmation"""
    symbol: str
    direction: str  # BUY or SELL
    alert_price: Optional[float]
    scan_name: str
    action: str
    context: Optional[Dict[str, Any]]
    timestamp: str
    config: Dict[str, Any]


def _load_queue() -> List[Dict[str, Any]]:
    """Load queue from disk"""
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ TURBO: Error loading queue: {e}")
    return []


def _save_queue(queue: List[Dict[str, Any]]):
    """Save queue to disk"""
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2)
    except Exception as e:
        print(f"⚠️ TURBO: Error saving queue: {e}")


def _load_processing() -> Dict[str, Dict[str, Any]]:
    """Load processing state from disk"""
    if PROCESSING_FILE.exists():
        try:
            with open(PROCESSING_FILE, "r") as f:
                data = json.load(f)
                # Filter out entries older than 1 hour
                now = datetime.now()
                return {
                    k: v for k, v in data.items()
                    if now - datetime.fromisoformat(v.get("started_at", now.isoformat())) < timedelta(hours=1)
                }
        except Exception as e:
            print(f"⚠️ TURBO: Error loading processing state: {e}")
    return {}


def _save_processing(processing: Dict[str, Dict[str, Any]]):
    """Save processing state to disk"""
    try:
        with open(PROCESSING_FILE, "w") as f:
            json.dump(processing, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️ TURBO: Error saving processing state: {e}")


async def add_to_turbo_queue(
    symbol: str,
    direction: str,
    alert_price: Optional[float],
    scan_name: str,
    action: str,
    context: Optional[Dict[str, Any]],
    config: Dict[str, Any]
) -> str:
    """
    Add a signal to the turbo processing queue.
    
    Returns:
        queue_id: Unique ID for tracking
    """
    async with _queue_lock:
        queue_id = f"TURBO_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{symbol}"
        
        entry = {
            "id": queue_id,
            "symbol": symbol,
            "direction": direction,
            "alert_price": alert_price,
            "scan_name": scan_name,
            "action": action,
            "context": context,
            "timestamp": datetime.now().isoformat(),
            "status": "QUEUED",
            "config": {
                # Save only necessary config
                "capital": config.get("capital", 100000),
                "risk_percent": config.get("risk_percent", 1.0),
                "turbo_mode": config.get("turbo_mode", {}),
                "kite": config.get("kite", {}),
                "risk_management": config.get("risk_management", {})
            }
        }
        
        _turbo_queue.append(entry)
        _save_queue(_turbo_queue)
        
        print(f"📥 TURBO: Added {symbol} to queue (ID: {queue_id})")
        return queue_id


async def get_queue_status() -> Dict[str, Any]:
    """
    Get current queue status with detailed categorization for visualization.
    Loads from disk if in-memory queue is empty (e.g., before processor starts).
    """
    async with _queue_lock:
        now = datetime.now()
        
        # Load from disk if in-memory queue is empty
        global _turbo_queue
        if not _turbo_queue:
            _turbo_queue = _load_queue()
        
        # Categorize items
        queued_items = [e for e in _turbo_queue if e.get("status") == "QUEUED"]
        processing_items = []
        for symbol, proc_info in _processing.items():
            entry = proc_info.get("entry", {})
            started_at = datetime.fromisoformat(proc_info.get("started_at", now.isoformat()))
            elapsed = (now - started_at).total_seconds()
            processing_items.append({
                **entry,
                "elapsed_seconds": elapsed,
                "progress_percent": min(elapsed / 600 * 100, 100)  # Assuming 10 min max
            })
        
        trend_check_items = [e for e in _turbo_queue if e.get("status") == "TREND_CHECK"]
        monitoring_items = [e for e in _turbo_queue if e.get("status") == "MONITORING"]
        executing_items = [e for e in _turbo_queue if e.get("status") == "EXECUTING"]
        
        successful_items = [e for e in _turbo_queue if e.get("status") in ["EXECUTED", "FALLBACK_EXECUTED"]]
        failed_items = [e for e in _turbo_queue if e.get("status") in ["TREND_MISMATCH", "EXPIRED", "CANCELLED", "FAILED", "ERROR"]]
        
        # Calculate stats
        total = len(_turbo_queue)
        success_rate = (len(successful_items) / max(len(successful_items) + len(failed_items), 1)) * 100
        
        # Recent items (last 20) with formatted data
        recent_items = []
        for entry in _turbo_queue[-20:]:
            item = {
                "id": entry.get("id"),
                "symbol": entry.get("symbol"),
                "direction": entry.get("direction"),
                "status": entry.get("status"),
                "timestamp": entry.get("timestamp"),
                "alert_price": entry.get("alert_price"),
                "entry_price": entry.get("entry_price"),
                "elapsed_seconds": None,
                "trend_aligned": entry.get("trend_check", {}).get("aligned") if entry.get("trend_check") else None,
                "trend_confidence": entry.get("trend_check", {}).get("confidence") if entry.get("trend_check") else None,
            }
            
            # Calculate elapsed time for active items
            if entry.get("timestamp") and entry.get("status") in ["QUEUED", "PROCESSING", "MONITORING", "EXECUTING"]:
                try:
                    item_time = datetime.fromisoformat(entry.get("timestamp"))
                    item["elapsed_seconds"] = (now - item_time).total_seconds()
                except:
                    pass
            
            recent_items.append(item)
        
        return {
            "counts": {
                "queued": len(queued_items),
                "processing": len(_processing),
                "trend_check": len(trend_check_items),
                "monitoring": len(monitoring_items),
                "executing": len(executing_items),
                "successful": len(successful_items),
                "failed": len(failed_items),
                "total": total
            },
            "stats": {
                "success_rate": round(success_rate, 1),
                "active": len(_processing) + len(queued_items)
            },
            "active_signals": processing_items,
            "queued_signals": queued_items[:10],  # First 10 in queue
            "recent_items": recent_items,
            "all_items": _turbo_queue  # All items for detailed view
        }


async def cancel_turbo_signal(queue_id: str) -> bool:
    """Cancel a queued signal"""
    async with _queue_lock:
        for entry in _turbo_queue:
            if entry.get("id") == queue_id:
                entry["status"] = "CANCELLED"
                _save_queue(_turbo_queue)
                print(f"❌ TURBO: Cancelled {queue_id}")
                return True
        return False


async def _update_entry_status(entry: Dict[str, Any], status: str, extra: Optional[Dict] = None):
    """Update entry status and persist queue under lock."""
    async with _queue_lock:
        entry["status"] = status
        if extra:
            entry.update(extra)
        _save_queue(_turbo_queue)


async def _process_single_signal(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single signal through turbo analysis"""
    from turbo_analyzer import TurboAnalyzer
    from chartink_webhook import process_single_alert, load_config

    symbol = entry["symbol"]
    direction = entry["direction"]
    config = entry["config"]

    turbo_config = config.get("turbo_mode", {})
    max_duration = turbo_config.get("max_monitor_duration_seconds", 300)

    print(f"\n🚀 TURBO: Processing {symbol} {direction}")

    # Initialize analyzer
    analyzer = TurboAnalyzer(config)

    # Step 1: Check trend alignment
    print(f"📊 TURBO: Checking trend alignment for {symbol}...")
    await _update_entry_status(entry, "TREND_CHECK")
    
    trend = await analyzer.check_trend_alignment(symbol, direction)
    
    await _update_entry_status(entry, "TREND_CHECK", {
        "trend_check": {
            "aligned": trend.aligned,
            "confidence": trend.confidence,
            "reason": trend.reason,
            "details": trend.details,
            "checked_at": datetime.now().isoformat()
        }
    })

    # Check if trend alignment is required
    trend_alignment_required = turbo_config.get("trend_alignment_required", True)

    if not trend.aligned:
        if trend_alignment_required:
            await _update_entry_status(entry, "TREND_MISMATCH", {"result": {"reason": trend.reason}})
            print(f"❌ TURBO: Trend mismatch for {symbol} - {trend.reason}")
            return entry
        else:
            # Trend not aligned but not required - proceed with warning
            print(f"⚠️  TURBO: Trend mismatch for {symbol} ({trend.reason}), but continuing (trend_alignment_required=false)")
    else:
        print(f"✅ TURBO: Trend aligned ({trend.confidence:.0f}% confidence)")

    # Step 2: Monitor for entry (until 2:30 PM market close)
    monitor_until_close = turbo_config.get("monitor_until_market_close", True)
    if monitor_until_close:
        print(f"⏱️ TURBO: Monitoring {symbol} for optimal entry (until 2:30 PM market close)...")
    else:
        print(f"⏱️ TURBO: Monitoring {symbol} for optimal entry (max {max_duration}s)...")

    await _update_entry_status(entry, "MONITORING", {
        "monitoring_started_at": datetime.now().isoformat(),
        "monitor_until_market_close": monitor_until_close
    })

    entry_result = await analyzer.monitor_entry(
        symbol, direction,
        max_duration=max_duration if not monitor_until_close else None,
        monitor_until_market_close=monitor_until_close
    )

    await _update_entry_status(entry, entry["status"], {
        "entry_monitor": {
            "triggered": entry_result.triggered,
            "duration_seconds": entry_result.duration_seconds,
            "confidence": entry_result.confidence_score,
            "reason": entry_result.trigger_reason,
            "completed_at": datetime.now().isoformat()
        }
    })

    if entry_result.triggered:
        await _update_entry_status(entry, "EXECUTING", {"entry_price": entry_result.entry_price})
        print(f"🎯 TURBO: Entry triggered at ₹{entry_result.entry_price:.2f}")

        # Execute the trade
        try:
            result = await process_single_alert(
                symbol=symbol,
                price=entry_result.entry_price,
                scan_name=entry["scan_name"],
                action=entry["action"],
                context=entry.get("context"),
                config=config
            )

            final_status = "EXECUTED" if result.get("status") == "SUCCESS" else "FAILED"
            await _update_entry_status(entry, final_status, {"result": result})
            print(f"{'✅' if result.get('status') == 'SUCCESS' else '❌'} TURBO: Trade result - {result.get('message', result.get('status'))}")

        except Exception as e:
            await _update_entry_status(entry, "ERROR", {"result": {"error": str(e)}})
            print(f"❌ TURBO: Execution error - {e}")

    else:
        # Max duration reached without trigger
        # Option: Execute at market anyway (fallback)
        fallback = turbo_config.get("fallback_to_market", True)

        if fallback:
            print(f"⏰ TURBO: Max duration reached, executing at market (fallback)")
            await _update_entry_status(entry, "FALLBACK_EXECUTING")

            try:
                result = await process_single_alert(
                    symbol=symbol,
                    price=entry.get("alert_price"),
                    scan_name=entry["scan_name"],
                    action=entry["action"],
                    context=entry.get("context"),
                    config=config
                )

                final_status = "FALLBACK_EXECUTED" if result.get("status") == "SUCCESS" else "FAILED"
                await _update_entry_status(entry, final_status, {"result": result})

            except Exception as e:
                await _update_entry_status(entry, "FALLBACK_ERROR", {"result": {"error": str(e)}})
        else:
            await _update_entry_status(entry, "EXPIRED", {
                "result": {"reason": "Max duration reached without trigger, no fallback"}
            })
            print(f"⏰ TURBO: Expired without entry")

    return entry


async def _turbo_processor():
    """Background task that processes the turbo queue"""
    global _stop_processor
    
    print("🔄 TURBO: Queue processor started")
    
    while not _stop_processor:
        try:
            async with _queue_lock:
                # Find next queued item
                next_item = None
                for entry in _turbo_queue:
                    if entry.get("status") == "QUEUED" and entry["symbol"] not in _processing:
                        next_item = entry
                        break
                
                if next_item:
                    symbol = next_item["symbol"]
                    _processing[symbol] = {
                        "started_at": datetime.now().isoformat(),
                        "entry": next_item
                    }
                    _save_processing(_processing)
            
            if next_item:
                # Process outside lock
                symbol = next_item["symbol"]
                
                try:
                    await _process_single_signal(next_item)
                except Exception as e:
                    print(f"❌ TURBO: Error processing {symbol}: {e}")
                    next_item["status"] = "ERROR"
                    next_item["error"] = str(e)
                
                # Update processing state
                async with _queue_lock:
                    if symbol in _processing:
                        del _processing[symbol]
                    _save_queue(_turbo_queue)
                    _save_processing(_processing)
            else:
                # No items to process, wait
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"❌ TURBO: Processor error: {e}")
            await asyncio.sleep(5)
    
    print("🛑 TURBO: Queue processor stopped")


async def start_turbo_processor():
    """Start the background turbo processor"""
    global _processor_task, _turbo_queue, _processing, _stop_processor
    
    # Load existing state
    _turbo_queue = _load_queue()
    _processing = _load_processing()
    
    # Reset items that were mid-processing (they'll be reprocessed)
    # All transient states should be reset to QUEUED on restart
    stuck_states = {"PROCESSING", "TREND_CHECK", "MONITORING", "EXECUTING", "FALLBACK_EXECUTING"}
    for entry in _turbo_queue:
        if entry.get("status") in stuck_states:
            entry["status"] = "QUEUED"
    
    # Clear old completed items (>24 hours)
    now = datetime.now()
    _turbo_queue = [
        e for e in _turbo_queue
        if now - datetime.fromisoformat(e.get("timestamp", now.isoformat())) < timedelta(hours=24)
    ]
    
    _stop_processor = False
    _processor_task = asyncio.create_task(_turbo_processor())
    
    print(f"🚀 TURBO: Processor started with {len([e for e in _turbo_queue if e.get('status') == 'QUEUED'])} queued items")


async def stop_turbo_processor():
    """Stop the background turbo processor"""
    global _stop_processor, _processor_task
    
    _stop_processor = True
    if _processor_task:
        _processor_task.cancel()
        try:
            await _processor_task
        except asyncio.CancelledError:
            pass
    
    print("🛑 TURBO: Processor stopped")


# Cleanup old queue entries periodically
async def cleanup_turbo_queue(max_age_hours: int = 24):
    """Remove old completed entries from queue"""
    global _turbo_queue
    
    async with _queue_lock:
        now = datetime.now()
        original_count = len(_turbo_queue)
        
        _turbo_queue = [
            e for e in _turbo_queue
            if e.get("status") not in ["EXECUTED", "EXPIRED", "CANCELLED", "FAILED"]
            or now - datetime.fromisoformat(e.get("timestamp", now.isoformat())) < timedelta(hours=max_age_hours)
        ]
        
        removed = original_count - len(_turbo_queue)
        if removed > 0:
            _save_queue(_turbo_queue)
            print(f"🧹 TURBO: Cleaned up {removed} old entries")


if __name__ == "__main__":
    # Test the queue
    async def test():
        # Add test signal
        test_config = {
            "capital": 100000,
            "risk_percent": 1.0,
            "turbo_mode": {
                "max_monitor_duration_seconds": 60,
                "fallback_to_market": True
            }
        }
        
        queue_id = await add_to_turbo_queue(
            symbol="RELIANCE",
            direction="BUY",
            alert_price=2500.0,
            scan_name="Test Scan",
            action="BUY",
            context={},
            config=test_config
        )
        
        print(f"Added to queue: {queue_id}")
        
        # Check status
        status = await get_queue_status()
        print(f"Queue status: {status}")
    
    asyncio.run(test())
