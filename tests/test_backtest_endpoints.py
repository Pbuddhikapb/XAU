"""
Integration tests for Phase 5 Backtest & Signal Horizon Endpoints.
Verifies:
- GET /api/v1/backtests
- GET /api/v1/backtests/{run_id}
- POST /api/v1/backtests/run
- GET /api/v1/signals/history
Conforms to Section 8 & 10 of PROJECT_SPECIFICATION.md.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_get_backtests_list(client):
    """Verify GET /api/v1/backtests returns 200 and list structure."""
    response = client.get("/api/v1/backtests?symbol=XAUUSDT&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_backtest_detail_not_found(client):
    """Verify GET /api/v1/backtests/{run_id} returns 404 for unknown run_id."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/v1/backtests/{fake_id}")
    assert response.status_code == 404
    assert f"Backtest run {fake_id} not found" in response.json()["detail"]


def test_get_backtest_detail_mocked(client):
    """Verify GET /api/v1/backtests/{run_id} returns full run metrics and config."""
    mock_id = uuid.uuid4()
    mock_detail = {
        "run_id": str(mock_id),
        "name": "Mock-WalkForward-Run",
        "start_time": "2026-01-01T00:00:00+00:00",
        "end_time": "2026-06-01T00:00:00+00:00",
        "in_sample_end": "2026-04-15T00:00:00+00:00",
        "timeframes": ["1h", "5m", "4h", "1d", "15m"],
        "strategy_config": {"risk_per_trade_pct": 0.01},
        "trading_costs_config": {"total_friction": 0.0014},
        "methodology_version": "v1.2.0-phase5",
        "executed_at": "2026-11-07T12:00:00+00:00",
        "metrics": {
            "total_trades": 24,
            "win_rate": 62.5,
            "profit_factor": 2.15,
            "expectancy": 450.0,
            "max_drawdown": 6.8,
            "sharpe_ratio": 1.85,
            "precision": 62.5,
            "recall": 100.0,
            "long_win_rate": 66.7,
            "short_win_rate": 58.3,
            "metrics_by_timeframe": {},
            "metrics_by_regime": {},
        },
    }

    with patch(
        "backend.backtest.persistence.BacktestPersistence.get_backtest_run_detail",
        new=AsyncMock(return_value=mock_detail),
    ):
        response = client.get(f"/api/v1/backtests/{mock_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == str(mock_id)
        assert data["metrics"]["win_rate"] == 62.5
        assert data["metrics"]["profit_factor"] == 2.15


def test_post_backtests_run_mocked(client):
    """Verify POST /api/v1/backtests/run triggers backtest and returns metrics summary."""
    mock_id = uuid.uuid4()
    mock_run_result = {
        "run_id": str(mock_id),
        "name": "Integration-Run-Test",
        "symbol": "XAUUSDT",
        "total_trades": 18,
        "win_rate": 61.11,
        "profit_factor": 1.95,
        "expectancy": 380.0,
        "max_drawdown": 5.4,
        "sharpe_ratio": 1.72,
        "precision": 61.11,
        "recall": 100.0,
        "in_sample_metrics": {"total_trades": 12, "win_rate": 66.67},
        "out_of_sample_metrics": {"total_trades": 6, "win_rate": 50.0},
        "walk_forward_folds": [],
        "signal_outcomes_count": 48,
    }

    payload = {
        "name": "Integration-Run-Test",
        "symbol": "XAUUSDT",
        "in_sample_ratio": 0.70,
        "walk_forward_folds": 3,
        "initial_capital": 100_000.0,
        "risk_per_trade_pct": 0.01,
    }

    with patch(
        "backend.backtest.runner.BacktestRunner.execute_and_persist",
        new=AsyncMock(return_value=mock_run_result),
    ):
        response = client.post("/api/v1/backtests/run", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == str(mock_id)
        assert data["total_trades"] == 18
        assert data["win_rate"] == 61.11


def test_get_signals_history(client):
    """Verify GET /api/v1/signals/history returns list with horizon filtering."""
    response = client.get("/api/v1/signals/history?horizon=20&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
