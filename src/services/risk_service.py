"""
Risk management service — Enhanced signal validation and position sizing.
"""
from datetime import datetime
from src.utils.time_utils import ist_naive
from typing import Optional, NamedTuple, Dict, Any, TYPE_CHECKING

from src.core.config import get_settings
from src.core.logging_config import get_logger
from src.models.database import get_db_session
from src.repositories.position_repository import PositionRepository

logger = get_logger()


class ValidationResult(NamedTuple):
    is_valid: bool
    reason: Optional[str] = None
    quote: Optional[Any] = None  # Carried back so caller can reuse the fetched quote


class PositionCalculation(NamedTuple):
    quantity: int
    stop_loss: float
    target: float
    risk_amount: float
    risk_reward: float


# Known high-volatility stocks to avoid (can move against you quickly)
HIGH_RISK_STOCKS = {
    "ZOMATO", "PAYTM", "NYKAA", "EMUDHFRA", "DELHIVERY", "FIVESTAR",
    "RBLBANK", "IDFCFIRST", "BANDHAN", "GMRINFRA", "ADANIPOWER",
    "JINDALSTEL", "TATASTEEL", "SAIL", "NMDC", "COALINDIA"
}

# Sector ETFs to check for market direction
INDEX_SYMBOLS = ["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY PHARMA"]

# Risk management constants
MIN_VOLUME = 100_000          # Minimum volume for liquid intraday stock
MAX_PRICE = 10_000            # Maximum price per share for intraday
MIN_PRICE = 10                # Minimum price per share for intraday
EXPENSIVE_STOCK_PRICE = 5_000  # Threshold above which ensure at least 1 lot
RISK_REDUCTION_LOSS_STREAK = 0.5   # Reduce risk by 50% after 2 consecutive losses
RISK_INCREASE_WIN_STREAK = 1.2     # Increase risk by 20% after 3 consecutive wins


