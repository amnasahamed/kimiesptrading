"""
Trading Bot Application — src/ entry point.
"""
import asyncio
import os
import sys
from datetime import time as dt_time
from threading import Thread
from src.utils.time_utils import ist_naive

# Add project root to path so `src.*` imports resolve from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import get_settings
from src.core.logging_config import setup_logging, get_logger
from src.models.database import init_db
from src.api.routes import trading
from src.api.routes import config as config_routes
from src.api.routes import ui as ui_routes
from src.api.routes import webhook as webhook_routes
from src.api.routes import analytics as analytics_routes
from src.api.routes import alerts as alerts_routes
from src.api.routes import turbo as turbo_routes

logger = setup_logging()


# ---------------------------------------------------------------------------
# Auto Square-Off Background Task
# ---------------------------------------------------------------------------
_square_off_done_today = False

async def _auto_square_off():
    """Close all open positions at end of market hours."""
    global _square_off_done_today
    
    from src.api.routes.config import load_config
    from src.models.database import get_db_session
    from src.repositories.position_repository import PositionRepository
    
    config = load_config()
    if not config.get("auto_square_off", False):
        return
    
    now = ist_naive()
    square_off_time = dt_time(15, 20)  # 3:20 PM
    
    # Reset flag at start of new day
    if now.time() < dt_time(9, 0):
        _square_off_done_today = False
    
    # Only run once per day, between 3:20 and 3:30 PM
    if not _square_off_done_today and dt_time(15, 20) <= now.time() <= dt_time(15, 30):
        logger.info("🔴 Auto square-off triggered")
        
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            
            # Get all open positions
            paper_positions = position_repo.get_open_positions(paper_trading=True)
            live_positions = position_repo.get_open_positions(paper_trading=False)
            
            all_positions = paper_positions + live_positions
            
            if all_positions:
                logger.info(f"Auto square-off: closing {len(all_positions)} positions")
                
                from src.services.kite_service import get_kite_service
                from src.services.notification_service import send_telegram
                kite = get_kite_service()
                
                total_pnl = 0
                for pos in all_positions:
                    try:
                        # Get current price
                        quote = await kite.get_quote(pos.symbol)
                        exit_price = quote.ltp if quote else pos.entry_price

                        # Determine position side
                        side = getattr(pos, "side", None) or "BUY"
                        is_long = side.upper() == "BUY"

                        # Calculate P&L — LONG: (exit - entry) * qty, SHORT: (entry - exit) * qty
                        if is_long:
                            pnl = (exit_price - pos.entry_price) * pos.quantity
                        else:
                            pnl = (pos.entry_price - exit_price) * pos.quantity
                        total_pnl += pnl

                        # Close position
                        position_repo.close_position(
                            pos.id,
                            exit_price,
                            pnl,
                            "AUTO_SQUARE_OFF"
                        )

                        # Place closing order for live positions (opposite of entry side)
                        if not pos.paper_trading:
                            close_transaction = "SELL" if is_long else "BUY"
                            await kite.place_order(
                                symbol=pos.symbol,
                                transaction_type=close_transaction,
                                quantity=pos.quantity
                            )
                        
                        logger.info(f"  Closed {pos.symbol}: P&L ₹{pnl:.2f}")
                    except Exception as e:
                        logger.error(f"  Error closing {pos.symbol}: {e}")
                
                _square_off_done_today = True
                
                await send_telegram(
                    f"🔴 *Auto Square-Off Complete*\n"
                    f"Positions closed: {len(all_positions)}\n"
                    f"Total P&L: ₹{total_pnl:.2f}"
                )
            else:
                logger.info("Auto square-off: no open positions")
                _square_off_done_today = True
                
        except Exception as e:
            logger.error(f"Auto square-off error: {e}")
        finally:
            db.close()


async def _run_background_tasks(app: FastAPI):
    """Background task runner for periodic operations."""
    while True:
        try:
            await _auto_square_off()
        except Exception as e:
            logger.error(f"Background task error: {e}")
        
        await asyncio.sleep(60)  # Check every minute


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    logger.info("=" * 50)
    logger.info("Trading Bot Starting")
    logger.info("=" * 50)

    init_db()
    logger.info("Database initialized")

    from src.services.turbo_service import start_turbo_processor, stop_turbo_processor
    await start_turbo_processor()
    logger.info("Turbo processor started")

    # Start background tasks (auto square-off)
    background_task = asyncio.create_task(_run_background_tasks(app))
    logger.info("Background tasks started")

    yield

    # Cancel background task
    background_task.cancel()
    try:
        await background_task
    except asyncio.CancelledError:
        pass
    
    await stop_turbo_processor()
    logger.info("=" * 50)
    logger.info("Trading Bot Shutting Down")
    logger.info("=" * 50)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Melon Trading Bot",
        version="2.0.0",
        description="Chartink webhook trading bot",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://coolify.themelon.in",
            "https://themelon.in",
            "http://localhost:8000",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Kite-Version"],
    )

    # API routes
    app.include_router(trading.router)
    app.include_router(config_routes.router)
    app.include_router(webhook_routes.router)
    app.include_router(analytics_routes.router)
    app.include_router(alerts_routes.router)
    app.include_router(turbo_routes.router)

    # UI routes (includes / and /dashboard — must be included last to avoid
    # shadowing API routes registered above)
    app.include_router(ui_routes.router)

    # Static assets
    try:
        app.mount("/static", StaticFiles(directory="static"), name="static")
    except Exception as e:
        import logging
        logging.getLogger("trading_bot").warning(f"Static files mount failed: {e}")

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        from src.api.routes.config import load_config
        from src.models.database import get_db_session
        config = load_config()
        checks: dict = {}

        # Config file
        checks["config"] = {
            "status": "ok",
            "system_enabled": config.get("system_enabled", False),
            "paper_trading": config.get("paper_trading", True),
        }

        # Database
        try:
            db = get_db_session()
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
            db.close()
            checks["database"] = {"status": "ok"}
        except Exception as e:
            checks["database"] = {"status": "error", "message": str(e)}

        overall = "healthy" if all(v.get("status") == "ok" for v in checks.values()) else "degraded"
        return {
            "status": overall,
            "version": "2.0.0",
            "mode": "paper" if settings.paper_trading else "live",
            "timestamp": ist_naive().isoformat(),
            "checks": checks,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    # SQLite requires single worker — always 1 until PostgreSQL migration
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
    )
