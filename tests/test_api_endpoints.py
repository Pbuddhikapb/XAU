"""
API integration tests for FastAPI backend endpoints.
Verifies GET /api/v1/system/health, /market/overview, /market/candles, /market/prices.
"""

import pytest
from fastapi.testclient import TestClient

from backend.data.exchange_verifier import ExchangeVerifier
from backend.main import app


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


def test_analytics_indicators_endpoint(client):
    response = client.get("/api/v1/analytics/indicators?timeframe=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        assert "ema_20" in data[0]
        assert "rsi_14" in data[0]
        assert "vwap" in data[0]


def test_analytics_divergences_endpoint(client):
    response = client.get("/api/v1/analytics/divergences?timeframe=1h&indicator=RSI")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_analytics_regime_endpoint(client):
    response = client.get("/api/v1/analytics/regime?timeframe=1h")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "XAUUSDT"
    assert "status" in data or "trend" in data


def test_structure_events_endpoint(client):
    response = client.get("/api/v1/structure/events?timeframe=1h&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_structure_levels_endpoint(client):
    response = client.get("/api/v1/structure/levels?timeframe=1h")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_structure_mtf_endpoint(client):
    response = client.get("/api/v1/structure/mtf")
    assert response.status_code == 200
    data = response.json()
    assert "alignment_state" in data
    assert "compound_score" in data
    assert "timeframes" in data
