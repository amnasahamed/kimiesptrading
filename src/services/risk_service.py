"""
Risk management service — 5-step signal validation and position sizing.
"""
from datetime import datetime
from typing import Optional, NamedTuple

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
    """Risk management service — 5-step validation + position sizing."""

    def __init__(self):
        self.settings = get_settings()

    async def validate_signal(
        self,
        symbol: str,
        is_paper: bool = False,
        kite=None,
        config: Optional[dict] = None,
    ) -> ValidationResult:
        """
        5-step signal validation:
          1. System enabled check
          2. Trading window check
          3. Nifty health check (live only, if kite provided)
          4. Duplicate / existing position check
          5. Max position limit check
        Price slippage validated separately in trading_service.
        """
        cfg = config or self._load_config()

        # Step 1: System enabled
        if not cfg.get("system_enabled", False):
            return ValidationResult(False, "System is disabled")

        # Step 2: Trading window
        in_window, window_msg = self._is_in_trading_window(cfg)
        if not in_window:
            return ValidationResult(False, window_msg)

        # Step 3: Nifty health (live only)
        if not is_paper and kite:
            signal_cfg = cfg.get("signal_validation", {})
            if signal_cfg.get("nifty_check_enabled", True):
                nifty_change = await self._get_nifty_change(kite)
                max_decline = float(signal_cfg.get("nifty_max_decline", -0.3))
                if nifty_change < max_decline:
                    return ValidationResult(
                        False,
                        f"Nifty weak: {nifty_change:.2f}% (threshold {max_decline}%)",
                    )

        db = get_db_session()
        try:
            position_repo = PositionRepository(db)

            # Step 4: Duplicate signal / existing position check
            if cfg.get("prevent_duplicate_stocks", True):
                existing = position_repo.get_by_symbol(
                    symbol=symbol, status="OPEN", paper_trading=is_paper
                )
                if existing:
                    return ValidationResult(
                        False,
                        f"Already holding {symbol} in {'paper' if is_paper else 'live'} mode",
                    )

            # Step 5: Max position limit
            signal_cfg = cfg.get("signal_validation", {})
            if is_paper:
                max_pos = int(cfg.get("paper_trading_filters", {}).get("max_positions", 20))
                count = position_repo.get_position_count(status="OPEN", paper_trading=True)
                if count >= max_pos:
                    return ValidationResult(False, f"Max paper positions ({max_pos}) reached")
            else:
                max_pos = int(signal_cfg.get("max_open_positions", 3))
                count = position_repo.get_position_count(status="OPEN", paper_trading=False)
                if count >= max_pos:
                    return ValidationResult(False, f"Max live positions ({max_pos}) reached")

            # Daily loss limit (live only)
            if not is_paper:
                daily_pnl = self._get_daily_pnl(db)
                max_loss = -(self.settings.capital * 0.03)
                if daily_pnl <= max_loss:
                    return ValidationResult(False, f"Daily loss limit hit: ₹{daily_pnl:.2f}")

            return ValidationResult(True)
        finally:
            db.close()

    async def calculate_position(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        paper_trading: bool = False,
    ) -> Optional[PositionCalculation]:
        """Calculate position size based on risk parameters."""
        risk_amount = self.settings.capital * (self.settings.risk_percent / 100)

        sl_distance = atr * self.settings.atr_multiplier_sl
        tp_distance = atr * self.settings.atr_multiplier_tp

        stop_loss = entry_price - sl_distance
        target = entry_price + tp_distance

        risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0
        if risk_reward < self.settings.min_risk_reward:
            logger.warning(f"Risk-reward too low for {symbol}: {risk_reward:.2f}")
            return None

        risk_per_share = entry_price - stop_loss
        if risk_per_share <= 0:
            return None

        quantity = int(risk_amount / risk_per_share)
        if quantity * entry_price > self.settings.trade_budget:
            quantity = int(self.settings.trade_budget / entry_price)
        quantity = max(1, quantity)

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
        now = datetime.now().time()
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

    def _get_daily_pnl(self, db) -> float:
        from src.models.database import Trade
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        trades = (
            db.query(Trade)
            .filter(
                Trade.date >= today,
                Trade.status == "CLOSED",
                Trade.paper_trading == False,
            )
            .all()
        )
        return sum(t.pnl or 0 for t in trades)


_risk_service: Optional[RiskService] = None


def get_risk_service() -> RiskService:
    global _risk_service
    if _risk_service is None:
        _risk_service = RiskService()
    return _risk_service
