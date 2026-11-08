"""
Integration tests for static dashboard and SPA asset serving on FastAPI.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_root_serves_spa_index(client):
    """Test GET / serves the compiled React single page application."""
    response = client.get("/")
    assert response.status_code == 200
    assert "XAUUSDT Institutional Market Intelligence" in response.text
    assert '<div id="root"></div>' in response.text


def test_spa_route_fallback(client):
    """Test non-API routes fallback to index.html for client-side routing."""
    response = client.get("/signals")
    assert response.status_code == 200
    assert "XAUUSDT Institutional Market Intelligence" in response.text

    response_bt = client.get("/backtest")
    assert response_bt.status_code == 200
    assert "XAUUSDT Institutional Market Intelligence" in response.text


def test_api_routes_not_shadowed(client):
    """Ensure API endpoints are never shadowed by SPA fallback."""
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
