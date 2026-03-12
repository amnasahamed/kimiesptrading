"""
Structured logging configuration.
"""
import logging
import sys
from typing import Any, Dict
import json
from datetime import datetime

from src.core.config import get_settings


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields if present
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Add extra fields to message if present
        extra_str = ""
        if hasattr(record, "extra"):
            extra_str = " | " + " ".join(f"{k}={v}" for k, v in record.extra.items())
        
        record.message = record.getMessage() + extra_str
        return super().format(record)


def setup_logging() -> logging.Logger:
    """Setup application logging."""
    settings = get_settings()
    
    # Create logger
    logger = logging.getLogger("trading_bot")
    logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # Remove existing handlers
    logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.log_level.upper()))
    
    # Set formatter based on settings
    if settings.log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler for errors
    file_handler = logging.FileHandler("logs/app.log")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)
    
    return logger


# Global logger instance
_logger = None


def get_logger() -> logging.Logger:
    """Get application logger."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


def log_trade(symbol: str, action: str, quantity: int, price: float, 
              paper: bool = False, **kwargs) -> None:
    """Log trade execution with structured data."""
    logger = get_logger()
    logger.info(
        f"Trade executed: {symbol} {action} {quantity} @ ₹{price}",
        extra={
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "paper_trading": paper,
            "event_type": "trade",
            **kwargs
        }
    )


def log_signal(symbol: str, status: str, reason: str = None, **kwargs) -> None:
    """Log signal processing with structured data."""
    logger = get_logger()
    logger.info(
        f"Signal {status}: {symbol}" + (f" - {reason}" if reason else ""),
        extra={
            "symbol": symbol,
            "status": status,
            "reason": reason,
            "event_type": "signal",
            **kwargs
        }
    )


def log_error(error: Exception, context: Dict[str, Any] = None) -> None:
    """Log error with context."""
    logger = get_logger()
    logger.error(
        str(error),
        extra={
            "error_type": type(error).__name__,
            "event_type": "error",
            **(context or {})
        },
        exc_info=True
    )