class RiskService:
    """Risk management service — Enhanced validation + smart position sizing."""

    def __init__(self):
        self.settings = get_settings()
        self._symbol_cache: Dict[str, Any] = {}

    async def validate_signal(
        self,
        symbol: str,
        is_paper: bool = False,
        kite: Optional[Any] = None,
        config: Optional[dict] = None,
    ) -> ValidationResult:
        """
        Enhanced 8-step signal validation:
          1. System enabled check
          2. Trading window check (best hours: 9:30-11:30, 2:00-3:00)
          3. Nifty health check (live only)
          4. Stock-specific filters (avoid high-risk stocks)
          5. Price & volume validation
          6. Duplicate / existing position check
          7. Max position limit check
          8. Consecutive loss check
        """
        cfg = config or self._load_config()
        
        # Upper case symbol for consistent checks
        symbol = symbol.upper().strip() if symbol else ""

        # Step 1: System enabled
        if not cfg.get("system_enabled", False):
            return ValidationResult(False, "System is disabled")

        # Step 2: Enhanced trading window check
        # Best trading times: 9:30-11:30 AM (morning trend) and 2:00-3:00 PM (closing momentum)
        # Avoid: 9:15-9:30 (wild open), 12:00-1:30 (lunch lull)
        in_window, window_msg = self._is_in_trading_window(cfg)
        if not in_window:
            return ValidationResult(False, window_msg)
        
        # Extra check: avoid first 15 mins of market (too volatile)
        now = ist_naive()
        market_open_15 = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if now < market_open_15:
            return ValidationResult(False, "Avoiding market open chaos (first 15 mins)")

        # Step 3: Nifty health (market direction filter)
        if kite:
            nifty_valid, nifty_msg = await self._validate_market_health(kite, cfg, is_paper)
            if not nifty_valid:
                return ValidationResult(False, nifty_msg)

        # Step 4: Stock-specific filters
        stock_check = self._check_stock_filters(symbol, kite)
        if not stock_check.is_valid:
            return stock_check

        # Step 5: Price & volume validation (ensure liquid stock)
        # Carried back so caller can reuse instead of calling get_quote again
        quote = None
        if kite:
            liquidity_check = await self._check_liquidity(symbol, kite)
            if not liquidity_check.is_valid:
                return liquidity_check
            quote = liquidity_check.quote

        db = get_db_session()
        try:
            position_repo = PositionRepository(db)

            # Step 6: Duplicate signal / existing position check
            if cfg.get("prevent_duplicate_stocks", True):
                # Check both paper and live - don't trade same stock in either mode
                existing_paper = position_repo.get_by_symbol(
                    symbol=symbol, status="OPEN", paper_trading=True
                )
                existing_live = position_repo.get_by_symbol(
                    symbol=symbol, status="OPEN", paper_trading=False
                )
                if existing_paper or existing_live:
                    return ValidationResult(
                        False,
                        f"Already holding {symbol} (paper: {bool(existing_paper)}, live: {bool(existing_live)})",
                    )

            # Step 7: Max position limit
            signal_cfg = cfg.get("signal_validation", {})
            
            # For paper trading: allow more positions for learning
            if is_paper:
                max_pos = int(cfg.get("paper_trading_filters", {}).get("max_positions", 10))
                count = position_repo.get_position_count(status="OPEN", paper_trading=True)
                if count >= max_pos:
                    return ValidationResult(False, f"Max paper positions ({max_pos}) reached")
            else:
                # Live: stricter limits
                max_pos = int(signal_cfg.get("max_open_positions", 3))
                count = position_repo.get_position_count(status="OPEN", paper_trading=False)
                if count >= max_pos:
                    return ValidationResult(False, f"Max live positions ({max_pos}) reached")

            # Step 8: Consecutive loss check (if recent losses, be more selective)
            recent_performance = self._get_recent_performance(db, is_paper)
            if recent_performance["consecutive_losses"] >= 3:
                # Only allow if nifty is strongly bullish
                if kite:
                    nifty_change = await self._get_nifty_change(kite)
                    if nifty_change < 0.2:  # Need strong nifty for revenge trading
                        return ValidationResult(
                            False,
                            f"Consecutive losses ({recent_performance['consecutive_losses']}), market not bullish enough"
                        )

            # Daily loss limit
            daily_pnl = self._get_daily_pnl(db, is_paper)
            max_loss = -(self.settings.capital * 0.02)  # 2% daily max
            if daily_pnl <= max_loss:
                return ValidationResult(False, f"Daily loss limit hit: ₹{daily_pnl:.2f}")

            logger.info(f"✅ Signal validated for {symbol}: {window_msg}")
            return ValidationResult(True, quote=quote)
        finally:
            db.close()

    async def calculate_position(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        paper_trading: bool = False,
    ) -> Optional[PositionCalculation]:
        """Calculate position size with smart adjustments."""
        cfg = self._load_config()
        
        # Base risk amount
        risk_percent = cfg.get("risk_percent", 1.5)
        risk_amount = self.settings.capital * (risk_percent / 100)

        # Adjust risk based on recent performance
        db = get_db_session()
        try:
            recent = self._get_recent_performance(db, paper_trading)
            
            # If on losing streak, reduce risk
            if recent["consecutive_losses"] >= 2:
                risk_amount *= RISK_REDUCTION_LOSS_STREAK
                logger.info(f"Reducing position size due to {recent['consecutive_losses']} consecutive losses")
            # If on winning streak, slightly increase
            elif recent["consecutive_wins"] >= 3:
                risk_amount *= RISK_INCREASE_WIN_STREAK
                logger.info(f"Increasing position size due to {recent['consecutive_wins']} consecutive wins")
        finally:
            db.close()

        # Calculate SL and TP based on ATR
        sl_distance = atr * self.settings.atr_multiplier_sl
        tp_distance = atr * self.settings.atr_multiplier_tp

        # For high-volatility stocks, use wider SL
        if symbol.upper() in HIGH_RISK_STOCKS:
            sl_distance *= 1.5
            tp_distance *= 1.5
            logger.info(f"Using wider SL/TP for high-risk stock: {symbol}")

        stop_loss = entry_price - sl_distance
        target = entry_price + tp_distance

        # Validate risk-reward ratio
        risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0
        min_rr = cfg.get("risk_management", {}).get("min_risk_reward", 2.0)
        if risk_reward < min_rr:
            logger.warning(f"Risk-reward too low for {symbol}: {risk_reward:.2f} < {min_rr}")
            return None

        risk_per_share = entry_price - stop_loss
        if risk_per_share <= 0:
            logger.warning(f"Invalid SL for {symbol}: entry={entry_price}, SL={stop_loss}")
            return None

        # Calculate quantity
        quantity = int(risk_amount / risk_per_share)
        
        # Cap at trade budget
        trade_budget = cfg.get("trade_budget", self.settings.trade_budget)
        if quantity * entry_price > trade_budget:
            quantity = int(trade_budget / entry_price)
        
        # Ensure minimum quantity
        quantity = max(1, quantity)
        
        # For expensive stocks, ensure at least 1 lot if possible
        if entry_price > EXPENSIVE_STOCK_PRICE and quantity < 1:
            quantity = 1

        return PositionCalculation(
            quantity=quantity,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_amount=risk_amount,
            risk_reward=round(risk_reward, 2),
        )

    def validate_close_position(
        self, position_id: str, current_price: float = 0
    ) -> ValidationResult:
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        from src.api.routes.config import load_config
        return load_config()

    def _is_in_trading_window(self, config: dict) -> tuple:
        now = ist_naive().time()
        trading_windows = config.get("trading_windows", [])

        if trading_windows:
            for window in trading_windows:
                if not window.get("enabled", True):
                    continue
                try:
                    start = datetime.strptime(window.get("start", "10:00"), "%H:%M").time()
                    end = datetime.strptime(window.get("end", "11:30"), "%H:%M").time()
                    if start <= now <= end:
                        return True, "OK"
                except ValueError:
                    continue
            enabled = [w for w in trading_windows if w.get("enabled", True)]
            descs = [f"{w.get('start', '?')}-{w.get('end', '?')}" for w in enabled]
            return False, f"Outside trading windows ({', '.join(descs)})"

        try:
            start_str = (
                config.get("trading_hours", {}).get("start")
                or self.settings.trading_hours_start
            )
            end_str = (
                config.get("trading_hours", {}).get("end")
                or self.settings.trading_hours_end
            )
            start = datetime.strptime(start_str, "%H:%M").time()
            end = datetime.strptime(end_str, "%H:%M").time()
            if start <= now <= end:
                return True, "OK"
            return False, f"Outside trading hours ({start_str}-{end_str})"
        except Exception:
            return True, "OK"

    async def _get_nifty_change(self, kite) -> float:
        try:
            quote = await kite.get_quote("NIFTY 50")
            if quote:
                return quote.change_percent
        except Exception as e:
            logger.warning(f"Could not fetch Nifty change: {e}")
        return 0.0

    def _get_daily_pnl(self, db, is_paper: bool = False) -> float:
        from src.models.database import Trade
        today = ist_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        trades = (
            db.query(Trade)
            .filter(
                Trade.date >= today,
                Trade.status == "CLOSED",
                Trade.paper_trading == is_paper,
            )
            .all()
        )
        return sum(t.pnl or 0 for t in trades)
    
    def _get_recent_performance(self, db, is_paper: bool = False) -> Dict[str, Any]:
        """Get recent trading performance metrics."""
        from src.models.database import Trade
        
        # Get last 10 closed trades
        recent_trades = (
            db.query(Trade)
            .filter(
                Trade.status == "CLOSED",
                Trade.paper_trading == is_paper,
            )
            .order_by(Trade.date.desc())
            .limit(10)
            .all()
        )
        
        if not recent_trades:
            return {"consecutive_losses": 0, "consecutive_wins": 0, "win_rate": 0}
        
        # Count consecutive losses/wins from most recent
        consecutive_losses = 0
        consecutive_wins = 0
        
        for trade in recent_trades:
            if trade.pnl and trade.pnl < 0:
                consecutive_losses += 1
                consecutive_wins = 0
            elif trade.pnl and trade.pnl > 0:
                consecutive_wins += 1
                consecutive_losses = 0
            else:
                break  # Break on zero/None P&L
        
        # Calculate win rate
        closed_trades = [t for t in recent_trades if t.pnl is not None]
        wins = sum(1 for t in closed_trades if t.pnl > 0)
        win_rate = (wins / len(closed_trades) * 100) if closed_trades else 0
        
        return {
            "consecutive_losses": consecutive_losses,
            "consecutive_wins": consecutive_wins,
            "win_rate": win_rate,
            "total_trades": len(closed_trades)
        }
    
    async def _validate_market_health(self, kite: Optional[Any], cfg: dict, is_paper: bool) -> tuple:
        """Validate overall market conditions."""
        signal_cfg = cfg.get("signal_validation", {})
        
        # Skip market check for paper trading (allow learning in all conditions)
        if is_paper:
            return True, "OK"
        
        if not signal_cfg.get("nifty_check_enabled", True):
            return True, "OK"
        
        # Get Nifty 50 change
        nifty_change = await self._get_nifty_change(kite)
        
        # Get Bank Nifty change (more relevant for intraday)
        bank_nifty_change = 0.0
        try:
            quote = await kite.get_quote("NIFTY BANK")
            if quote:
                bank_nifty_change = quote.change_percent
        except Exception as e:
            logger.warning(f"Could not fetch Bank Nifty quote: {e}")
        
        max_decline = float(signal_cfg.get("nifty_max_decline", -0.5))
        
        # If nifty is down significantly, don't trade
        if nifty_change < max_decline:
            return False, f"Nifty weak: {nifty_change:.2f}% (max decline: {max_decline}%)"
        
        # If nifty is flat (< 0.2%), be selective - only trade momentum stocks
        if nifty_change < 0.2:
            return True, "OK (neutral market - will filter for momentum)"
        
        return True, f"OK (Nifty: {nifty_change:.2f}%, BankNifty: {bank_nifty_change:.2f}%)"
    
    def _check_stock_filters(self, symbol: str, kite: Optional[Any]) -> ValidationResult:
        """Check stock-specific filters."""
        # Avoid known high-risk/volatile stocks
        if symbol in HIGH_RISK_STOCKS:
            return ValidationResult(False, f"High-risk stock avoided: {symbol}")
        
        # Basic symbol validation
        if not symbol or len(symbol) < 3:
            return ValidationResult(False, "Invalid symbol")
        
        # Avoid stocks with special characters (F&O stocks should be clean)
        if not symbol.isalnum():
            return ValidationResult(False, f"Symbol contains special characters: {symbol}")
        
        return ValidationResult(True)
    
    async def _check_liquidity(self, symbol: str, kite: Optional[Any]) -> ValidationResult:
        """Check if stock has sufficient liquidity for intraday."""
        try:
            quote = await kite.get_quote(symbol)
            if not quote:
                return ValidationResult(False, f"Could not fetch quote for {symbol}")

            # Check volume (minimum 100k for liquid intraday)
            if quote.volume and quote.volume < MIN_VOLUME:
                return ValidationResult(False, f"Low volume for {symbol}: {quote.volume}", quote)

            # Check if price is reasonable (not too high or too low)
            if quote.ltp < MIN_PRICE:
                return ValidationResult(False, f"Price too low: ₹{quote.ltp}", quote)

            if quote.ltp > MAX_PRICE:
                return ValidationResult(False, f"Price too high: ₹{quote.ltp}", quote)

            return ValidationResult(True, quote=quote)

        except Exception as e:
            logger.warning(f"Liquidity check failed for {symbol}: {e}")
            return ValidationResult(False, f"Liquidity check failed: {e}")


_risk_service: Optional[RiskService] = None


def get_risk_service() -> RiskService:
    global _risk_service
    if _risk_service is None:
        _risk_service = RiskService()
    return _risk_service
