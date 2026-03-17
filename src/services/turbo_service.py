"""
Turbo Service — absorbs turbo_queue.py, wraps turbo_analyzer.py.

Manages signals that need multi-timeframe confirmation before execution.
Queue state is persisted in the `turbo_queue` DB table instead of JSON files.
In-flight state (TREND_CHECK, MONITORING, EXECUTING) is reset to QUEUED on
startup — safe because the processor re-validates before executing.
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.logging_config import get_logger
from src.models.database import get_db_session, TurboQueueItem

logger = get_logger()

# ---------------------------------------------------------------------------
# Module-level processor state
# ---------------------------------------------------------------------------
_processor_task: Optional[asyncio.Task] = None
_stop_processor: bool = False
_queue_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_to_dict(item: TurboQueueItem) -> Dict[str, Any]:
    return {
        "id": item.id,
        "symbol": item.symbol,
        "scan_name": item.scan_name,
        "alert_price": item.alert_price,
        "status": item.status,
        "timestamp": item.created_at.isoformat() if item.created_at else None,
        "processed_at": item.processed_at.isoformat() if item.processed_at else None,
        "timeframes_confirmed": item.timeframes_confirmed or [],
        "timeframes_required": item.timeframes_required or [],
        "result": item.result,
        "extra": item.extra or {},
    }


def _load_queue_from_db() -> List[Dict[str, Any]]:
    db = get_db_session()
    try:
        items = db.query(TurboQueueItem).all()
        return [_db_to_dict(i) for i in items]
    finally:
        db.close()


def _save_entry_to_db(entry: Dict[str, Any]) -> None:
    db = get_db_session()
    try:
        item = db.query(TurboQueueItem).filter(TurboQueueItem.id == entry["id"]).first()
        if item:
            item.status = entry.get("status", item.status)
            item.result = entry.get("result")
            item.timeframes_confirmed = entry.get("timeframes_confirmed", [])
            if entry.get("status") in ("EXECUTED", "FALLBACK_EXECUTED", "FAILED", "EXPIRED",
                                       "CANCELLED", "TREND_MISMATCH", "ERROR"):
                item.processed_at = datetime.utcnow()
            extra = {k: v for k, v in entry.items()
                     if k not in ("id", "symbol", "scan_name", "alert_price", "status",
                                  "timestamp", "processed_at", "result", "timeframes_confirmed",
                                  "timeframes_required")}
            item.extra = extra
        else:
            new_item = TurboQueueItem(
                id=entry["id"],
                symbol=entry["symbol"],
                scan_name=entry.get("scan_name", ""),
                alert_price=entry.get("alert_price"),
                status=entry.get("status", "QUEUED"),
                timeframes_required=entry.get("timeframes_required", []),
                timeframes_confirmed=entry.get("timeframes_confirmed", []),
                result=entry.get("result"),
                extra={k: v for k, v in entry.items()
                       if k not in ("id", "symbol", "scan_name", "alert_price",
                                    "status", "result")},
            )
            db.add(new_item)
        db.commit()
    except Exception as exc:
        logger.error(f"turbo_service DB save error: {exc}")
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# In-memory queue (mirrors DB for fast access during processing)
# ---------------------------------------------------------------------------
_turbo_queue: List[Dict[str, Any]] = []
_processing: Dict[str, Dict[str, Any]] = {}  # symbol -> info


async def _update_entry_status(entry: Dict[str, Any], status: str, extra: Optional[Dict] = None) -> None:
    async with _queue_lock:
        entry["status"] = status
        if extra:
            entry.update(extra)
        _save_entry_to_db(entry)


# ---------------------------------------------------------------------------
# Public: add to queue
# ---------------------------------------------------------------------------

async def add_to_turbo_queue(
    symbol: str,
    direction: str,
    alert_price: Optional[float],
    scan_name: str,
    action: str,
    context: Optional[Dict[str, Any]],
    config: Dict[str, Any],
) -> str:
    """Add a signal to the turbo queue. Returns queue_id."""
    async with _queue_lock:
        queue_id = f"TURBO_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{symbol}"
        entry = {
            "id": queue_id,
            "symbol": symbol,
            "direction": direction,
            "alert_price": alert_price,
            "scan_name": scan_name,
            "action": action,
            "context": context or {},
            "timestamp": datetime.now().isoformat(),
            "status": "QUEUED",
            "config": {
                "capital": config.get("capital", 100000),
                "risk_percent": config.get("risk_percent", 1.0),
                "turbo_mode": config.get("turbo_mode", {}),
                "kite": config.get("kite", {}),
                "risk_management": config.get("risk_management", {}),
            },
        }
        _turbo_queue.append(entry)
        _save_entry_to_db(entry)
        logger.info(f"TURBO: queued {symbol} (id={queue_id})")
        return queue_id


# ---------------------------------------------------------------------------
# Public: queue status
# ---------------------------------------------------------------------------

async def get_queue_status() -> Dict[str, Any]:
    """Return current turbo queue status for the API."""
    async with _queue_lock:
        now = datetime.now()

        queued, processing, completed, expired = [], [], [], []
        for entry in _turbo_queue:
            status = entry.get("status", "")
            age = 0
            try:
                age = (now - datetime.fromisoformat(entry["timestamp"])).total_seconds()
            except Exception:
                pass

            item = {
                "id": entry["id"],
                "symbol": entry["symbol"],
                "scan_name": entry.get("scan_name", ""),
                "status": status,
                "age_seconds": round(age),
                "alert_price": entry.get("alert_price"),
            }

            if status == "QUEUED":
                queued.append(item)
            elif status in ("TREND_CHECK", "MONITORING", "EXECUTING", "FALLBACK_EXECUTING"):
                processing.append(item)
            elif status in ("EXECUTED", "FALLBACK_EXECUTED", "FAILED", "ERROR",
                            "TREND_MISMATCH", "CANCELLED"):
                completed.append(item)
            elif status == "EXPIRED":
                expired.append(item)

        return {
            "queue_size": len(queued),
            "processing_count": len(processing),
            "completed_today": len(completed),
            "expired_count": len(expired),
            "queued": queued,
            "processing": processing,
            "recent_completed": completed[-10:],
        }


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------

async def _process_single_signal(entry: Dict[str, Any]) -> None:
    """Run one signal through TurboAnalyzer and then execute via trading_service."""
    symbol = entry["symbol"]
    direction = entry.get("direction", "BUY")
    config = entry.get("config", {})
    turbo_cfg = config.get("turbo_mode", {})
    max_duration = turbo_cfg.get("max_monitor_duration_seconds", 300)

    logger.info(f"TURBO: processing {symbol} {direction}")

    # Import TurboAnalyzer from root (wrap — don't absorb 850-line file)
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from turbo_analyzer import TurboAnalyzer
    except ImportError:
        logger.error("TURBO: turbo_analyzer.py not found — skipping turbo analysis, executing direct")
        await _execute_entry(entry, entry.get("alert_price"), config)
        return

    analyzer = TurboAnalyzer(config)

    # Step 1: trend alignment
    await _update_entry_status(entry, "TREND_CHECK")
    try:
        trend = await analyzer.check_trend_alignment(symbol, direction)
    except Exception as exc:
        logger.error(f"TURBO: trend check error for {symbol}: {exc}")
        await _update_entry_status(entry, "ERROR", {"result": {"error": str(exc)}})
        return

    await _update_entry_status(entry, "TREND_CHECK", {
        "trend_check": {
            "aligned": trend.aligned,
            "confidence": trend.confidence,
            "reason": trend.reason,
            "checked_at": datetime.now().isoformat(),
        }
    })

    trend_required = turbo_cfg.get("trend_alignment_required", True)
    if not trend.aligned and trend_required:
        await _update_entry_status(entry, "TREND_MISMATCH", {"result": {"reason": trend.reason}})
        logger.info(f"TURBO: trend mismatch for {symbol} — {trend.reason}")
        return

    # Step 2: monitor for entry
    monitor_until_close = turbo_cfg.get("monitor_until_market_close", True)
    await _update_entry_status(entry, "MONITORING", {
        "monitoring_started_at": datetime.now().isoformat(),
    })

    try:
        entry_result = await analyzer.monitor_entry(
            symbol,
            direction,
            max_duration=max_duration if not monitor_until_close else None,
            monitor_until_market_close=monitor_until_close,
        )
    except Exception as exc:
        logger.error(f"TURBO: monitor_entry error for {symbol}: {exc}")
        await _update_entry_status(entry, "ERROR", {"result": {"error": str(exc)}})
        return

    if entry_result.triggered:
        await _update_entry_status(entry, "EXECUTING", {"entry_price": entry_result.entry_price})
        await _execute_entry(entry, entry_result.entry_price, config, status_on_success="EXECUTED")
    else:
        if turbo_cfg.get("fallback_to_market", True):
            await _update_entry_status(entry, "FALLBACK_EXECUTING")
            await _execute_entry(entry, entry.get("alert_price"), config, status_on_success="FALLBACK_EXECUTED")
        else:
            await _update_entry_status(entry, "EXPIRED", {
                "result": {"reason": "Max duration reached without trigger"}
            })


async def _execute_entry(
    entry: Dict[str, Any],
    price: Optional[float],
    config: Dict[str, Any],
    status_on_success: str = "EXECUTED",
) -> None:
    """Call trading_service.process_signal and update entry status."""
    from src.services.trading_service import get_trading_service

    symbol = entry["symbol"]
    try:
        svc = get_trading_service()
        result = await svc.process_signal(
            symbol=symbol,
            alert_price=price,
            scan_name=entry.get("scan_name", "turbo"),
            action=entry.get("action", "BUY"),
            config=config,
        )
        final = status_on_success if result.get("status") == "SUCCESS" else "FAILED"
        await _update_entry_status(entry, final, {"result": result})
        logger.info(f"TURBO: {symbol} → {final}")
    except Exception as exc:
        await _update_entry_status(entry, "ERROR", {"result": {"error": str(exc)}})
        logger.error(f"TURBO: execution error for {symbol}: {exc}")


# ---------------------------------------------------------------------------
# Background processor
# ---------------------------------------------------------------------------

async def _turbo_processor() -> None:
    global _stop_processor
    logger.info("TURBO: processor started")

    while not _stop_processor:
        try:
            next_item = None
            async with _queue_lock:
                for entry in _turbo_queue:
                    if entry.get("status") == "QUEUED" and entry["symbol"] not in _processing:
                        next_item = entry
                        break
                if next_item:
                    _processing[next_item["symbol"]] = {"started_at": datetime.now().isoformat()}

            if next_item:
                symbol = next_item["symbol"]
                try:
                    await _process_single_signal(next_item)
                except Exception as exc:
                    logger.error(f"TURBO: processor error for {symbol}: {exc}")
                    next_item["status"] = "ERROR"
                    _save_entry_to_db(next_item)
                finally:
                    async with _queue_lock:
                        _processing.pop(symbol, None)
            else:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"TURBO: processor loop error: {exc}")
            await asyncio.sleep(5)

    logger.info("TURBO: processor stopped")


async def start_turbo_processor() -> None:
    """Load queue from DB, reset stuck entries, start background task."""
    global _processor_task, _turbo_queue, _processing, _stop_processor

    _turbo_queue = _load_queue_from_db()

    # Reset transient states — safe because we re-validate before executing
    stuck = {"TREND_CHECK", "MONITORING", "EXECUTING", "FALLBACK_EXECUTING"}
    for entry in _turbo_queue:
        if entry.get("status") in stuck:
            entry["status"] = "QUEUED"
            _save_entry_to_db(entry)

    # Drop completed entries older than 24 h from memory (keep in DB)
    cutoff = datetime.now() - timedelta(hours=24)
    terminal = {"EXECUTED", "FALLBACK_EXECUTED", "FAILED", "EXPIRED", "CANCELLED",
                "TREND_MISMATCH", "ERROR"}
    _turbo_queue = [
        e for e in _turbo_queue
        if e.get("status") not in terminal
        or datetime.fromisoformat(e["timestamp"]) > cutoff
    ]

    _stop_processor = False
    _processor_task = asyncio.create_task(_turbo_processor())
    queued_count = sum(1 for e in _turbo_queue if e.get("status") == "QUEUED")
    logger.info(f"TURBO: started with {queued_count} queued item(s)")


async def stop_turbo_processor() -> None:
    """Cancel the background processor task."""
    global _stop_processor, _processor_task
    _stop_processor = True
    if _processor_task:
        _processor_task.cancel()
        try:
            await _processor_task
        except asyncio.CancelledError:
            pass
    logger.info("TURBO: processor stopped")


async def cleanup_turbo_queue(max_age_hours: int = 24) -> Dict[str, Any]:
    """Remove old terminal entries from memory and DB."""
    global _turbo_queue

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    terminal = {"EXECUTED", "FALLBACK_EXECUTED", "FAILED", "EXPIRED", "CANCELLED",
                "TREND_MISMATCH", "ERROR"}

    async with _queue_lock:
        original = len(_turbo_queue)
        _turbo_queue = [
            e for e in _turbo_queue
            if e.get("status") not in terminal
            or datetime.fromisoformat(e.get("timestamp", datetime.now().isoformat())) > cutoff
        ]
        removed = original - len(_turbo_queue)

        # Also prune DB rows
        db = get_db_session()
        try:
            deleted = (
                db.query(TurboQueueItem)
                .filter(
                    TurboQueueItem.status.in_(list(terminal)),
                    TurboQueueItem.created_at < cutoff,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        except Exception as exc:
            logger.error(f"TURBO cleanup DB error: {exc}")
            db.rollback()
            deleted = 0
        finally:
            db.close()

    logger.info(f"TURBO: cleanup removed {removed} in-memory + {deleted} DB entries")
    return {"removed_memory": removed, "removed_db": deleted}
