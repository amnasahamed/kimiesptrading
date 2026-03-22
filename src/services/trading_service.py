"""
Main trading service orchestrating all operations - Enhanced Version.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from src.utils.time_utils import ist_naive
import asyncio

from src.core.config import get_settings
from src.core.logging_config import get_logger, log_trade, log_signal
from src.models.database import get_db_session
from src.repositories.position_repository import PositionRepository, TradeRepository
from src.services.kite_service import get_kite_service, KiteQuote
from src.services.risk_service import get_risk_service
from src.services.notification_service import send_telegram
from src.utils.cache import get_cache

logger = get_logger()


class TradingService:
    """Main trading service with smart exits."""
    
    def __init__(self):
        self.settings = get_settings()
        self.kite = get_kite_service()
        self.risk = get_risk_service()
        self.cache = get_cache()
        self._monitored_positions: Dict[str, Any] = {}
    
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
        start_time = ist_naive()
        cfg = config or self._load_config()
        paper_setting = cfg.get("paper_trading", self.settings.paper_trading)
        is_paper = paper_setting if isinstance(paper_setting, bool) else bool(paper_setting)
        side = action.upper()  # BUY = LONG, SELL = SHORT

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

        # 2. Get current market price (reuse quote from validation if available)
        quote = validation_result.quote
        if not quote:
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
        
        # 4. Calculate position size (reuse quote already fetched above)
        position_calc = await self.risk.calculate_position(
            symbol=symbol,
            entry_price=current_price,
            atr=self._atr_from_quote(quote),
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
                "id": f"{'PAPER' if is_paper else 'LIVE'}_{ist_naive().strftime('%Y%m%d%H%M%S')}_{symbol}",
                "symbol": symbol,
                "quantity": position_calc.quantity,
                "entry_price": current_price,
                "sl_price": position_calc.stop_loss,
                "tp_price": position_calc.target,
                "paper_trading": is_paper,
                "status": "OPEN",
                "side": side,
            }

            if is_paper:
                # Simulate paper trade
                position = position_repo.create(position_data)
                order_result = {
                    "status": "SUCCESS",
                    "order_id": f"PAPER_{symbol}_{int(ist_naive().timestamp())}",
                    "message": "Paper trade executed"
                }
            else:
                # Live trade - place actual order
                order_result = await self.kite.place_order(
                    symbol=symbol,
                    transaction_type=action,
                    quantity=position_calc.quantity
                )

                if order_result.get("status") == "SUCCESS":
                    position_data["entry_order_id"] = order_result["order_id"]
                    position = position_repo.create(position_data)
                    
                    # Only place GTT orders for LIVE trades, NOT paper trades
                    # For paper trades, we simulate the exit conditions
                    if not is_paper:
                        sl_order_id = None
                        tp_order_id = None
                        
                        # Place SL GTT (sell if price drops to stop loss)
                        sl_gtt = await self.kite.place_sl_gtt(
                            symbol=symbol,
                            quantity=position_calc.quantity,
                            trigger_price=position_calc.stop_loss,
                            limit_price=round(position_calc.stop_loss * 0.995, 2),
                            product="MIS"
                        )
                        if sl_gtt:
                            sl_order_id = sl_gtt.get("gtt_id")
                            position_repo.update(position.id, {"sl_order_id": sl_order_id})
                            logger.info(f"Placed SL GTT for {symbol}: {sl_order_id} @ {position_calc.stop_loss}")
                        
                        # Place TP GTT (sell if price rises to target)
                        tp_gtt = await self.kite.place_sl_gtt(
                            symbol=symbol,
                            quantity=position_calc.quantity,
                            trigger_price=position_calc.target,
                            limit_price=round(position_calc.target * 0.995, 2),
                            product="MIS"
                        )
                        if tp_gtt:
                            tp_order_id = tp_gtt.get("gtt_id")
                            position_repo.update(position.id, {"tp_order_id": tp_order_id})
                            logger.info(f"Placed TP GTT for {symbol}: {tp_order_id} @ {position_calc.target}")
                    else:
                        logger.info(f"PAPER TRADE: No GTT orders placed (simulation mode)")
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
                "action": action.upper(),
                "entry_price": current_price,
                "stop_loss": position_calc.stop_loss,
                "target": position_calc.target,
                "quantity": position_calc.quantity,
                "risk_amount": position_calc.risk_amount,
                "risk_reward": position_calc.risk_reward,
                "order_id": order_result.get("order_id"),
                "status": "OPEN",
                "paper_trading": is_paper,
                "alert_name": scan_name,
                "position_id": position.id,
            }
            trade_repo.create(trade_data)

            # Bust analytics cache so dashboard reflects this trade immediately
            from src.services.learning_service import _bust_analytics_cache
            _bust_analytics_cache()

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

            # Determine position side (LONG or SHORT)
            # Prefer side stored on position; fall back to Trade.action for legacy positions
            side = getattr(position, "side", None)
            if not side:
                from src.models.database import Trade
                trade = db.query(Trade).filter(
                    Trade.position_id == position_id
                ).first()
                if trade:
                    side = trade.action  # BUY = LONG, SELL = SHORT
                else:
                    side = "BUY"  # Default to LONG for legacy positions without trade record

            is_long = side.upper() == "BUY"

            # Get exit price
            if exit_price is None:
                quote = await self.kite.get_quote(position.symbol)
                if quote:
                    exit_price = quote.ltp
                else:
                    return {"status": "ERROR", "reason": "Could not get market price"}

            # Calculate P&L — LONG: (exit - entry) * qty, SHORT: (entry - exit) * qty
            if is_long:
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity

            # Close in broker if live — opposite of entry side
            if not position.paper_trading:
                close_transaction = "SELL" if is_long else "BUY"
                order_result = await self.kite.place_order(
                    symbol=position.symbol,
                    transaction_type=close_transaction,
                    quantity=position.quantity
                )

                if order_result.get("status") != "SUCCESS":
                    return {
                        "status": "FAILED",
                        "reason": order_result.get("message", "Exit order failed")
                    }

                # Use actual fill price from order if available
                try:
                    fill_price = order_result.get("average_price") or order_result.get("price")
                    if fill_price and float(fill_price) > 0:
                        exit_price = float(fill_price)
                        if is_long:
                            pnl = (exit_price - position.entry_price) * position.quantity
                        else:
                            pnl = (position.entry_price - exit_price) * position.quantity
                        logger.info(f"Using actual fill price for {position.symbol}: ₹{exit_price}")
                except Exception as e:
                    logger.warning(f"Could not get fill price, using LTP: {e}")
            
            # Update database
            position_repo.close_position(position_id, exit_price, pnl, "MANUAL")
            
            # Update trade record
            from src.models.database import Trade
            trade = db.query(Trade).filter(
                Trade.position_id == position_id
            ).first()
            
            if trade:
                trade_repo.update_pnl(trade.id, exit_price, pnl)

            from src.services.learning_service import _bust_analytics_cache
            _bust_analytics_cache()

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
        """Fetch and compute true ATR (Average True Range) over 14 periods."""
        try:
            candles = await self.kite.get_historical_data(symbol, "day", 20)
            if not candles or len(candles) < 14:
                return 2.0
            trs = []
            for i in range(1, len(candles)):
                high = candles[i].get("high", 0)
                low = candles[i].get("low", 0)
                prev_close = candles[i - 1].get("close", 0)
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                trs.append(tr)
            if len(trs) < 14:
                return sum(trs) / len(trs) if trs else 2.0
            return sum(trs[-14:]) / 14
        except Exception:
            return 2.0

    def _atr_from_quote(self, quote) -> float:
        """Estimate ATR from an already-fetched quote (no extra API call)."""
        if quote and quote.high and quote.low and quote.high > quote.low:
            return (quote.high - quote.low) * 0.5
        return 2.0  # Default fallback


    async def check_trailing_stop(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Check and update trailing stop loss for a position.
        Call this periodically for open positions.
        
        Strategy:
        - Move SL to breakeven when profit reaches 1%
        - Move SL to 50% of profit when profit reaches 2%
        - Move SL to 75% of profit when profit reaches 3%
        """
        cfg = self._load_config()
        if not cfg.get("trailing_tp_enabled", True):
            return None
            
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            position = position_repo.get_by_id(position_id)
            
            if not position or position.status != "OPEN":
                return None
            
            # Get current price
            quote = await self.kite.get_quote(position.symbol)
            if not quote:
                return None
            
            current_price = quote.ltp
            entry_price = position.entry_price
            current_sl = position.sl_price
            
            # Calculate profit percentage
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            
            # Determine new SL based on profit
            new_sl = None
            
            if profit_pct >= 3:
                # Lock in 75% of profit
                profit_amount = current_price - entry_price
                new_sl = entry_price + (profit_amount * 0.75)
            elif profit_pct >= 2:
                # Lock in 50% of profit  
                profit_amount = current_price - entry_price
                new_sl = entry_price + (profit_amount * 0.50)
            elif profit_pct >= 1:
                # Move to breakeven + 0.2%
                new_sl = entry_price * 1.002
            
            # Update SL if it's higher than current SL
            if new_sl and new_sl > current_sl:
                position_repo.update(position_id, {"sl_price": round(new_sl, 2)})
                
                # Update GTT order if exists
                if position.sl_order_id and not str(position.sl_order_id).startswith("PAPER_"):
                    try:
                        await self.kite.delete_gtt(str(position.sl_order_id))
                        new_gtt = await self.kite.place_sl_gtt(
                            symbol=position.symbol,
                            quantity=position.quantity,
                            trigger_price=round(new_sl, 2),
                            limit_price=round(new_sl * 0.995, 2),
                            product="MIS"
                        )
                        if new_gtt:
                            position_repo.update(position_id, {"sl_order_id": new_gtt["gtt_id"]})
                            logger.info(f"Trailing SL updated for {position.symbol}: ₹{new_sl:.2f}")
                    except Exception as e:
                        logger.error(f"Failed to update trailing SL: {e}")
                
                return {
                    "action": "trailing_sl_updated",
                    "old_sl": current_sl,
                    "new_sl": new_sl,
                    "profit_pct": profit_pct
                }
                
        except Exception as e:
            logger.error(f"Trailing stop check error: {e}")
        finally:
            db.close()
        
        return None
    
    async def check_partial_profit(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if partial profit booking is needed.
        Books 50% of position when profit reaches 2%.
        """
        cfg = self._load_config()
        if not cfg.get("partial_profit_enabled", True):
            return None
            
        db = get_db_session()
        try:
            position_repo = PositionRepository(db)
            position = position_repo.get_by_id(position_id)
            
            if not position or position.status != "OPEN":
                return None
            
            # Check if partial already taken
            if getattr(position, "partial_exits", None):
                return None  # Already took partial
            
            # Get current price
            quote = await self.kite.get_quote(position.symbol)
            if not quote:
                return None
            
            current_price = quote.ltp
            entry_price = position.entry_price
            
            # Calculate profit percentage
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            
            # Book partial at 2% profit
            if profit_pct >= 2:
                qty_to_close = position.quantity // 2
                if qty_to_close < 1:
                    return None
                    
                exit_price = current_price
                pnl = (exit_price - entry_price) * qty_to_close
                
                # Close partial position
                # Note: Full implementation would create a new closed position record
                # For now, just log and notify
                logger.info(f"Partial profit booking signal for {position.symbol}: {qty_to_close} qty @ ₹{exit_price}, P&L: ₹{pnl:.2f}")
                
                await send_telegram(
                    f"📊 *Partial Profit Signal*\n"
                    f"Symbol: {position.symbol}\n"
                    f"Qty to book: {qty_to_close}\n"
                    f"Entry: ₹{entry_price}\n"
                    f"Current: ₹{current_price}\n"
                    f"Profit: ₹{pnl:.2f} ({profit_pct:.1f}%)"
                )
                
                return {
                    "action": "partial_profit_signal",
                    "quantity": qty_to_close,
                    "profit_pct": profit_pct,
                    "pnl": pnl
                }
                
        except Exception as e:
            logger.error(f"Partial profit check error: {e}")
        finally:
            db.close()
        
        return None


# Global service instance
_trading_service: Optional[TradingService] = None


def get_trading_service() -> TradingService:
    """Get trading service singleton."""
    global _trading_service
    if _trading_service is None:
        _trading_service = TradingService()
    return _trading_service
