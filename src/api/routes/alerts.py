"""
Incoming alerts API routes.

GET /api/incoming-alerts
GET /api/incoming-alerts/stats
GET /api/incoming-alerts/symbol/{symbol}
GET /api/incoming-alerts/scan/{scan_name}
GET /api/incoming-alerts/today
"""
from datetime import datetime
from src.utils.time_utils import ist_naive
from typing import Optional

from fastapi import APIRouter

from src.models.database import get_db_session
from src.repositories.alert_repository import (
    get_recent,
    get_stats,
    get_by_symbol,
    get_by_scan,
    get_today,
)

router = APIRouter(prefix="/api", tags=["alerts"])


def _alert_dict(alert) -> dict:
    return {
        "id": alert.id,
        "timestamp": alert.received_at.isoformat() if alert.received_at else None,
        "alert_type": alert.alert_type,
        "source_ip": alert.source_ip,
        "symbols": alert.symbols,
        "scan_name": (alert.raw_payload or {}).get("scan_name") if alert.raw_payload else None,
        "processing_status": alert.processing_status,
        "result_summary": alert.processing_result,
        "latency_ms": alert.latency_ms,
    }


@router.get("/incoming-alerts")
async def incoming_alerts(limit: int = 50, status: Optional[str] = None):
    """Recent incoming alerts, optionally filtered by processing status."""
    limit = min(limit, 200)
    db = get_db_session()
    try:
        alerts = await get_recent(db, limit=limit)
        if status:
            alerts = [a for a in alerts if a.processing_status == status]
        data = [_alert_dict(a) for a in alerts]
        return {"alerts": data, "count": len(data), "filter": {"status": status, "limit": limit}}
    finally:
        db.close()


@router.get("/incoming-alerts/stats")
async def incoming_alerts_stats():
    """Aggregate statistics for today's incoming alerts."""
    db = get_db_session()
    try:
        stats = await get_stats(db)
        return {"stats": stats, "timestamp": ist_naive().isoformat()}
    finally:
        db.close()


@router.get("/incoming-alerts/symbol/{symbol}")
async def incoming_alerts_by_symbol(symbol: str):
    """All alerts containing a specific symbol (today)."""
    db = get_db_session()
    try:
        alerts = await get_by_symbol(db, symbol.upper())
        data = [_alert_dict(a) for a in alerts]
        return {"symbol": symbol.upper(), "alerts": data, "count": len(data)}
    finally:
        db.close()


@router.get("/incoming-alerts/scan/{scan_name}")
async def incoming_alerts_by_scan(scan_name: str):
    """All alerts from a specific scan (today)."""
    db = get_db_session()
    try:
        alerts = await get_by_scan(db, scan_name)
        data = [_alert_dict(a) for a in alerts]
        return {"scan_name": scan_name, "alerts": data, "count": len(data)}
    finally:
        db.close()


@router.get("/incoming-alerts/today")
async def incoming_alerts_today():
    """Summary of all incoming alerts received today."""
    db = get_db_session()
    try:
        alerts = await get_today(db)
        stats = await get_stats(db)
        recent = [_alert_dict(a) for a in alerts[-10:]]
        unique_scans = len({(a.raw_payload or {}).get("scan_name") for a in alerts if a.raw_payload and a.raw_payload.get("scan_name")})
        unique_symbols = len({s for a in alerts for s in (a.symbols or [])})
        return {
            "summary": {
                "total_alerts_today": len(alerts),
                "unique_scans": unique_scans,
                "unique_symbols": unique_symbols,
                "avg_latency_ms": stats.get("avg_latency_ms", 0),
            },
            "recent_alerts": recent,
            "stats": stats,
        }
    finally:
        db.close()
