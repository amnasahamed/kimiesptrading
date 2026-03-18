"""
Trading Bot Application — src/ entry point.
"""
import os
import sys

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

    yield

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
            "*",  # Allow all origins for webhook compatibility
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
            "timestamp": __import__("datetime").datetime.now().isoformat(),
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
