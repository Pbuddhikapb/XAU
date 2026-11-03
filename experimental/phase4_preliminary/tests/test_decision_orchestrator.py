"""
Integration tests for DecisionOrchestrator and Phase 4 FastAPI Endpoints.
Strictly tests Section 6, 7, 8, 9, and 10 of PROJECT_SPECIFICATION.md:
- Full end-to-end execution of DecisionOrchestrator.
- PostgreSQL persistence into market_analysis and trade_setups tables.
- Verification of REST endpoints:
  * GET /api/v1/analysis/current
  * GET /api/v1/analysis/timeframes
  * GET /api/v1/analysis/evidence
  * GET /api/v1/setups/current
  * GET /api/v1/setups/history
"""

import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    ScoreBreakdown,
    SetupStatus,
    SetupType,
    TradeDirection,
    TradeSetupModel,
)
from backend.decision.orchestrator import DecisionOrchestrator
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_multi_tf_candles(n: int = 60) -> dict[str, pd.DataFrame]:
    raw_data = {}
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)

    for tf in ["1d", "4h", "1h", "15m", "5m"]:
        times = [base_time + timedelta(hours=i) for i in range(n)]
        prices = []
        for i in range(n):
            cycle = i % 8
            wave = 3.0 * (cycle if cycle < 5 else (8 - cycle))
            p = 2650.0 + (i * 2.0) + wave
            prices.append(p)

        raw_data[tf] = pd.DataFrame(
            {
                "open_time": times,
                "open": [p - 1.0 for p in prices],
                "high": [p + 3.0 for p in prices],
                "low": [p - 3.0 for p in prices],
                "close": prices,
                "volume": [200.0 + (i * 2.0) for i in range(n)],
                "taker_buy_volume": [(200.0 + (i * 2.0)) * 0.65 for i in range(n)],
            }
        )
    return raw_data


def test_orchestrator_process_timeframe_data():
    """Verify end-to-end pipeline execution across multi-timeframe inputs during active market hours."""
    raw_tf = make_multi_tf_candles(60)
    # Wednesday 14:00 UTC is an active CME TradFi gold market session
    active_wednesday = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)
    assessment, setups = DecisionOrchestrator.process_timeframe_data(
        raw_candles_by_tf=raw_tf,
        symbol="XAUUSDT",
        as_of_time=active_wednesday,
        is_live=True,
    )

    assert isinstance(assessment, DirectionAssessment)
    assert assessment.symbol == "XAUUSDT"
    assert assessment.direction in [DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH]
    assert assessment.bullish_score >= 50.0
    assert assessment.data_quality_score >= 80.0
    assert isinstance(setups, list)


@pytest.mark.asyncio
async def test_orchestrator_persistence():
    """Verify persisting DirectionAssessment and TradeSetups to PostgreSQL."""
    now = datetime.now(UTC)
    assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=now,
        direction=DirectionType.BULLISH,
        bullish_score=80.0,
        bearish_score=15.0,
        breakdown=ScoreBreakdown(
            structure_score=20.0,
            mtf_trend_score=18.0,
            momentum_score=12.0,
            volume_score=12.0,
            volatility_pa_score=10.0,
            liquidity_score=8.0,
            total_bullish=80.0,
            total_bearish=15.0,
        ),
        supporting_evidence=[{"factor": "Trend", "desc": "Bullish"}],
        contradicting_evidence=[],
        timeframe_alignment={"1h": "BULLISH"},
        key_levels={"vwap": 2710.0},
        invalidation_conditions="Close below 2680.0",
        data_quality_score=95.0,
        is_live=True,
    )

    setup = TradeSetupModel(
        setup_id=uuid.uuid4(),
        symbol="XAUUSDT",
        created_at=now,
        status=SetupStatus.IDENTIFIED,
        setup_type=SetupType.TREND_CONTINUATION,
        direction=TradeDirection.LONG,
        timeframe="1h",
        entry_zone_min=2700.0,
        entry_zone_max=2705.0,
        stop_loss=2685.0,
        target_1=2735.0,
        target_2=2755.0,
        target_3=2780.0,
        risk_reward_ratio=1.75,
        expiration_time=now + timedelta(hours=10),
        invalidation_conditions="Close below 2685.0",
        supporting_evidence=[{"test": True}],
    )

    success_assess = await DecisionOrchestrator.persist_assessment(assessment)
    assert success_assess is True

    persisted_setups_count = await DecisionOrchestrator.persist_setups([setup])
    assert persisted_setups_count == 1


def test_api_analysis_current_endpoint(client):
    """Verify GET /api/v1/analysis/current endpoint returns valid DirectionAssessment structure."""
    response = client.get("/api/v1/analysis/current")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "XAUUSDT"
    assert "direction" in data
    assert "bullish_score" in data
    assert "bearish_score" in data
    assert "breakdown" in data
    assert "supporting_evidence" in data
    assert "contradicting_evidence" in data
    assert "invalidation_conditions" in data
    assert "data_quality_score" in data


def test_api_analysis_timeframes_endpoint(client):
    """Verify GET /api/v1/analysis/timeframes endpoint returns timeframe breakdown."""
    response = client.get("/api/v1/analysis/timeframes")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "XAUUSDT"
    assert "overall_direction" in data
    assert "timeframe_alignment" in data


def test_api_analysis_evidence_endpoint(client):
    """Verify GET /api/v1/analysis/evidence returns structured citations."""
    response = client.get("/api/v1/analysis/evidence")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "XAUUSDT"
    assert "supporting_evidence" in data
    assert "contradicting_evidence" in data
    assert "invalidation_conditions" in data


def test_api_setups_current_endpoint(client):
    """Verify GET /api/v1/setups/current returns list of active setups."""
    response = client.get("/api/v1/setups/current")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for s in data:
        assert "setup_id" in s
        assert "setup_type" in s
        assert "entry_zone_min" in s
        assert "stop_loss" in s
        assert "target_1" in s
        assert "risk_reward_ratio" in s


def test_api_setups_history_endpoint(client):
    """Verify GET /api/v1/setups/history returns paginated historical setups."""
    response = client.get("/api/v1/setups/history?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
