"""
Refactored Trading Bot Application
"""
import os
import sys

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import get_settings
from src.core.logging_config import setup_logging, get_logger
from src.models.database import init_db
from src.api.routes import trading

# Setup logging
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("=" * 50)
    logger.info("🚀 Trading Bot Starting (Refactored)")
    logger.info("=" * 50)
    
    # Initialize database
    init_db()
    logger.info("✅ Database initialized")
    
    yield
    
    # Shutdown
    logger.info("=" * 50)
    logger.info("🛑 Trading Bot Shutting Down")
    logger.info("=" * 50)


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Trading Bot",
        version="2.0.0",
        description="Refactored trading bot with proper architecture",
        lifespan=lifespan
    )
    
    # CORS middleware
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
        allow_headers=["Content-Type", "Authorization"],
    )
    
    # Include routers
    app.include_router(trading.router)
    
    # Static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "version": "2.0.0",
            "mode": "paper" if settings.paper_trading else "live"
        }
    
    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "service": "Trading Bot",
            "version": "2.0.0",
            "status": "running"
        }
    
    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=not get_settings().debug,
        workers=1 if get_settings().debug else 4
    )
