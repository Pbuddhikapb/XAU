"""
Integration tests for Phase 4 Engine B Setup Endpoints.
Verifies:
- GET /api/v1/setups/current (active setups or explicit NO_SETUP payload)
- GET /api/v1/setups/history (historical setups with filtering by direction, status, limit)
Conforms to Section 7, 8, & 10 of PROJECT_SPECIFICATION.md:
- Explicit NO_SETUP response with reason when nothing qualifies.
- Trade setup fields: entry zone, stop loss, targets T1-T3, net R:R >= 1.5.
- Active stop loss and breakeven tracking.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_setups_current_live_endpoint(client):
    """Verify GET /api/v1/setups/current executes cleanly and returns valid structure."""
    response = client.get("/api/v1/setups/current?symbol=XAUUSDT")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "XAUUSDT"
    assert "has_active_setup" in data
    assert "no_setup" in data

    if data["no_setup"]:
        assert "reason" in data
        assert "data_quality_score" in data
        assert "market_regime" in data
        assert data["methodology_version"] == settings.DECISION_METHODOLOGY_VERSION
        assert data["setups"] == []
    else:
        assert data["has_active_setup"] is True
        assert len(data["setups"]) >= 1
        s = data["setups"][0]
        assert "setup_id" in s
        assert "entry_zone_min" in s
        assert "stop_loss" in s
        assert "target_1" in s
        assert "breakeven_locked" in s


def test_setups_current_no_setup_mock(client):
    """Verify GET /api/v1/setups/current returns explicit NO_SETUP format when no setups qualify."""
    mock_no_setup = {
        "symbol": "XAUUSDT",
        "has_active_setup": False,
        "no_setup": True,
        "reason": "DATA_QUALITY_BELOW_THRESHOLD",
        "direction": "NEUTRAL",
        "data_quality_score": 50.0,
        "market_regime": "RANGE_BOUND",
        "assessment_time": "2026-11-07T12:00:00+00:00",
        "methodology_version": settings.DECISION_METHODOLOGY_VERSION,
        "setups": [],
        "source": "COMPUTED",
    }

    with patch(
        "backend.decision.orchestrator.DecisionOrchestrator.get_or_compute_current_setups",
        new=AsyncMock(return_value=mock_no_setup),
    ):
        response = client.get("/api/v1/setups/current?symbol=XAUUSDT")
        assert response.status_code == 200
        data = response.json()

        assert data["no_setup"] is True
        assert data["has_active_setup"] is False
        assert data["reason"] == "DATA_QUALITY_BELOW_THRESHOLD"
        assert data["setups"] == []


def test_setups_current_active_setup_mock(client):
    """Verify GET /api/v1/setups/current returns active setups with breakeven tracking."""
    mock_active = {
        "symbol": "XAUUSDT",
        "has_active_setup": True,
        "no_setup": False,
        "count": 1,
        "setups": [
            {
                "setup_id": "11111111-1111-1111-1111-111111111111",
                "symbol": "XAUUSDT",
                "created_at": "2026-11-07T12:00:00+00:00",
                "status": "CONFIRMED",
                "setup_type": "TREND_CONTINUATION",
                "direction": "LONG",
                "timeframe": "1h",
                "entry_zone_min": 2700.0,
                "entry_zone_max": 2705.0,
                "stop_loss": 2685.0,
                "target_1": 2735.0,
                "target_2": 2755.0,
                "target_3": 2780.0,
                "risk_reward_ratio": 1.85,
                "expiration_time": "2026-11-07T22:00:00+00:00",
                "invalidation_conditions": "Close below 2685.0",
                "supporting_evidence": [{"factor": "Trend Alignment"}],
                "estimated_fees_pct": 0.0010,
                "methodology_version": settings.DECISION_METHODOLOGY_VERSION,
                "active_stop_loss": None,
                "breakeven_locked": False,
            }
        ],
        "source": "COMPUTED",
    }

    with patch(
        "backend.decision.orchestrator.DecisionOrchestrator.get_or_compute_current_setups",
        new=AsyncMock(return_value=mock_active),
    ):
        response = client.get("/api/v1/setups/current?symbol=XAUUSDT")
        assert response.status_code == 200
        data = response.json()

        assert data["has_active_setup"] is True
        assert data["no_setup"] is False
        assert len(data["setups"]) == 1
        s = data["setups"][0]
        assert s["direction"] == "LONG"
        assert s["risk_reward_ratio"] == 1.85
        assert s["breakeven_locked"] is False


def test_setups_history_endpoint(client):
    """Verify GET /api/v1/setups/history returns a list of setup records with filter params."""
    response = client.get("/api/v1/setups/history?symbol=XAUUSDT&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_setups_history_filtered_mock(client):
    """Verify GET /api/v1/setups/history filters by direction and status correctly."""
    mock_history = [
        {
            "setup_id": "22222222-2222-2222-2222-222222222222",
            "symbol": "XAUUSDT",
            "created_at": "2026-11-07T10:00:00+00:00",
            "status": "TARGET_HIT",
            "setup_type": "TREND_CONTINUATION",
            "direction": "LONG",
            "timeframe": "1h",
            "entry_zone_min": 2700.0,
            "entry_zone_max": 2705.0,
            "stop_loss": 2685.0,
            "target_1": 2735.0,
            "target_2": 2755.0,
            "target_3": 2780.0,
            "risk_reward_ratio": 1.85,
            "expiration_time": "2026-11-07T20:00:00+00:00",
            "invalidation_conditions": "Close below 2685.0",
            "supporting_evidence": [],
            "estimated_fees_pct": 0.0010,
            "methodology_version": settings.DECISION_METHODOLOGY_VERSION,
            "active_stop_loss": 2702.5,
            "breakeven_locked": True,
        }
    ]

    with patch(
        "backend.decision.orchestrator.DecisionOrchestrator.get_setups_history",
        new=AsyncMock(return_value=mock_history),
    ):
        response = client.get("/api/v1/setups/history?symbol=XAUUSDT&direction=LONG&status=TARGET_HIT")
        assert response.status_code == 200
        data = response.json()

        assert len(data) == 1
        assert data[0]["direction"] == "LONG"
        assert data[0]["status"] == "TARGET_HIT"
        assert data[0]["breakeven_locked"] is True
        assert data[0]["active_stop_loss"] == 2702.5
