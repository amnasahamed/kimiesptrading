"""
Tests for RiskService — 5-step signal validation.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from src.services.risk_service import RiskService, ValidationResult


def _now_window():
    """Return a trading_windows list that always includes the current time."""
    now = datetime.now()
    start = f"{now.hour:02d}:{max(0, now.minute - 30):02d}"
    end = f"{now.hour:02d}:{min(59, now.minute + 30):02d}"
    # Handle edge case where minute ± 30 crosses hour boundary
    start_h, start_m = divmod(now.hour * 60 + max(0, now.minute - 30), 60)
    end_h, end_m = divmod(now.hour * 60 + min(now.minute + 30, 59), 60)
    return [{"start": f"{start_h:02d}:{start_m:02d}", "end": f"{end_h:02d}:{end_m:02d}", "enabled": True}]


def _make_config(**kwargs):
    base = {
        "system_enabled": True,
        "paper_trading": True,
        "prevent_duplicate_stocks": True,
        "trading_windows": _now_window(),  # always within current time
        "signal_validation": {
            "max_open_positions": 3,
            "nifty_check_enabled": False,
            "prevent_daily_duplicates": True,
        },
        "paper_trading_filters": {"max_positions": 20},
    }
    base.update(kwargs)
    return base


@pytest.fixture
def risk_service(db_session):
    svc = RiskService()
    return svc


class TestValidateSignal:
    @pytest.mark.asyncio
    async def test_system_disabled(self, risk_service, db_session):
        cfg = _make_config(system_enabled=False)
        with patch.object(risk_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                result = await risk_service.validate_signal("RELIANCE", is_paper=True, config=cfg)
        assert not result.is_valid
        assert "disabled" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_outside_trading_hours(self, risk_service, db_session):
        # Use a window definitively in the past (00:00–00:01) that can never be current time
        cfg = _make_config(trading_windows=[{"start": "00:00", "end": "00:01", "enabled": True}])
        with patch.object(risk_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                result = await risk_service.validate_signal("RELIANCE", is_paper=True, config=cfg)
        assert not result.is_valid
        assert "outside" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_max_paper_positions_reached(self, risk_service, db_session):
        cfg = _make_config(paper_trading_filters={"max_positions": 0})
        with patch.object(risk_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                result = await risk_service.validate_signal("RELIANCE", is_paper=True, config=cfg)
        assert not result.is_valid
        assert "max paper" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_max_live_positions_reached(self, risk_service, db_session):
        cfg = _make_config(signal_validation={"max_open_positions": 0, "nifty_check_enabled": False})
        with patch.object(risk_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                result = await risk_service.validate_signal("RELIANCE", is_paper=False, config=cfg)
        assert not result.is_valid
        assert "max live" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_nifty_health_check(self, risk_service, db_session):
        """Reject when Nifty is too weak (live mode)."""
        cfg = _make_config(signal_validation={
            "max_open_positions": 3,
            "nifty_check_enabled": True,
            "nifty_max_decline": -0.3,
        })
        mock_kite = MagicMock()
        mock_kite.get_quote = AsyncMock(
            return_value=MagicMock(change_percent=-1.5)
        )
        with patch.object(risk_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                result = await risk_service.validate_signal(
                    "RELIANCE", is_paper=False, kite=mock_kite, config=cfg
                )
        assert not result.is_valid
        assert "nifty" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_valid_signal_passes(self, risk_service, db_session):
        """A valid signal should pass all checks."""
        # Use trading_windows that contain current time
        now = datetime.now()
        start = f"{now.hour:02d}:{max(0, now.minute - 5):02d}"
        end = f"{now.hour:02d}:{min(59, now.minute + 5):02d}"
        cfg = _make_config(
            trading_windows=[{"start": start, "end": end, "enabled": True}],
            prevent_duplicate_stocks=False,
        )
        with patch.object(risk_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                result = await risk_service.validate_signal("RELIANCE", is_paper=True, config=cfg)
        assert result.is_valid


class TestCalculatePosition:
    @pytest.mark.asyncio
    async def test_calculates_reasonable_quantity(self):
        svc = RiskService()
        result = await svc.calculate_position("RELIANCE", entry_price=2500, atr=50)
        assert result is not None
        assert result.quantity >= 1
        assert result.stop_loss < 2500
        assert result.target > 2500
        assert result.risk_reward > 0

    @pytest.mark.asyncio
    async def test_returns_none_for_zero_atr(self):
        svc = RiskService()
        result = await svc.calculate_position("RELIANCE", entry_price=2500, atr=0)
        assert result is None
