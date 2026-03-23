"""
Configuration API routes — GET/POST /api/config, POST /api/test-kite
"""
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.config import get_settings, reload_settings
from src.core.logging_config import get_logger

logger = get_logger()
router = APIRouter(tags=["config"])

CONFIG_FILE = Path("config.json")

# In-memory config cache — avoids disk reads on every incoming signal
_config_cache: Dict[str, Any] = {}
_config_cache_ts: float = 0.0
_CONFIG_CACHE_TTL = 30.0  # seconds


def load_config() -> Dict[str, Any]:
    """Load config.json, using a 30-second in-memory cache."""
    global _config_cache, _config_cache_ts
    now = time.monotonic()
    if _config_cache and (now - _config_cache_ts) < _CONFIG_CACHE_TTL:
        return _config_cache
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        _config_cache = data
        _config_cache_ts = now
        return data
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return _config_cache or {}


def save_config(config: Dict[str, Any]):
    """Save config.json to disk and bust the in-memory cache."""
    global _config_cache, _config_cache_ts
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
            f.flush()
        # Bust cache so next read picks up the new file
        _config_cache = config
        _config_cache_ts = time.monotonic()
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        raise


class ConfigUpdate(BaseModel):
    system_enabled: Optional[bool] = None
    capital: Optional[float] = None
    risk_percent: Optional[float] = None
    trade_budget: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    trading_hours: Optional[Dict[str, str]] = None
    kite_access_token: Optional[str] = None
    kite_api_key: Optional[str] = None
    kite_api_secret: Optional[str] = None
    telegram: Optional[Dict[str, Any]] = None
    whatsapp: Optional[Dict[str, Any]] = None
    analysis_engine: Optional[Dict[str, Any]] = None
    chartink: Optional[Dict[str, Any]] = None
    risk_management: Optional[Dict[str, Any]] = None
    paper_trading: Optional[bool] = None
    prevent_duplicate_stocks: Optional[bool] = None
    club_positions: Optional[bool] = None
    signal_validation: Optional[Dict[str, Any]] = None
    trading_windows: Optional[List[Dict[str, Any]]] = None


@router.get("/api/config")
async def get_config():
    """Get current configuration (sensitive fields masked)."""
    config = load_config()
    # Mask sensitive keys
    if "kite" in config:
        config["kite"] = {
            **config["kite"],
            "api_key": "***" if config["kite"].get("api_key") else "",
            "api_secret": "***" if config["kite"].get("api_secret") else "",
            "access_token": "***" if config["kite"].get("access_token") else "",
        }
    if "telegram" in config:
        config["telegram"] = {
            **config["telegram"],
            "bot_token": "***" if config["telegram"].get("bot_token") else "",
        }
    if "whatsapp" in config:
        config["whatsapp"] = {
            **config["whatsapp"],
            "api_key": "***" if config["whatsapp"].get("api_key") else "",
        }
    if "analysis_engine" in config:
        ae = config["analysis_engine"]
        if ae.get("openai_api_key"):
            ae["openai_api_key"] = "***"
        if ae.get("claude_api_key"):
            ae["claude_api_key"] = "***"
    return config


