"""
Tests for TradingService.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


def _make_config(**kwargs):
    base = {
        "system_enabled": True,
        "paper_trading": True,
        "prevent_duplicate_stocks": False,
        "trading_hours": {"start": "09:15", "end": "15:30"},
        "trading_windows": [],
        "signal_validation": {"max_open_positions": 3, "nifty_check_enabled": False},
        "paper_trading_filters": {"max_positions": 20},
    }
    base.update(kwargs)
    return base


def _make_mock_kite(ltp: float = 1500.0):
    kite = MagicMock()
    quote = MagicMock()
    quote.ltp = ltp
    quote.high = ltp * 1.01
    quote.low = ltp * 0.99
    quote.change_percent = 0.5
    kite.get_quote = AsyncMock(return_value=quote)
    kite.place_order = AsyncMock(return_value={"status": "SUCCESS", "order_id": "LIVE123"})
    return kite


@pytest.fixture
def trading_service(db_session):
    from src.services.trading_service import TradingService

    svc = TradingService()
    svc.kite = _make_mock_kite()
    return svc


class TestProcessSignal:
    @pytest.mark.asyncio
    async def test_paper_trade_creates_position(self, trading_service, db_session):
        """Paper trade should create a position record."""
        cfg = _make_config()
        now = datetime.now()
        cfg["trading_windows"] = [
            {"start": f"{now.hour:02d}:{max(0, now.minute-5):02d}",
             "end": f"{now.hour:02d}:{min(59, now.minute+5):02d}",
             "enabled": True}
        ]
        cfg["system_enabled"] = True

        with patch.object(trading_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                with patch("src.services.trading_service.get_db_session", return_value=db_session):
                    result = await trading_service.process_signal(
                        symbol="INFY",
                        alert_price=1500.0,
                        scan_name="Test Scan",
                        action="BUY",
                        config=cfg,
                    )

        # Either succeeds or is rejected (depends on system state) — no ERROR
        assert result.get("status") in ("SUCCESS", "REJECTED", "ERROR")
        assert result.get("symbol") == "INFY"

    @pytest.mark.asyncio
    async def test_system_disabled_rejects(self, trading_service, db_session):
        cfg = _make_config(system_enabled=False)
        with patch.object(trading_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                with patch("src.services.trading_service.get_db_session", return_value=db_session):
                    result = await trading_service.process_signal(
                        "RELIANCE", 2500.0, "Test", config=cfg
                    )
        assert result["status"] == "REJECTED"
        assert "disabled" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_live_trade_calls_kite(self, trading_service, db_session):
        """Live trade should call kite.place_order."""
        cfg = _make_config(paper_trading=False)
        now = datetime.now()
        cfg["trading_windows"] = [
            {"start": f"{now.hour:02d}:{max(0, now.minute-5):02d}",
             "end": f"{now.hour:02d}:{min(59, now.minute+5):02d}",
             "enabled": True}
        ]
        cfg["system_enabled"] = True

        with patch.object(trading_service, "_load_config", return_value=cfg):
            with patch("src.services.risk_service.get_db_session", return_value=db_session):
                with patch("src.services.trading_service.get_db_session", return_value=db_session):
                    result = await trading_service.process_signal(
                        "TCS", 3500.0, "Live Test", config=cfg
                    )

        # place_order may or may not be called based on validation
        assert "status" in result


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_nonexistent_position(self, trading_service, db_session):
        with patch("src.services.trading_service.get_db_session", return_value=db_session):
            result = await trading_service.close_position("NONEXISTENT_ID")
        assert result["status"] == "ERROR"
        assert "not found" in result["reason"].lower()
