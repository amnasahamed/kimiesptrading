"""
Position repository for database operations.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from src.models.database import Position as PositionModel, Trade as TradeModel
from src.core.logging_config import get_logger

logger = get_logger()


class PositionRepository:
    """Repository for position operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_id(self, position_id: str) -> Optional[PositionModel]:
        """Get position by ID."""
        return self.db.query(PositionModel).filter(
            PositionModel.id == position_id
        ).first()
    
    def get_open_positions(
        self, 
        paper_trading: Optional[bool] = None
    ) -> List[PositionModel]:
        """Get all open positions, optionally filtered by paper trading mode."""
        query = self.db.query(PositionModel).filter(
            PositionModel.status == "OPEN"
        )
        
        if paper_trading is not None:
            query = query.filter(
                PositionModel.paper_trading == paper_trading
            )
        
        return query.all()
    
    def get_by_symbol(
        self, 
        symbol: str, 
        status: str = "OPEN",
        paper_trading: Optional[bool] = None
    ) -> List[PositionModel]:
        """Get positions by symbol."""
        query = self.db.query(PositionModel).filter(
            and_(
                PositionModel.symbol == symbol.upper(),
                PositionModel.status == status
            )
        )
        
        if paper_trading is not None:
            query = query.filter(
                PositionModel.paper_trading == paper_trading
            )
        
        return query.all()
    
    def create(self, position_data: Dict[str, Any]) -> PositionModel:
        """Create new position."""
        position = PositionModel(**position_data)
        self.db.add(position)
        self.db.commit()
        self.db.refresh(position)
        logger.info(f"Created position: {position.id}")
        return position
    
    def update(
        self, 
        position_id: str, 
        updates: Dict[str, Any]
    ) -> Optional[PositionModel]:
        """Update position."""
        position = self.get_by_id(position_id)
        if position:
            for key, value in updates.items():
                setattr(position, key, value)
            self.db.commit()
            self.db.refresh(position)
            logger.debug(f"Updated position: {position_id}")
        return position
    
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        pnl: float,
        reason: str = "MANUAL"
    ) -> Optional[PositionModel]:
        """Close a position."""
        position = self.get_by_id(position_id)
        if position:
            position.status = "CLOSED"
            position.exit_price = exit_price
            position.pnl = pnl
            position.exit_reason = reason
            position.exit_time = datetime.utcnow()
            self.db.commit()
            self.db.refresh(position)
            logger.info(f"Closed position: {position_id}, P&L: ₹{pnl:.2f}")
        return position
    
    def get_position_count(
        self, 
        status: str = "OPEN",
        paper_trading: Optional[bool] = None
    ) -> int:
        """Count positions."""
        query = self.db.query(PositionModel).filter(
            PositionModel.status == status
        )
        
        if paper_trading is not None:
            query = query.filter(
                PositionModel.paper_trading == paper_trading
            )
        
        return query.count()
    
    def get_clubbed_position(
        self, 
        symbol: str, 
        paper_trading: bool
    ) -> Optional[PositionModel]:
        """Get existing clubbed position for symbol."""
        return self.db.query(PositionModel).filter(
            and_(
                PositionModel.symbol == symbol.upper(),
                PositionModel.status == "OPEN",
                PositionModel.clubbed == True,
                PositionModel.paper_trading == paper_trading
            )
        ).first()
    
    def get_total_pnl(
        self, 
        paper_trading: Optional[bool] = None
    ) -> float:
        """Get total unrealized P&L."""
        query = self.db.query(PositionModel).filter(
            PositionModel.status == "OPEN"
        )
        
        if paper_trading is not None:
            query = query.filter(
                PositionModel.paper_trading == paper_trading
            )
        
        positions = query.all()
        return sum(p.pnl or 0 for p in positions)


class TradeRepository:
    """Repository for trade operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, trade_data: Dict[str, Any]) -> TradeModel:
        """Create new trade record."""
        trade = TradeModel(**trade_data)
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        return trade
    
    def get_today_trades(
        self, 
        paper_trading: Optional[bool] = None
    ) -> List[TradeModel]:
        """Get today's trades."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        query = self.db.query(TradeModel).filter(
            TradeModel.date >= today
        )
        
        if paper_trading is not None:
            query = query.filter(
                TradeModel.paper_trading == paper_trading
            )
        
        return query.order_by(desc(TradeModel.date)).all()
    
    def get_all_trades(
        self,
        limit: int = 100,
        paper_trading: Optional[bool] = None
    ) -> List[TradeModel]:
        """Get all trades with limit."""
        query = self.db.query(TradeModel)
        
        if paper_trading is not None:
            query = query.filter(
                TradeModel.paper_trading == paper_trading
            )
        
        return query.order_by(desc(TradeModel.date)).limit(limit).all()
    
    def update_pnl(
        self, 
        trade_id: str, 
        exit_price: float, 
        pnl: float
    ) -> Optional[TradeModel]:
        """Update trade P&L on close."""
        trade = self.db.query(TradeModel).filter(
            TradeModel.id == trade_id
        ).first()
        
        if trade:
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.status = "CLOSED"
            self.db.commit()
            self.db.refresh(trade)
        
        return trade
    
    def get_trade_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get trading statistics."""
        since = datetime.utcnow() - timedelta(days=days)
        
        trades = self.db.query(TradeModel).filter(
            TradeModel.date >= since
        ).all()
        
        if not trades:
            return {
                "total": 0,
                "winners": 0,
                "losers": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "total_pnl": 0
            }
        
        closed = [t for t in trades if t.status == "CLOSED"]
        winners = [t for t in closed if (t.pnl or 0) > 0]
        losers = [t for t in closed if (t.pnl or 0) < 0]
        
        total_pnl = sum(t.pnl or 0 for t in closed)
        
        return {
            "total": len(trades),
            "closed": len(closed),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": len(winners) / len(closed) * 100 if closed else 0,
            "avg_pnl": total_pnl / len(closed) if closed else 0,
            "total_pnl": total_pnl,
            "avg_winner": sum(t.pnl or 0 for t in winners) / len(winners) if winners else 0,
            "avg_loser": sum(t.pnl or 0 for t in losers) / len(losers) if losers else 0
        }
