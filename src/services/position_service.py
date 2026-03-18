"""
Position management service.

Handles GTT monitoring, Kite sync, force-close, position clubbing,
and ESP hardware display state.
"""
from datetime import datetime
from src.utils.time_utils import ist_naive
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from src.core.logging_config import get_logger
from src.models.database import get_db_session
from src.repositories.position_repository import PositionRepository, TradeRepository
from src.services.kite_service import KiteService, get_kite_service
from src.services.notification_service import send_telegram

logger = get_logger()

# ---------------------------------------------------------------------------
# ESP last-alert in-process state (not DB — single-process safe)
# ---------------------------------------------------------------------------
_esp_last_alert: Dict[str, Any] = {
    "symbol": "",
    "price": 0.0,
    "time": "",
    "shown": True,
}


def store_alert_for_esp(symbol: str, price: float) -> None:
    """Called by webhook when a signal arrives — updates ESP polling state."""
    global _esp_last_alert
    _esp_last_alert = {
        "symbol": symbol,
        "price": price,
        "time": ist_naive().strftime("%H:%M"),
        "shown": False,
    }


def get_esp_alert() -> Dict[str, Any]:
    """Return last alert for ESP polling. Marks as shown on first read."""
    global _esp_last_alert
    if not _esp_last_alert["shown"]:
        _esp_last_alert["shown"] = True
        return {
            "new_alert": True,
            "symbol": _esp_last_alert["symbol"],
            "price": _esp_last_alert["price"],
            "time": _esp_last_alert["time"],
        }
    return {"new_alert": False}


# ---------------------------------------------------------------------------
# Sync positions with Kite
# ---------------------------------------------------------------------------
async def sync_positions_with_kite(db: Session, kite: KiteService) -> Dict[str, Any]:
    """
    Compare local open positions against Kite's live positions.
    Marks local positions as closed when they're no longer in Kite.
    """
    result: Dict[str, Any] = {"synced": 0, "closed": 0, "errors": 0, "details": []}

    try:
        kite_positions = await kite.get_positions()

        # Build normalised symbol set from Kite (positive qty only)
        kite_symbols: Dict[str, str] = {}
        for pos in kite_positions:
            symbol = pos.get("tradingsymbol", "").upper()
            if int(pos.get("quantity", 0)) > 0:
                kite_symbols[symbol] = symbol
                base = symbol.split("-")[0]
                if base != symbol:
                    kite_symbols[base] = symbol

        result["synced"] = len(kite_symbols)

        position_repo = PositionRepository(db)
        open_positions = position_repo.get_open_positions(paper_trading=False)

        for pos in open_positions:
            symbol = (pos.symbol or "").upper()
            base = symbol.split("-")[0]
            if symbol and symbol not in kite_symbols and base not in kite_symbols:
                # Position no longer in Kite — mark closed
                try:
                    quote = await kite.get_quote(symbol)
                    exit_price = quote.ltp if quote else (pos.entry_price or 0)
                except Exception:
                    exit_price = pos.entry_price or 0

                qty = pos.quantity or 0
                pnl = round((exit_price - (pos.entry_price or 0)) * qty, 2)

                position_repo.close_position(pos.id, exit_price, pnl, "MANUAL_KITE")
                result["closed"] += 1
                result["details"].append({
                    "position_id": pos.id,
                    "symbol": symbol,
                    "action": "marked_closed",
                    "exit_price": exit_price,
                    "pnl": pnl,
                })
                logger.info(f"Sync: marked {symbol} closed (gone from Kite)")

        if result["closed"] > 0:
            symbols_closed = ", ".join(d["symbol"] for d in result["details"][:5])
            await send_telegram(
                f"🔄 *Position Sync*\n{result['closed']} position(s) closed from Kite:\n{symbols_closed}"
            )

        result["debug"] = {
            "kite_symbols": list(kite_symbols.keys()),
            "local_open_count": len(open_positions),
        }

    except Exception as exc:
        logger.error(f"sync_positions_with_kite error: {exc}")
        result["errors"] += 1
        result["details"].append({"error": str(exc)})

    return result