@router.post("/api/config")
async def update_config(update: ConfigUpdate):
    """Update configuration."""
    config = load_config()

    if update.system_enabled is not None:
        config["system_enabled"] = update.system_enabled
    if update.capital is not None:
        if update.capital <= 0:
            raise HTTPException(status_code=400, detail="Capital must be positive")
        config["capital"] = update.capital
    if update.risk_percent is not None:
        if not (0 < update.risk_percent <= 100):
            raise HTTPException(status_code=400, detail="Risk percent must be between 0 and 100")
        config["risk_percent"] = update.risk_percent
    if update.trade_budget is not None:
        if update.trade_budget <= 0:
            raise HTTPException(status_code=400, detail="Trade budget must be positive")
        config["trade_budget"] = update.trade_budget
    if update.max_trades_per_day is not None:
        if update.max_trades_per_day < 1:
            raise HTTPException(status_code=400, detail="Max trades must be at least 1")
        config["max_trades_per_day"] = update.max_trades_per_day
    if update.trading_hours is not None:
        config["trading_hours"] = update.trading_hours
    if update.telegram is not None:
        config["telegram"] = update.telegram
    if update.whatsapp is not None:
        config["whatsapp"] = update.whatsapp
    if update.analysis_engine is not None:
        config["analysis_engine"] = update.analysis_engine
    if update.chartink is not None:
        config["chartink"] = update.chartink
    if update.risk_management is not None:
        config["risk_management"] = update.risk_management
    if update.paper_trading is not None:
        config["paper_trading"] = update.paper_trading
    if update.prevent_duplicate_stocks is not None:
        config["prevent_duplicate_stocks"] = update.prevent_duplicate_stocks
    if update.club_positions is not None:
        config["club_positions"] = update.club_positions
    if update.signal_validation is not None:
        if "signal_validation" not in config:
            config["signal_validation"] = {}
        config["signal_validation"].update(update.signal_validation)
    if update.trading_windows is not None:
        config["trading_windows"] = update.trading_windows
        # Sync trading_hours to range of enabled windows
        enabled = [w for w in update.trading_windows if w.get("enabled", True)]
        if enabled:
            starts = [w.get("start", "09:15") for w in enabled]
            ends = [w.get("end", "15:30") for w in enabled]
            config["trading_hours"] = {"start": min(starts), "end": max(ends)}

    # Kite credentials
    if update.kite_api_key:
        config.setdefault("kite", {})["api_key"] = update.kite_api_key
    if update.kite_api_secret:
        config.setdefault("kite", {})["api_secret"] = update.kite_api_secret
    if update.kite_access_token is not None:
        kite_cfg = config.setdefault("kite", {})
        if update.kite_access_token == "":
            # Revoke — clear the token
            kite_cfg.pop("access_token", None)
        else:
            api_key = kite_cfg.get("api_key")
            # Prefer passed api_secret, fall back to stored config secret
            api_secret = update.kite_api_secret or kite_cfg.get("api_secret")
            # Kite request_tokens are 32 hex chars; access_tokens are longer
            # Try exchange if we have credentials and token looks like a request_token
            if api_key and api_secret and len(update.kite_access_token) <= 64:
                from src.services.kite_service import KiteService
                svc = KiteService()
                try:
                    access_token = await svc.exchange_request_token(
                        update.kite_access_token, api_key, api_secret
                    )
                    if access_token:
                        kite_cfg["access_token"] = access_token
                        save_config(config)
                        from src.services.kite_service import reset_kite_service
                        reset_kite_service()
                        return {"status": "updated", "message": "Token exchanged successfully", "exchanged": True, "access_token": access_token}
                except Exception as e:
                    logger.warning(f"Token exchange failed, storing raw token: {e}")
            kite_cfg["access_token"] = update.kite_access_token

    save_config(config)
    reload_settings()
    from src.services.kite_service import reset_kite_service
    reset_kite_service()
    return {"status": "updated"}


@router.post("/api/test-kite")
async def test_kite():
    """Test Kite API connection using credentials from config.json."""
    config = load_config()
    kite_cfg = config.get("kite", {})
    api_key = kite_cfg.get("api_key", "")
    access_token = kite_cfg.get("access_token", "")

    if not api_key or not access_token:
        return {"status": "failed", "message": "API Key or Access Token missing in config"}

    # Always use a fresh KiteService built with current config credentials
    # (the singleton may have stale headers from env vars)
    from src.services.kite_service import KiteService
    kite = KiteService()
    # Override headers with credentials from config.json
    kite.headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{access_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        quote = await kite.get_quote("NIFTY 50")
        if quote:
            return {"status": "success", "message": f"Connected! NIFTY 50 LTP: ₹{quote.ltp}", "nifty_ltp": quote.ltp}
        # Fallback to RELIANCE if NIFTY 50 quote fails
        quote = await kite.get_quote("RELIANCE")
        if quote:
            return {"status": "success", "message": f"Connected! RELIANCE LTP: ₹{quote.ltp}", "nifty_ltp": quote.ltp}
        return {"status": "failed", "message": "Could not fetch quote — token may be expired or invalid"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}
    finally:
        await kite.close()
