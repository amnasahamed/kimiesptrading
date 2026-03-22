"""
Application configuration with environment variables.
"""
import os
from pathlib import Path
from typing import Optional, List
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # App
    app_name: str = "Trading Bot"
    debug: bool = False
    secret_key: str = Field(default="change-me-in-production")
    
    # Kite API
    kite_api_key: str = Field(default="")
    kite_api_secret: str = Field(default="")
    kite_access_token: str = Field(default="")
    kite_base_url: str = "https://api.kite.trade"
    
    # Telegram
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    telegram_enabled: bool = False
    
    # Database
    database_url: str = Field(default="sqlite:///./trading_bot.db")
    redis_url: Optional[str] = Field(default=None)
    
    # Trading Settings
    paper_trading: bool = True
    capital: float = 100000.0
    risk_percent: float = 1.0
    max_trades_per_day: int = 10
    trade_budget: float = 50000.0
    
    # Features
    club_positions: bool = False
    prevent_duplicate_stocks: bool = True
    trailing_tp_enabled: bool = False
    
    # Security
    webhook_secret: str = Field(default="")
    
    # Trading Hours
    trading_hours_start: str = "09:15"
    trading_hours_end: str = "15:30"
    
    # Risk Management
    atr_multiplier_sl: float = 1.5
    atr_multiplier_tp: float = 3.0
    min_risk_reward: float = 2.0
    max_sl_percent: float = 2.0
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or text
    
    # Rate Limiting
    rate_limit: int = 20
    rate_window: int = 60
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global _settings
    _settings = Settings()
    return _settings
