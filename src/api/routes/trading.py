"""
Trading API routes.
"""
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.models.database import get_db, get_db_session
from src.repositories.position_repository import PositionRepository, TradeRepository
from src.repositories.signal_repository import get_stats as signal_stats, get_today_signals
from src.services.kite_service import get_kite_service
from src.services.trading_service import get_trading_service

router = APIRouter(prefix="/api", tags=["trading"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class TradeRequest(BaseModel):
    symbol: str
    action: str = "BUY"
    quantity: Optional[int] = None
    price: Optional[float] = None


class ClosePositionRequest(BaseModel):
    exit_price: Optional[float] = None


# ---------------------------------------------------------------------------
# Existing routes (verified)
# ---------------------------------------------------------------------------
@router.post("/trade")
async def execute_trade(request: TradeRequest, db: Session = Depends(get_db)):
    """Execute a trade."""
    service = get_trading_service()
    result = await service.process_signal(
        symbol=request.symbol,
        alert_price=request.price,
        scan_name="Manual",
        action=request.action,
    )
    if result["status"] == "ERROR":
        raise HTTPException(status_code=500, detail=result.get("reason", "Error"))
    if result["status"] == "REJECTED":
        raise HTTPException(status_code=400, detail=result.get("reason", "Rejected"))
    return result


@router.post("/positions/{position_id}/close")
async def close_position(
    position_id: str,
    request: ClosePositionRequest,
    db: Session = Depends(get_db),
):
    """Close a position."""
    service = get_trading_service()
    result = await service.close_position(
        position_id=position_id, exit_price=request.exit_price
    )
    if result["status"] == "ERROR":
        raise HTTPException(status_code=400, detail=result.get("reason", "Error"))
    return result


@router.get("/portfolio")
async def get_portfolio(db: Session = Depends(get_db)):
    """Get portfolio summary."""
    service = get_trading_service()
    return await service.get_portfolio_summary()


@router.get("/kite/funds")
async def get_kite_funds():
    """Get Kite account funds."""
    kite = get_kite_service()
    result = await kite.get_funds()
    return {
        "status": "success" if result else "error",
        "funds": result,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a symbol."""
    kite = get_kite_service()
    quote = await kite.get_quote(symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not available")
    return {
        "symbol": quote.symbol,
        "ltp": quote.ltp,
        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "change_percent": quote.change_percent,
    }


# ---------------------------------------------------------------------------
# New routes added in Phase 2
# ---------------------------------------------------------------------------
@router.get("/trades")
async def get_trades():
    """Get today's trades."""
    db = get_db_session()
    try:
        trade_repo = TradeRepository(db)
        trades = trade_repo.get_today_trades()
        result = []
        for t in trades:
            result.append({
                "id": t.id,
                "date": t.date.isoformat() if t.date else None,
                "symbol": t.symbol,
                "action": t.action,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "stop_loss": t.stop_loss,
                "target": t.target,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "status": t.status,
                "paper_trading": t.paper_trading,
                "alert_name": t.alert_name,
                "scan_name": t.scan_name,
                "order_id": t.order_id,
            })
        return result
    finally:
        db.close()


@router.get("/positions")
async def get_positions():
    """Get current open positions with live P&L."""
    db = get_db_session()
    try:
        position_repo = PositionRepository(db)
        open_positions = position_repo.get_open_positions()
        if not open_positions:
            return {"positions": [], "count": 0, "total_unrealized_pnl": 0}

        kite = get_kite_service()

        # Fetch all quotes in parallel instead of one-by-one
        quotes = await asyncio.gather(*[kite.get_quote(pos.symbol) for pos in open_positions])

        positions_with_pnl = []
        for pos, quote in zip(open_positions, quotes):
            pos_dict = {
                "id": pos.id,
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "sl_price": pos.sl_price,
                "tp_price": pos.tp_price,
                "status": pos.status,
                "paper_trading": pos.paper_trading,
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "pnl": pos.pnl or 0,
                "source": pos.source,
            }
            if quote:
                ltp = quote.ltp
                unrealized_pnl = round((ltp - pos.entry_price) * pos.quantity, 2)
                pos_dict.update({
                    "ltp": ltp,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_percent": round((ltp - pos.entry_price) / pos.entry_price * 100, 2)
                    if pos.entry_price > 0
                    else 0,
                })
            positions_with_pnl.append(pos_dict)

        total_pnl = round(sum(p.get("unrealized_pnl", 0) for p in positions_with_pnl), 2)
        return {
            "positions": positions_with_pnl,
            "count": len(positions_with_pnl),
            "total_unrealized_pnl": total_pnl,
        }
    finally:
        db.close()


@router.get("/signals")
async def get_signals():
    """Get today's signal history and stats."""
    db = get_db_session()
    try:
        stats = await signal_stats(db)
        signals = await get_today_signals(db)
        sig_list = [
            {
                "id": s.id,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "symbol": s.symbol,
                "status": s.status,
                "reason": s.reason,
                "paper_trading": s.paper_trading,
            }
            for s in signals[:50]
        ]
        from src.api.routes.config import load_config
        return {
            "stats": stats,
            "signals": sig_list,
            "validation_config": load_config().get("signal_validation", {}),
        }
    finally:
        db.close()


@router.post("/signals/clear")
async def clear_signals():
    """Clear today's signal history (for testing)."""
    db = get_db_session()
    try:
        from src.models.database import Signal
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        deleted = db.query(Signal).filter(Signal.timestamp >= today).delete()
        db.commit()
        return {"status": "cleared", "message": f"{deleted} signals cleared"}
    finally:
        db.close()


@router.get("/dashboard")
async def get_dashboard():
    """Single endpoint that returns everything the dashboard needs on load.

    Replaces the 3 separate calls to /api/config, /api/stats, and /api/trades
    with one round trip, cutting initial load time significantly.
    """
    from src.api.routes.config import load_config
    from src.repositories.alert_repository import get_stats as alert_stats
    db = get_db_session()
    try:
        trade_repo = TradeRepository(db)
        today_trades = trade_repo.get_today_trades()
        stats = trade_repo.get_trade_stats(days=30)
        config = load_config()

        rs = __import__('src.services.risk_service', fromlist=['get_risk_service']).get_risk_service()
        within_hours, _ = rs._is_in_trading_window(config)

        paper_trades = [t for t in today_trades if t.paper_trading]
        live_trades  = [t for t in today_trades if not t.paper_trading]

        trades_list = [
            {
                "id": t.id,
                "date": t.date.isoformat() if t.date else None,
                "symbol": t.symbol,
                "action": t.action,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "stop_loss": t.stop_loss,
                "target": t.target,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "status": t.status,
                "paper_trading": t.paper_trading,
                "alert_name": t.alert_name,
                "scan_name": t.scan_name,
                "order_id": t.order_id,
            }
            for t in today_trades
        ]

        alert_s = await alert_stats(db)

        return {
            "config": config,
            "stats": {
                "system_enabled": config.get("system_enabled", False),
                "within_trading_hours": within_hours,
                "today_trades": len(today_trades),
                "today_pnl": sum(t.pnl or 0 for t in today_trades if t.status == "CLOSED"),
                "max_trades": config.get("max_trades_per_day", 10),
                "winning_trades": stats.get("winners", 0),
                "losing_trades": stats.get("losers", 0),
                "capital": config.get("capital", 0),
                "risk_percent": config.get("risk_percent", 0),
                "total_trades": len(today_trades),
                "paper_trades_today": len(paper_trades),
                "live_trades_today": len(live_trades),
            },
            "trades": trades_list,
            "alerts_stats": alert_s,
        }
    finally:
        db.close()


@router.get("/stats")
async def get_stats():
    """Get trading statistics."""
    db = get_db_session()
    try:
        trade_repo = TradeRepository(db)
        today_trades = trade_repo.get_today_trades()
        stats = trade_repo.get_trade_stats(days=30)

        from src.api.routes.config import load_config
        from src.services.risk_service import get_risk_service
        config = load_config()

        def _is_within_hours():
            from src.services.risk_service import get_risk_service
            rs = get_risk_service()
            ok, _ = rs._is_in_trading_window(config)
            return ok

        paper_trades = [t for t in today_trades if t.paper_trading]
        live_trades = [t for t in today_trades if not t.paper_trading]

        return {
            "system_enabled": config.get("system_enabled", False),
            "within_trading_hours": _is_within_hours(),
            "today_trades": len(today_trades),
            "today_pnl": sum(t.pnl or 0 for t in today_trades if t.status == "CLOSED"),
            "max_trades": config.get("max_trades_per_day", 10),
            "winning_trades": stats.get("winners", 0),
            "losing_trades": stats.get("losers", 0),
            "capital": config.get("capital", 0),
            "risk_percent": config.get("risk_percent", 0),
            "total_trades": len(today_trades),
            "paper_trades_today": len(paper_trades),
            "live_trades_today": len(live_trades),
        }
    finally:
        db.close()


@router.post("/reset-daily")
async def reset_daily():
    """Reset dashboard for next trading day."""
    db = get_db_session()
    try:
        position_repo = PositionRepository(db)
        trade_repo = TradeRepository(db)

        # Archive open positions as DAILY_RESET
        open_positions = position_repo.get_open_positions()
        closed_count = 0
        for pos in open_positions:
            position_repo.close_position(pos.id, pos.entry_price, 0.0, "DAILY_RESET")
            closed_count += 1

        # Count today's trades before reset
        today_trades = trade_repo.get_today_trades()

        return {
            "status": "reset",
            "message": f"Day reset complete. Archived {closed_count} positions.",
            "details": {
                "closed_positions": closed_count,
                "trades_today": len(today_trades),
                "insights_preserved": True,
            },
            "reset_time": datetime.now().isoformat(),
        }
    finally:
        db.close()


@router.post("/test-telegram")
async def test_telegram():
    """Send a test Telegram notification."""
    from src.services.notification_service import send_telegram
    ok = await send_telegram("🤖 Test notification from Melon Trading Bot")
    return {"status": "sent" if ok else "failed"}


@router.post("/test-whatsapp")
async def test_whatsapp():
    """Send a test WhatsApp notification."""
    from src.services.notification_service import send_whatsapp
    ok = await send_whatsapp("🤖 Test notification from Melon Trading Bot")
    return {"status": "sent" if ok else "failed"}


@router.get("/debug/paper-live-classification")
async def debug_classification():
    """Debug paper vs live position classification."""
    db = get_db_session()
    try:
        position_repo = PositionRepository(db)
        trade_repo = TradeRepository(db)

        open_positions = position_repo.get_open_positions()
        paper = [p for p in open_positions if p.paper_trading]
        live = [p for p in open_positions if not p.paper_trading]
        today_trades = trade_repo.get_today_trades()

        from src.api.routes.config import load_config
        config = load_config()

        return {
            "system_mode": {
                "paper_trading_enabled": config.get("paper_trading", False),
                "timestamp": datetime.now().isoformat(),
            },
            "open_positions": {
                "total": len(open_positions),
                "paper": len(paper),
                "live": len(live),
                "paper_details": [{"id": p.id, "symbol": p.symbol} for p in paper],
                "live_details": [{"id": p.id, "symbol": p.symbol} for p in live],
            },
            "today_trades": {
                "total": len(today_trades),
                "paper": sum(1 for t in today_trades if t.paper_trading),
                "live": sum(1 for t in today_trades if not t.paper_trading),
            },
        }
    finally:
        db.close()


@router.get("/analysis/paper-uptrend")
async def analyze_paper_uptrend():
    """Analyze max uptrend reached after paper trade entry."""
    db = get_db_session()
    try:
        position_repo = PositionRepository(db)
        kite = get_kite_service()

        from src.models.database import Position
        closed_paper = (
            db.query(Position)
            .filter(Position.status == "CLOSED", Position.paper_trading == True)
            .limit(50)
            .all()
        )

        analysis = []
        for pos in closed_paper:
            if not pos.entry_price or not pos.exit_price:
                continue
            max_uptrend_pct = ((pos.tp_price - pos.entry_price) / pos.entry_price * 100
                               if pos.tp_price and pos.entry_price else 0)
            actual_pnl_pct = ((pos.exit_price - pos.entry_price) / pos.entry_price * 100
                              if pos.entry_price else 0)
            analysis.append({
                "symbol": pos.symbol,
                "entry": pos.entry_price,
                "exit": pos.exit_price,
                "target": pos.tp_price,
                "exit_reason": pos.exit_reason,
                "max_uptrend_pct": round(max_uptrend_pct, 2),
                "actual_pnl_pct": round(actual_pnl_pct, 2),
            })

        avg_uptrend = (sum(a["max_uptrend_pct"] for a in analysis) / len(analysis)
                       if analysis else 0)
        avg_actual = (sum(a["actual_pnl_pct"] for a in analysis) / len(analysis)
                      if analysis else 0)

        return {
            "analysis": analysis,
            "summary": {
                "total_trades": len(analysis),
                "avg_max_uptrend_pct": round(avg_uptrend, 2),
                "avg_actual_pnl_pct": round(avg_actual, 2),
            },
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Phase 3 routes — Position management
# ---------------------------------------------------------------------------
from src.services.position_service import (
    sync_positions_with_kite,
    sync_kite_positions,
    force_close_position as svc_force_close,
    modify_sl,
    get_kite_debug,
    get_gtt_orders,
    cleanup_orphan_gtt,
    get_esp_stats,
    get_esp_positions,
    get_esp_alert,
)


class ModifySLRequest(BaseModel):
    new_sl_price: float


class ForceCloseRequest(BaseModel):
    exit_price: Optional[float] = None


@router.post("/positions/sync")
async def sync_positions_api():
    """Sync local positions against Kite — marks closed if gone from Kite."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        result = await sync_positions_with_kite(db, kite)
        return {
            "status": "success" if result.get("errors", 0) == 0 else "partial",
            "message": f"Synced {result.get('synced', 0)} positions, closed {result.get('closed', 0)}",
            "details": result,
        }
    finally:
        db.close()


@router.post("/positions/{position_id}/force-close")
async def force_close_position_api(position_id: str, request: ForceCloseRequest = ForceCloseRequest()):
    """Force-close a position without placing an order (already closed externally)."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await svc_force_close(db, kite, position_id, request.exit_price)
    finally:
        db.close()


@router.post("/positions/{position_id}/modify-sl")
async def modify_sl_api(position_id: str, request: ModifySLRequest):
    """Update the stop-loss price; re-places GTT for live positions."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await modify_sl(db, kite, position_id, request.new_sl_price)
    finally:
        db.close()


@router.get("/positions/kite-debug")
async def kite_positions_debug():
    """Debug: compare raw Kite positions vs local DB."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await get_kite_debug(db, kite)
    finally:
        db.close()


@router.get("/gtt-orders")
async def get_gtt_orders_api():
    """List all GTT orders from Kite, enriched with position info."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await get_gtt_orders(db, kite)
    finally:
        db.close()


@router.post("/gtt/cleanup")
async def cleanup_gtt_api():
    """Cancel orphan GTT orders (no matching open position)."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await cleanup_orphan_gtt(db, kite)
    finally:
        db.close()


@router.post("/sync-kite")
async def sync_kite_api():
    """Import external positions from Kite (placed via Kite app, not bot)."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await sync_kite_positions(db, kite)
    finally:
        db.close()


@router.get("/esp/stats")
async def esp_stats():
    """Compact stats for ESP8266 display."""
    from src.api.routes.config import load_config
    db = get_db_session()
    try:
        config = load_config()
        return await get_esp_stats(db, config)
    finally:
        db.close()


@router.get("/esp/positions")
async def esp_positions():
    """Simplified position list for ESP display."""
    kite = get_kite_service()
    db = get_db_session()
    try:
        return await get_esp_positions(db, kite)
    finally:
        db.close()


@router.get("/esp/alert")
async def esp_alert():
    """Latest webhook alert for ESP polling (mark-as-shown on read)."""
    return get_esp_alert()
