"""
Turbo mode API routes.

GET  /api/turbo/status
POST /api/turbo/cleanup
"""
from datetime import datetime
from src.utils.time_utils import ist_naive

from fastapi import APIRouter, HTTPException

from src.services.turbo_service import get_queue_status, cleanup_turbo_queue

router = APIRouter(prefix="/api", tags=["turbo"])


@router.get("/turbo/status")
async def turbo_status():
    """Turbo queue status — signals awaiting multi-timeframe confirmation."""
    try:
        status = await get_queue_status()
        return {
            "status": "ok",
            "turbo_enabled": True,
            **status,
            "timestamp": ist_naive().isoformat(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "timestamp": ist_naive().isoformat(),
        }


@router.post("/turbo/cleanup")
async def turbo_cleanup():
    """Remove completed/expired turbo queue entries older than 24 h."""
    try:
        result = await cleanup_turbo_queue(max_age_hours=24)
        return {"status": "ok", "message": "Cleanup completed", "details": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
