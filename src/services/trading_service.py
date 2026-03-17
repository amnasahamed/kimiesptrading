"""
Main trading service orchestrating all operations.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio

from src.core.config import get_settings
from src.core.logging_config import get_logger, log_trade, log_signal
from src.models.database import get_db_session
from src.repositories.position_repository import PositionRepository, TradeRepository
from src.services.kite_service import get_kite_service, KiteQuote
from src.services.risk_service import get_risk_service
from src.utils.cache import get_cache

logger = get_logger()


class TradingService:
    """Main trading service."""
    
    def __init__(self):
        self.settings = get_settings()
        self.kite = get_kite_service()
        self.risk = get_risk_service()
        self.cache = get_cache()
    
    async def process_signal(
        self,
        symbol: str,
        alert_price: Optional[float],
        scan_name: str,
        action: str = "BUY",
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process a trading signal end-to-end.
        """
        start_time = datetime.utcnow()
        cfg = config or self._load_config()
        paper_setting = cfg.get("paper_trading", self.settings.paper_trading)
        is_paper = paper_setting if isinstance(paper_setting, bool) else bool(paper_setting)

        logger.info(f"Processing signal: {symbol} ({'PAPER' if is_paper else 'LIVE'})")

        # 1. Validate signal
        validation_result = await self.risk.validate_signal(
            symbol, is_paper, kite=self.kite, config=cfg
        )
        if not validation_result.is_valid:
            log_signal(symbol, "REJECTED", validation_result.reason, paper=is_paper)
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "reason": validation_result.reason,
                "timestamp": start_time.isoformat()
            }
        
        # 2. Get current market price
        quote = await self.kite.get_quote(symbol)
        if not quote:
            return {
                "status": "ERROR",
                "symbol": symbol,
                "reason": "Could not fetch market price",
                "timestamp": start_time.isoformat()
            }
        
        current_price = quote.ltp
        
        # 3. Check price slippage
        if alert_price and alert_price > 0:
            slippage = (current_price - alert_price) / alert_price * 100
            max_slippage = 1.0 if is_paper else 0.5
            
            if slippage > max_slippage:
                return {
                    "status": "REJECTED",
                    "symbol": symbol,
                    "reason": f"Price slippage too high: {slippage:.2f}%",
                    "timestamp": start_time.isoformat()
                }
        
        # 4. Calculate position size
        position_calc = await self.risk.calculate_position(
            symbol=symbol,
            entry_price=current_price,
            atr=await self._get_atr(symbol),
            paper_trading=is_paper
        )
        
        if not position_calc:
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "reason": "Position sizing failed",
                "timestamp": start_time.isoformat()
            }
        
        # 5. Execute trade
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            trade_repo = TradeRepository(db)
            
            # Create position
            position_data = {
                "id": f"{'PAPER' if is_paper else 'LIVE'}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{symbol}",
                "symbol": symbol,
                "quantity": position_calc.quantity,
                "entry_price": current_price,
                "sl_price": position_calc.stop_loss,
                "tp_price": position_calc.target,
                "paper_trading": is_paper,
                "status": "OPEN"
            }
            
            if is_paper:
                # Simulate paper trade
                position = position_repo.create(position_data)
                order_result = {
                    "status": "SUCCESS",
                    "order_id": f"PAPER_{symbol}_{int(datetime.utcnow().timestamp())}",
                    "message": "Paper trade executed"
                }
            else:
                # Live trade - place actual order
                order_result = await self.kite.place_order(
                    symbol=symbol,
                    transaction_type=action,
                    quantity=position_calc.quantity
                )
                
                if order_result["status"] == "SUCCESS":
                    position_data["entry_order_id"] = order_result["order_id"]
                    position = position_repo.create(position_data)
                else:
                    return {
                        "status": "FAILED",
                        "symbol": symbol,
                        "reason": order_result.get("message", "Order failed"),
                        "timestamp": start_time.isoformat()
                    }
            
            # Log trade
            trade_data = {
                "id": f"TRADE_{position.id}",
                "symbol": symbol,
                "action": action,
                "entry_price": current_price,
                "stop_loss": position_calc.stop_loss,
                "target": position_calc.target,
                "quantity": position_calc.quantity,
                "risk_amount": position_calc.risk_amount,
                "risk_reward": position_calc.risk_reward,
                "order_id": order_result.get("order_id"),
                "status": "OPEN",
                "paper_trading": is_paper,
                "alert_name": scan_name
            }
            trade_repo.create(trade_data)
            
            log_trade(
                symbol=symbol,
                action=action,
                quantity=position_calc.quantity,
                price=current_price,
                paper=is_paper,
                order_id=order_result.get("order_id")
            )
            
            return {
                "status": "SUCCESS",
                "symbol": symbol,
                "order_id": order_result.get("order_id"),
                "position_id": position.id,
                "entry_price": current_price,
                "quantity": position_calc.quantity,
                "stop_loss": position_calc.stop_loss,
                "target": position_calc.target,
                "timestamp": start_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            db.rollback()
            return {
                "status": "ERROR",
                "symbol": symbol,
                "reason": str(e),
                "timestamp": start_time.isoformat()
            }
        finally:
            db.close()
    
    async def close_position(
        self,
        position_id: str,
        exit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """Close a position."""
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            trade_repo = TradeRepository(db)
            
            position = position_repo.get_by_id(position_id)
            if not position:
                return {"status": "ERROR", "reason": "Position not found"}
            
            if position.status != "OPEN":
                return {"status": "ERROR", "reason": "Position already closed"}
            
            # Get exit price
            if exit_price is None:
                quote = await self.kite.get_quote(position.symbol)
                if quote:
                    exit_price = quote.ltp
                else:
                    return {"status": "ERROR", "reason": "Could not get market price"}
            
            # Calculate P&L
            pnl = (exit_price - position.entry_price) * position.quantity
            
            # Close in broker if live
            if not position.paper_trading:
                order_result = await self.kite.place_order(
                    symbol=position.symbol,
                    transaction_type="SELL",
                    quantity=position.quantity
                )
                
                if order_result["status"] != "SUCCESS":
                    return {
                        "status": "FAILED",
                        "reason": order_result.get("message", "Exit order failed")
                    }
            
            # Update database
            position_repo.close_position(position_id, exit_price, pnl, "MANUAL")
            
            # Update trade record
            trade = trade_repo.db.query(trade_repo.db.query(TradeRepository).filter_by(
                position_id=position_id
            ).first().__class__).first()
            
            if trade:
                trade_repo.update_pnl(trade.id, exit_price, pnl)
            
            logger.info(f"Closed position {position_id}: P&L ₹{pnl:.2f}")
            
            return {
                "status": "SUCCESS",
                "position_id": position_id,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_percent": (pnl / (position.entry_price * position.quantity)) * 100
            }
            
        except Exception as e:
            logger.error(f"Close position error: {e}")
            db.rollback()
            return {"status": "ERROR", "reason": str(e)}
        finally:
            db.close()
    
    async def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary."""
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            trade_repo = TradeRepository(db)
            
            # Open positions
            paper_positions = position_repo.get_open_positions(paper_trading=True)
            live_positions = position_repo.get_open_positions(paper_trading=False)
            
            # Calculate P&L
            paper_pnl = sum(p.pnl or 0 for p in paper_positions)
            live_pnl = sum(p.pnl or 0 for p in live_positions)
            
            # Today's trades
            today_trades = trade_repo.get_today_trades()
            
            # Stats
            stats = trade_repo.get_trade_stats(days=30)
            
            return {
                "open_positions": {
                    "paper": len(paper_positions),
                    "live": len(live_positions),
                    "total": len(paper_positions) + len(live_positions)
                },
                "unrealized_pnl": {
                    "paper": paper_pnl,
                    "live": live_pnl,
                    "total": paper_pnl + live_pnl
                },
                "today_trades": len(today_trades),
                "stats": stats
            }
            
        finally:
            db.close()
    
    def _load_config(self) -> Dict[str, Any]:
        from src.api.routes.config import load_config
        return load_config()

    async def _get_atr(self, symbol: str) -> float:
        """Get ATR for symbol (simplified)."""
        # In production, fetch historical data and calculate real ATR
        quote = await self.kite.get_quote(symbol)
        if quote:
            return (quote.high - quote.low) * 0.5  # Simplified estimate
        return 2.0  # Default


# Global service instance
_trading_service: Optional[TradingService] = None


def get_trading_service() -> TradingService:
    """Get trading service singleton."""
    global _trading_service
    if _trading_service is None:
        _trading_service = TradingService()
    return _trading_service
