"""
API integration tests for FastAPI backend endpoints.
Verifies GET /api/v1/system/health, /market/overview, /market/candles, /market/prices.
"""

from fastapi.testclient import TestClient
import pytest

from backend.main import app
from backend.data.exchange_verifier import ExchangeVerifier


@pytest.fixture(scope="module")
def client():
    # Prime metadata before testing
    verifier = ExchangeVerifier()
    spec = verifier.verify_contract()
    verifier.persist_metadata(spec)

    with TestClient(app) as test_client:
        yield test_client


def test_system_health_endpoint(client):
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert data["symbol"] == "XAUUSDT"
    assert data["database_connected"] is True
    assert "tradfi_session_state" in data
    assert "data_freshness" in data
    assert "latest_candle_time" in data["data_freshness"]


def test_market_overview_endpoint(client):
    response = client.get("/api/v1/market/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "XAUUSDT"
    assert data["metadata"] is not None
    assert data["metadata"]["tick_size"] == 0.01
    assert data["metadata"]["step_size"] == 0.001


def test_market_candles_endpoint(client):
    # Fetch 1m candles previously inserted
    response = client.get("/api/v1/market/candles?timeframe=1m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        assert "open" in data[0]
        assert "high" in data[0]
        assert "low" in data[0]
        assert "close" in data[0]
        assert "volume" in data[0]


def test_market_prices_endpoint(client):
    response = client.get("/api/v1/market/prices")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "XAUUSDT"