# ---------------------------------------------------------------------------
# Sync external Kite positions into local DB
# ---------------------------------------------------------------------------
async def sync_kite_positions(db: Session, kite: KiteService) -> Dict[str, Any]:
    """
    Import external positions from Kite (placed from the Kite app, not the bot).
    """
    position_repo = PositionRepository(db)
    open_positions = position_repo.get_open_positions()

    # Build set of locally tracked symbols
    local_symbols = {(p.symbol or "").upper() for p in open_positions}

    try:
        kite_positions = await kite.get_positions()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    synced_count = 0
    for pos in kite_positions:
        if pos.get("product") != "MIS":
            continue
        qty = int(pos.get("quantity", 0))
        if qty <= 0:
            continue

        symbol = pos.get("tradingsymbol", "").upper()
        if symbol in local_symbols:
            continue

        entry_price = float(pos.get("average_price", 0))
        position_id = f"EXTERNAL_{symbol}_{ist_naive().strftime('%H%M%S')}"

        position_repo.create({
            "id": position_id,
            "symbol": symbol,
            "quantity": qty,
            "entry_price": entry_price,
            "sl_price": round(entry_price * 0.98, 2),
            "tp_price": round(entry_price * 1.06, 2),
            "status": "OPEN",
            "paper_trading": False,
            "source": "KITE_APP",
            "entry_time": ist_naive(),
        })
        local_symbols.add(symbol)
        synced_count += 1

    return {
        "status": "success",
        "message": f"Synced {synced_count} external position(s) from Kite",
        "synced_count": synced_count,
    }


# ---------------------------------------------------------------------------
# Force close
# ---------------------------------------------------------------------------
async def force_close_position(
    db: Session, kite: KiteService, position_id: str, exit_price: Optional[float]
) -> Dict[str, Any]:
    """Close a position locally without placing an order (already closed in Kite)."""
    position_repo = PositionRepository(db)
    pos = position_repo.get_by_id(position_id)

    if not pos:
        return {"status": "error", "message": "Position not found"}
    if pos.status != "OPEN":
        return {"status": "error", "message": "Position is not open"}

    symbol = pos.symbol or ""

    # Resolve exit price
    if not exit_price or exit_price <= 0:
        try:
            quote = await kite.get_quote(symbol)
            exit_price = quote.ltp if quote else (pos.entry_price or 0)
        except Exception:
            exit_price = pos.entry_price or 0

    # Cancel GTT orders (live positions only)
    for gtt_id in filter(None, [pos.sl_order_id, pos.tp_order_id]):
        if not str(gtt_id).startswith("PAPER_"):
            try:
                await kite.delete_gtt(str(gtt_id))
            except Exception as e:
                logger.warning(f"Could not delete GTT {gtt_id}: {e}")

    qty = pos.quantity or 0
    pnl = round((exit_price - (pos.entry_price or 0)) * qty, 2)
    position_repo.close_position(position_id, exit_price, pnl, "MANUAL_FORCE_CLOSE")

    await send_telegram(
        f"🔴 *Force-Closed: {symbol}*\nExit: ₹{exit_price:.2f} | P&L: ₹{pnl:.2f}"
    )

    return {
        "status": "success",
        "message": f"{symbol} force-closed",
        "exit_price": exit_price,
        "pnl": pnl,
    }


# ---------------------------------------------------------------------------
# Modify stop-loss
# ---------------------------------------------------------------------------
async def modify_sl(
    db: Session, kite: KiteService, position_id: str, new_sl_price: float
) -> Dict[str, Any]:
    """Update stop-loss price; re-place GTT for live positions."""
    position_repo = PositionRepository(db)
    pos = position_repo.get_by_id(position_id)

    if not pos:
        return {"status": "error", "message": "Position not found"}
    if pos.status != "OPEN":
        return {"status": "error", "message": "Position is not open"}

    old_sl = pos.sl_price
    position_repo.update(position_id, {"sl_price": new_sl_price})

    # For live positions, cancel old GTT and place new one
    if not pos.paper_trading and pos.sl_order_id:
        try:
            await kite.delete_gtt(str(pos.sl_order_id))
        except Exception as e:
            logger.warning(f"Could not delete old SL GTT: {e}")

        new_gtt = await kite.place_sl_gtt(
            symbol=pos.symbol,
            quantity=pos.quantity or 1,
            trigger_price=new_sl_price,
            limit_price=round(new_sl_price * 0.995, 2),
        )
        if new_gtt:
            position_repo.update(position_id, {"sl_order_id": new_gtt["gtt_id"]})

    return {
        "status": "success",
        "message": f"SL updated from ₹{old_sl} to ₹{new_sl_price}",
        "position_id": position_id,
        "old_sl": old_sl,
        "new_sl": new_sl_price,
    }


