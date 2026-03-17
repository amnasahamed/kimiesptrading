"""
Tests for ChartInk webhook route.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


def _now_window():
    now = datetime.now()
    start_h, start_m = divmod(now.hour * 60 + max(0, now.minute - 30), 60)
    end_h, end_m = divmod(now.hour * 60 + min(now.minute + 30, 59), 60)
    return [{"start": f"{start_h:02d}:{start_m:02d}",
             "end": f"{end_h:02d}:{end_m:02d}", "enabled": True}]


def _make_config(secret="", system_enabled=True, **kwargs):
    cfg = {
        "system_enabled": system_enabled,
        "paper_trading": True,
        "prevent_duplicate_stocks": False,
        "chartink": {"webhook_secret": secret},
        "trading_windows": _now_window(),
        "signal_validation": {"max_open_positions": 3, "nifty_check_enabled": False},
        "paper_trading_filters": {"max_positions": 20},
    }
    cfg.update(kwargs)
    return cfg


def _rejected_result(reason: str = "Test rejection"):
    return {"status": "REJECTED", "symbol": "RELIANCE", "reason": reason}


def _mock_db_alert():
    mock = MagicMock()
    mock.id = "ALT_TEST_123"
    return mock


@pytest.fixture
def test_client(app):
    return TestClient(app, raise_server_exceptions=False)


# Patch paths — must match where the name is *used*, not where it's defined
CONFIG_PATCH = "src.api.routes.config.load_config"
RECORD_PATCH = "src.api.routes.webhook.record_alert"
UPDATE_PATCH = "src.api.routes.webhook.update_status"
TRADING_SVC_PATCH = "src.api.routes.webhook.get_trading_service"
DB_SESSION_PATCH = "src.api.routes.webhook.get_db_session"


def _db_session_mock():
    """Mock get_db_session to avoid hitting a real DB in webhook tests."""
    mock_session = MagicMock()
    mock_session.close = MagicMock()
    return mock_session


class TestWebhookJSON:
    def test_valid_payload(self, test_client):
        """Valid payload should return 200."""
        with patch(CONFIG_PATCH, return_value=_make_config()):
            with patch(DB_SESSION_PATCH, return_value=_db_session_mock()):
                with patch(RECORD_PATCH, new_callable=AsyncMock, return_value=_mock_db_alert()):
                    with patch(UPDATE_PATCH, new_callable=AsyncMock):
                        with patch(TRADING_SVC_PATCH) as mock_ts:
                            mock_ts.return_value.process_signal = AsyncMock(
                                return_value=_rejected_result()
                            )
                            resp = test_client.post(
                                "/webhook/chartink",
                                json={"stocks": "RELIANCE", "trigger_prices": "2500.00",
                                      "scan_name": "Test"},
                            )
        assert resp.status_code == 200

    def test_invalid_secret_returns_401(self, test_client):
        """Wrong webhook secret should return 401."""
        with patch(CONFIG_PATCH, return_value=_make_config(secret="correct-secret")):
            with patch(DB_SESSION_PATCH, return_value=_db_session_mock()):
                with patch(RECORD_PATCH, new_callable=AsyncMock, return_value=_mock_db_alert()):
                    with patch(UPDATE_PATCH, new_callable=AsyncMock):
                        resp = test_client.post(
                            "/webhook/chartink",
                            json={"stocks": "RELIANCE", "trigger_prices": "2500.00",
                                  "secret": "wrong-secret"},
                        )
        assert resp.status_code == 401

    def test_malformed_no_stocks(self, test_client):
        """Payload with no valid stocks → REJECTED."""
        with patch(CONFIG_PATCH, return_value=_make_config()):
            with patch(DB_SESSION_PATCH, return_value=_db_session_mock()):
                with patch(RECORD_PATCH, new_callable=AsyncMock, return_value=_mock_db_alert()):
                    with patch(UPDATE_PATCH, new_callable=AsyncMock):
                        resp = test_client.post(
                            "/webhook/chartink",
                            json={"stocks": "", "trigger_prices": ""},
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("REJECTED", "ALL_REJECTED")

    def test_trading_disabled_logs_signal(self, test_client):
        """When system disabled, signal logged as REJECTED."""
        with patch(CONFIG_PATCH, return_value=_make_config(system_enabled=False)):
            with patch(DB_SESSION_PATCH, return_value=_db_session_mock()):
                with patch(RECORD_PATCH, new_callable=AsyncMock, return_value=_mock_db_alert()):
                    with patch(UPDATE_PATCH, new_callable=AsyncMock):
                        with patch(TRADING_SVC_PATCH) as mock_ts:
                            mock_ts.return_value.process_signal = AsyncMock(
                                return_value=_rejected_result("System is disabled")
                            )
                            resp = test_client.post(
                                "/webhook/chartink",
                                json={"stocks": "RELIANCE", "trigger_prices": "2500"},
                            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "REJECTED"

    def test_rate_limit_returns_429(self, test_client):
        """After RATE_LIMIT calls, next should return 429."""
        from src.api.routes import webhook
        webhook._webhook_calls.clear()
        # TestClient uses "testclient" as host
        ip = "testclient"
        webhook._webhook_calls[ip] = [datetime.now()] * webhook.RATE_LIMIT

        with patch(DB_SESSION_PATCH, return_value=_db_session_mock()):
            with patch(RECORD_PATCH, new_callable=AsyncMock, return_value=_mock_db_alert()):
                resp = test_client.post(
                    "/webhook/chartink",
                    json={"stocks": "RELIANCE", "trigger_prices": "2500"},
                )
        assert resp.status_code == 429
        webhook._webhook_calls.clear()


class TestWebhookStatus:
    def test_get_webhook_status(self, test_client):
        resp = test_client.get("/webhook/chartink")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "active"
