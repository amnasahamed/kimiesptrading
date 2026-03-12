"""
Risk management service for validation and position sizing.
"""
from typing import Optional, Dict, Any, NamedTuple
from datetime import datetime, time

from src.core.config import get_settings
from src.core.logging_config import get_logger
from src.models.database import get_db_session
from src.repositories.position_repository import PositionRepository

logger = get_logger()


class ValidationResult(NamedTuple):
    is_valid: bool
    reason: Optional[str] = None


class PositionCalculation(NamedTuple):
    quantity: int
    stop_loss: float
    target: float
    risk_amount: float
    risk_reward: float


class RiskService:
    """Risk management service."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def validate_signal(
        self, 
        symbol: str, 
        is_paper: bool = False
    ) -> ValidationResult:
        """
        Validate if a signal should be executed.
        """
        # 1. Check if system is enabled
        if not self._is_system_enabled():
            return ValidationResult(False, "System is disabled")
        
        # 2. Check trading hours
        if not self._is_in_trading_hours():
            return ValidationResult(False, "Outside trading hours")
        
        # 3. Check position limits
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            
            if is_paper:
                paper_count = position_repo.get_position_count(
                    status="OPEN", 
                    paper_trading=True
                )
                if paper_count >= 20:  # Paper limit
                    return ValidationResult(False, "Max paper positions (20) reached")
            else:
                live_count = position_repo.get_position_count(
                    status="OPEN", 
                    paper_trading=False
                )
                if live_count >= 3:  # Live limit
                    return ValidationResult(False, "Max live positions (3) reached")
            
            # 4. Check duplicate (only in same mode)
            if self.settings.prevent_duplicate_stocks:
                existing = position_repo.get_by_symbol(
                    symbol=symbol,
                    status="OPEN",
                    paper_trading=is_paper
                )
                if existing:
                    return ValidationResult(
                        False, 
                        f"Already holding {symbol} in {'paper' if is_paper else 'live'} mode"
                    )
            
            # 5. Check daily loss limit (live only)
            if not is_paper:
                daily_pnl = self._get_daily_pnl()
                max_loss = -(self.settings.capital * 0.03)  # 3% max loss
                if daily_pnl <= max_loss:
                    return ValidationResult(
                        False, 
                        f"Daily loss limit hit: ₹{daily_pnl:.2f}"
                    )
            
            return ValidationResult(True)
            
        finally:
            db.close()
    
    async def calculate_position(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        paper_trading: bool = False
    ) -> Optional[PositionCalculation]:
        """
        Calculate position size based on risk parameters.
        """
        # Risk amount
        risk_amount = self.settings.capital * (self.settings.risk_percent / 100)
        
        # Calculate SL/TP based on ATR
        sl_distance = atr * self.settings.atr_multiplier_sl
        tp_distance = atr * self.settings.atr_multiplier_tp
        
        stop_loss = entry_price - sl_distance
        target = entry_price + tp_distance
        
        # Calculate risk-reward
        risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0
        
        if risk_reward < self.settings.min_risk_reward:
            logger.warning(f"Risk-reward too low: {risk_reward:.2f}")
            return None
        
        # Calculate quantity based on risk
        risk_per_share = entry_price - stop_loss
        if risk_per_share <= 0:
            return None
        
        quantity = int(risk_amount / risk_per_share)
        
        # Apply budget constraint
        position_value = quantity * entry_price
        if position_value > self.settings.trade_budget:
            quantity = int(self.settings.trade_budget / entry_price)
        
        # Minimum 1 share
        quantity = max(1, quantity)
        
        # Round to lot size (assuming 1 for stocks)
        lot_size = 1
        quantity = (quantity // lot_size) * lot_size
        
        return PositionCalculation(
            quantity=quantity,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_amount=risk_amount,
            risk_reward=round(risk_reward, 2)
        )
    
    def _is_system_enabled(self) -> bool:
        """Check if trading system is enabled."""
        # Could check a config flag in database
        return True
    
    def _is_in_trading_hours(self) -> bool:
        """Check if current time is within trading hours."""
        now = datetime.utcnow().time()
        start = datetime.strptime(self.settings.trading_hours_start, "%H:%M").time()
        end = datetime.strptime(self.settings.trading_hours_end, "%H:%M").time()
        return start <= now <= end
    
    def _get_daily_pnl(self) -> float:
        """Get today's P&L."""
        # Simplified - would fetch from database
        return 0.0
    
    def validate_close_position(
        self, 
        position_id: str,
        current_price: float
    ) -> ValidationResult:
        """Validate if position can be closed."""
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            position = position_repo.get_by_id(position_id)
            
            if not position:
                return ValidationResult(False, "Position not found")
            
            if position.status != "OPEN":
                return ValidationResult(False, "Position already closed")
            
            return ValidationResult(True)
            
        finally:
            db.close()


# Global service instance
_risk_service: Optional[RiskService] = None


def get_risk_service() -> RiskService:
    """Get risk service singleton."""
    global _risk_service
    if _risk_service is None:
        _risk_service = RiskService()
    return _risk_service