# ---------------------------------------------------------------------------
# Kite debug
# ---------------------------------------------------------------------------
async def get_kite_debug(db: Session, kite: KiteService) -> Dict[str, Any]:
    """Compare raw Kite positions against local DB positions."""
    try:
        kite_positions = await kite.get_positions()
        position_repo = PositionRepository(db)
        local_open = position_repo.get_open_positions()

        return {
            "kite_positions": [
                {
                    "symbol": p.get("tradingsymbol"),
                    "quantity": p.get("quantity"),
                    "product": p.get("product"),
                    "exchange": p.get("exchange"),
                }
                for p in kite_positions
            ],
            "local_open_positions": [
                {"id": p.id, "symbol": p.symbol, "quantity": p.quantity, "status": p.status}
                for p in local_open
            ],
            "match_analysis": {
                "kite_count": len(kite_positions),
                "local_open_count": len(local_open),
            },
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# GTT orders
# ---------------------------------------------------------------------------
async def get_gtt_orders(db: Session, kite: KiteService) -> Dict[str, Any]:
    """List all GTT orders, enriched with local position info."""
    try:
        gtt_orders = await kite.list_gtt_orders()

        position_repo = PositionRepository(db)
        open_positions = position_repo.get_open_positions()

        # Map gtt_id -> position context
        gtt_map: Dict[str, Dict] = {}
        for pos in open_positions:
            for gtt_id, gtt_type in [(pos.sl_order_id, "SL"), (pos.tp_order_id, "TP")]:
                if gtt_id:
                    gtt_map[str(gtt_id)] = {
                        "position_id": pos.id,
                        "symbol": pos.symbol,
                        "type": gtt_type,
                    }

        for gtt in gtt_orders:
            gtt_id = str(gtt.get("id", ""))
            if gtt_id in gtt_map:
                gtt["position_info"] = gtt_map[gtt_id]

        return {"status": "success", "count": len(gtt_orders), "orders": gtt_orders}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def cleanup_orphan_gtt(db: Session, kite: KiteService) -> Dict[str, Any]:
    """Cancel GTT orders that have no matching open position."""
    result: Dict[str, Any] = {"cancelled": [], "errors": [], "checked": 0}

    try:
        gtt_orders = await kite.list_gtt_orders()
        position_repo = PositionRepository(db)
        open_positions = position_repo.get_open_positions()

        # Valid GTT IDs from open positions
        valid_gtt_ids = set()
        for pos in open_positions:
            for gtt_id in filter(None, [pos.sl_order_id, pos.tp_order_id]):
                if not str(gtt_id).startswith("PAPER_"):
                    valid_gtt_ids.add(str(gtt_id))

        for gtt in gtt_orders:
            gtt_id = str(gtt.get("id", ""))
            status = gtt.get("status", "").lower()
            if status in ("triggered", "cancelled", "expired", "rejected"):
                continue

            result["checked"] += 1
            if gtt_id not in valid_gtt_ids:
                symbol = gtt.get("condition", {}).get("tradingsymbol", "UNKNOWN")
                try:
                    if await kite.delete_gtt(gtt_id):
                        result["cancelled"].append({"gtt_id": gtt_id, "symbol": symbol})
                    else:
                        result["errors"].append({"gtt_id": gtt_id, "error": "delete failed"})
                except Exception as e:
                    result["errors"].append({"gtt_id": gtt_id, "error": str(e)})

    except Exception as exc:
        result["errors"].append({"error": str(exc)})

    return {
        "status": "success" if not result["errors"] else "partial",
        "message": f"Cancelled {len(result['cancelled'])} orphan GTT(s) ({result['checked']} checked)",
        "details": result,
    }


# ---------------------------------------------------------------------------
# ESP compact helpers
# ---------------------------------------------------------------------------
async def get_esp_stats(db: Session, config: dict) -> Dict[str, Any]:
    """Compact trading stats for ESP8266 display."""
    trade_repo = TradeRepository(db)
    position_repo = PositionRepository(db)

    today_trades = trade_repo.get_today_trades()
    open_positions = position_repo.get_open_positions()
    total_pnl = sum(t.pnl or 0 for t in today_trades if t.status == "CLOSED")

    from src.services.risk_service import get_risk_service
    rs = get_risk_service()
    in_window, _ = rs._is_in_trading_window(config)

    return {
        "system_enabled": config.get("system_enabled", False),
        "market_open": in_window,
        "paper_trading": config.get("paper_trading", True),
        "today_pnl": round(total_pnl, 2),
        "open_positions": len(open_positions),
        "today_trades": len(today_trades),
        "timestamp": ist_naive().isoformat(),
    }


async def get_esp_positions(db: Session, kite: KiteService) -> Dict[str, Any]:
    """Simplified positions list for ESP display."""
    position_repo = PositionRepository(db)
    open_positions = position_repo.get_open_positions()

    result = []
    for pos in open_positions:
        try:
            quote = await kite.get_quote(pos.symbol)
            ltp = quote.ltp if quote else (pos.entry_price or 0)
        except Exception:
            ltp = pos.entry_price or 0

        entry = pos.entry_price or 0
        qty = pos.quantity or 0
        pnl = round((ltp - entry) * qty, 2)
        result.append({
            "symbol": pos.symbol,
            "qty": qty,
            "entry": round(entry, 2),
            "ltp": round(ltp, 2),
            "sl": round(pos.sl_price or 0, 2),
            "tp": round(pos.tp_price or 0, 2),
            "pnl": pnl,
            "pnl_pct": round((ltp - entry) / entry * 100, 1) if entry > 0 else 0,
        })

    return {"positions": result, "count": len(result)}
