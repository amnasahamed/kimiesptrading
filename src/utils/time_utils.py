"""
Central IST (Indian Standard Time, UTC+5:30) helpers.

Use these everywhere instead of datetime.now() or datetime.utcnow().
"""
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    """Return the current datetime in IST (timezone-aware)."""
    return datetime.now(tz=IST)


def ist_today_start() -> datetime:
    """Return midnight IST today (00:00:00 IST)."""
    now = ist_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def ist_naive() -> datetime:
    """Return current IST time as a naive datetime (for legacy DB columns)."""
    return ist_now().replace(tzinfo=None)
