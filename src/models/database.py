"""
Database models and connection management.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, 
    DateTime, Boolean, Text, JSON, ForeignKey, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.pool import StaticPool

from src.core.config import get_settings


Base = declarative_base()


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class Position(Base):
    """Open position model."""
    __tablename__ = "positions"
    
    id = Column(String(100), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_order_id = Column(String(100))
    sl_price = Column(Float, nullable=False)
    tp_price = Column(Float, nullable=False)
    sl_order_id = Column(String(100))
    tp_order_id = Column(String(100))
    status = Column(String(20), default="OPEN", index=True)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_price = Column(Float)
    exit_time = Column(DateTime)
    exit_reason = Column(String(50))
    pnl = Column(Float, default=0.0)
    paper_trading = Column(Boolean, default=False, index=True)
    external = Column(Boolean, default=False)
    source = Column(String(50), default="BOT")
    clubbed = Column(Boolean, default=False)
    club_count = Column(Integer, default=1)
    component_trades = Column(JSON, default=list)
    partial_exits = Column(JSON, default=list)
    highest_r = Column(Float, default=0.0)
    
    # Relationships
    trades = relationship("Trade", back_populates="position")
    
    __table_args__ = (
        Index('idx_symbol_status', 'symbol', 'status'),
        Index('idx_paper_status', 'paper_trading', 'status'),
    )


class Trade(Base):
    """Trade execution log."""
    __tablename__ = "trades"
    
    id = Column(String(100), primary_key=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    stop_loss = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    risk_amount = Column(Float)
    risk_reward = Column(Float)
    atr = Column(Float)
    order_id = Column(String(100))
    order_status = Column(String(20))
    sl_order_id = Column(String(100))
    tp_order_id = Column(String(100))
    status = Column(String(20), default="PENDING")
    pnl = Column(Float, default=0.0)
    alert_name = Column(String(200))
    scan_name = Column(String(200))
    paper_trading = Column(Boolean, default=False, index=True)
    context = Column(JSON)
    position_id = Column(String(100), ForeignKey("positions.id"))
    
    # Relationships
    position = relationship("Position", back_populates="trades")
    
    __table_args__ = (
        Index('idx_trade_date', 'date', 'symbol'),
        Index('idx_trade_paper', 'paper_trading', 'date'),
    )


class Signal(Base):
    """Signal tracking for analysis."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # RECEIVED, VALIDATED, EXECUTING, EXECUTED, REJECTED
    reason = Column(Text)
    signal_metadata = Column(JSON)  # renamed from metadata (reserved by SQLAlchemy)
    paper_trading = Column(Boolean, default=False)
    
    __table_args__ = (
        Index('idx_signal_ts', 'timestamp', 'symbol'),
    )


class IncomingAlert(Base):
    """Incoming webhook alerts log."""
    __tablename__ = "incoming_alerts"
    
    id = Column(String(50), primary_key=True)
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    alert_type = Column(String(20))  # json, form, get
    symbols = Column(JSON)
    raw_payload = Column(JSON)
    source_ip = Column(String(50))
    headers = Column(JSON)
    processing_status = Column(String(20), default="pending")  # pending, processing, processed, rejected, error
    processing_result = Column(Text)
    latency_ms = Column(Float)
    
    __table_args__ = (
        Index('idx_alert_received', 'received_at', 'processing_status'),
    )


class Config(Base):
    """Application configuration storage."""
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, default=1)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(JSON)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Insight(Base):
    """Per-symbol trade analytics (replaces trade_insights.json)."""
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    avg_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    avg_hold_minutes = Column(Float, default=0.0)
    best_pnl = Column(Float, default=0.0)
    worst_pnl = Column(Float, default=0.0)
    extra = Column(JSON, default=dict)

    __table_args__ = (
        Index('idx_insight_symbol_date', 'symbol', 'date'),
    )


class TurboQueueItem(Base):
    """Multi-timeframe signal queue (replaces turbo_queue.json)."""
    __tablename__ = "turbo_queue"

    id = Column(String(100), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    scan_name = Column(String(200))
    alert_price = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(20), default="pending", index=True)  # pending, processing, done, failed
    timeframes_confirmed = Column(JSON, default=list)
    timeframes_required = Column(JSON, default=list)
    result = Column(Text)
    processed_at = Column(DateTime)
    extra = Column(JSON, default=dict)

    __table_args__ = (
        Index('idx_turbo_symbol_status', 'symbol', 'status'),
    )


class ErrorLog(Base):
    """Centralized error tracking (replaces error_log.json)."""
    __tablename__ = "error_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    category = Column(String(50), index=True)
    message = Column(Text, nullable=False)
    details = Column(JSON, default=dict)
    resolved = Column(Boolean, default=False)

    __table_args__ = (
        Index('idx_error_ts', 'timestamp', 'category'),
    )


# Database engine and session
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        
        # SQLite specific settings for async compatibility
        if settings.database_url.startswith("sqlite"):
            _engine = create_engine(
                settings.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=settings.debug
            )
        else:
            _engine = create_engine(settings.database_url, echo=settings.debug)
    
    return _engine


def init_db():
    """Initialize database tables."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Get database session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get database session (non-generator version)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal()
