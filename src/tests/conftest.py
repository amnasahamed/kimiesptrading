"""
Test configuration and fixtures.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from src.models.database import Base, get_db


# ---------------------------------------------------------------------------
# In-memory SQLite DB fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Mock KiteService
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_kite():
    kite = MagicMock()
    kite.get_quote = AsyncMock(return_value=None)
    kite.get_funds = AsyncMock(return_value=None)
    kite.place_order = AsyncMock(return_value={"status": "SUCCESS", "order_id": "MOCK123"})
    return kite


# ---------------------------------------------------------------------------
# Sample ChartInk payloads
# ---------------------------------------------------------------------------
VALID_PAYLOAD = {
    "stocks": "RELIANCE",
    "trigger_prices": "2500.00",
    "scan_name": "Test Breakout",
    "triggered_at": "10:05 am",
    "secret": "test-secret",
}

INVALID_SECRET_PAYLOAD = {
    "stocks": "RELIANCE",
    "trigger_prices": "2500.00",
    "scan_name": "Test",
    "secret": "wrong-secret",
}

MALFORMED_PAYLOAD = {
    "stocks": "",
    "trigger_prices": "",
}

DUPLICATE_PAYLOAD = {
    "stocks": "INFY",
    "trigger_prices": "1500.00",
    "scan_name": "Duplicate Test",
    "secret": "test-secret",
}

OUT_OF_HOURS_PAYLOAD = {
    "stocks": "TCS",
    "trigger_prices": "3500.00",
    "scan_name": "Out of Hours Test",
    "secret": "test-secret",
}


# ---------------------------------------------------------------------------
# App fixture with DB override
# ---------------------------------------------------------------------------
@pytest.fixture
def app(db_session):
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

    from src.main import create_app
    _app = create_app()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    _app.dependency_overrides[get_db] = override_get_db
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)
