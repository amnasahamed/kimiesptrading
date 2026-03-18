"""
Signal repository — absorbs signal_tracker.py.
Tracks per-day signals for duplicate detection and analytics.
"""
from datetime import datetime, timedelta
from src.utils.time_utils import ist_naive
from typing import Optional

from sqlalchemy.orm import Session

from src.models.database import Signal
from src.core.logging_config import get_logger

logger = get_logger()

# Daily reset happens at 08:00 IST (signals before 8 AM belong to previous day)
_RESET_HOUR = 8


def _day_start() -> datetime:
    """Return the 8 AM boundary for today's signal window."""
    now = ist_naive()
    today_reset = now.replace(hour=_RESET_HOUR, minute=0, second=0, microsecond=0)
    if now < today_reset:
        # Before 8 AM — use yesterday's 8 AM as the start
        return today_reset - timedelta(days=1)
    return today_reset


async def record_signal(
    db: Session,
    symbol: str,
    scan_name: str,
    signal_type: str,
    reason: Optional[str] = None,
    paper_trading: bool = False,
    metadata: Optional[dict] = None,
) -> Signal:
    """Record a signal event."""
    sig = Signal(
        symbol=symbol.upper(),
        status=signal_type,
        reason=reason,
        signal_metadata={"scan_name": scan_name, **(metadata or {})},
        paper_trading=paper_trading,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    logger.debug(f"Signal recorded: {symbol} → {signal_type}")
    return sig


async def is_duplicate(
    db: Session,
    symbol: str,
    scan_name: str,
    within_minutes: int = 5,
) -> bool:
    """
    Return True if an EXECUTING/EXECUTED signal for (symbol, scan_name)
    already exists within the past `within_minutes` minutes today.
    """
    cutoff = max(
        _day_start(),
        ist_naive() - timedelta(minutes=within_minutes),
    )
    existing = (
        db.query(Signal)
        .filter(
            Signal.symbol == symbol.upper(),
            Signal.status.in_(["EXECUTING", "EXECUTED"]),
            Signal.timestamp >= cutoff,
        )
        .first()
    )
    return existing is not None


async def get_today_signals(db: Session) -> list[Signal]:
    """Return all signals since today's 8 AM reset."""
    return (
        db.query(Signal)
        .filter(Signal.timestamp >= _day_start())
        .order_by(Signal.timestamp.desc())
        .all()
    )


async def get_stats(db: Session) -> dict:
    """Return statistics for today's signals."""
    signals = await get_today_signals(db)
    return {
        "date": ist_naive().strftime("%Y-%m-%d"),
        "total": len(signals),
        "executing": sum(1 for s in signals if s.status == "EXECUTING"),
        "executed": sum(1 for s in signals if s.status == "EXECUTED"),
        "rejected": sum(1 for s in signals if s.status == "REJECTED"),
        "failed": sum(1 for s in signals if s.status == "FAILED"),
        "symbols": list({s.symbol for s in signals}),
    }
