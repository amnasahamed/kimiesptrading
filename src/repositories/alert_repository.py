"""
Alert repository — absorbs incoming_alerts.py.
Records every incoming webhook alert for audit and analytics.
"""
from datetime import datetime, timedelta
from src.utils.time_utils import ist_naive
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.models.database import IncomingAlert
from src.core.logging_config import get_logger

logger = get_logger()

_RESET_HOUR = 8


def _day_start() -> datetime:
    now = ist_naive()
    today_reset = now.replace(hour=_RESET_HOUR, minute=0, second=0, microsecond=0)
    if now < today_reset:
        return today_reset - timedelta(days=1)
    return today_reset


async def record_alert(
    db: Session,
    alert_type: str,
    raw_payload: dict,
    source_ip: str,
    headers: dict,
    symbols: Optional[list] = None,
) -> IncomingAlert:
    """Record an incoming webhook alert and return the created record."""
    now = ist_naive()
    alert_id = f"ALT{now.strftime('%Y%m%d%H%M%S%f')[:-3]}"

    if symbols is None:
        stocks_str = raw_payload.get("stocks", "")
        if stocks_str:
            symbols = [s.strip().upper() for s in stocks_str.split(",") if s.strip()]
        else:
            sym = raw_payload.get("symbol")
            symbols = [sym.upper()] if sym else []

    alert = IncomingAlert(
        id=alert_id,
        received_at=now,
        alert_type=alert_type,
        symbols=symbols or [],
        raw_payload=raw_payload,
        source_ip=source_ip,
        headers=headers,
        processing_status="pending",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    logger.debug(f"Alert recorded: {alert_id} from {source_ip} ({len(symbols or [])} symbols)")
    return alert


async def update_status(
    db: Session,
    alert_id: str,
    status: str,
    result: Optional[str] = None,
    latency_ms: Optional[float] = None,
) -> None:
    """Update processing status of an alert."""
    alert = db.query(IncomingAlert).filter_by(id=alert_id).first()
    if not alert:
        return
    alert.processing_status = status
    if result is not None:
        alert.processing_result = result
    if latency_ms is not None:
        alert.latency_ms = latency_ms
    db.commit()


async def get_recent(db: Session, limit: int = 100) -> list[IncomingAlert]:
    """Return the most recent alerts."""
    return (
        db.query(IncomingAlert)
        .order_by(desc(IncomingAlert.received_at))
        .limit(limit)
        .all()
    )


async def get_stats(db: Session) -> dict:
    """Return statistics for today's alerts."""
    alerts = await get_today(db)
    by_type: dict = {}
    by_status: dict = {}
    sources: set = set()
    latencies: list = []

    for a in alerts:
        by_type[a.alert_type or "unknown"] = by_type.get(a.alert_type or "unknown", 0) + 1
        by_status[a.processing_status] = by_status.get(a.processing_status, 0) + 1
        if a.source_ip:
            sources.add(a.source_ip)
        if a.latency_ms:
            latencies.append(a.latency_ms)

    return {
        "date": ist_naive().strftime("%Y-%m-%d"),
        "total": len(alerts),
        "by_type": by_type,
        "by_status": by_status,
        "unique_sources": list(sources),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "max_latency_ms": round(max(latencies), 2) if latencies else 0,
    }


async def get_by_symbol(db: Session, symbol: str) -> list[IncomingAlert]:
    """Return today's alerts that contain the given symbol."""
    sym = symbol.upper()
    today_alerts = await get_today(db)
    return [a for a in today_alerts if sym in (a.symbols or [])]


async def get_by_scan(db: Session, scan_name: str) -> list[IncomingAlert]:
    """Return today's alerts from the given scan (partial match)."""
    today_alerts = await get_today(db)
    name_lower = scan_name.lower()
    results = []
    for a in today_alerts:
        rp = a.raw_payload or {}
        sn = (rp.get("scan_name") or rp.get("alert_name") or "").lower()
        if name_lower in sn:
            results.append(a)
    return results


async def get_today(db: Session) -> list[IncomingAlert]:
    """Return all alerts since today's 8 AM reset."""
    return (
        db.query(IncomingAlert)
        .filter(IncomingAlert.received_at >= _day_start())
        .order_by(desc(IncomingAlert.received_at))
        .all()
    )
