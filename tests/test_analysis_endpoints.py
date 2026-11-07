"""
Integration tests for Phase 4 Engine A Analysis Endpoints.
Verifies:
- GET /api/v1/analysis/current
- GET /api/v1/analysis/timeframes
- GET /api/v1/analysis/evidence
Conforms to Section 7 & 10 of PROJECT_SPECIFICATION.md:
- Heuristic scores (0-100), never probabilities.
- Two-tier invalidation format.
- Stamped methodology version.
- Fast cached response.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_analysis_current_endpoint(client):
    """Verify GET /api/v1/analysis/current adheres strictly to Engine A requirements."""
    response = client.get("/api/v1/analysis/current?symbol=XAUUSDT")
    assert response.status_code == 200
    data = response.json()

    # Core identification
    assert data["symbol"] == "XAUUSDT"
    assert "assessment_time" in data
    assert "direction" in data

    # Mandatory Heuristic Indicator Score Label & Boundary
    assert data["score_label"] == "HEURISTIC_INDICATOR_SCORE"
    assert 0.0 <= data["bullish_score"] <= 100.0
    assert 0.0 <= data["bearish_score"] <= 100.0
    # Must NOT sum to 100
    assert data["bullish_score"] + data["bearish_score"] != 100.0

    # Score breakdown
    bd = data["breakdown"]
    assert "structure_score" in bd
    assert "mtf_trend_score" in bd
    assert "momentum_score" in bd
    assert "volume_score" in bd
    assert "liquidity_score" in bd
    assert "volatility_pa_score" in bd

    # Methodology and quality stamping
    assert data["methodology_version"] == settings.DECISION_METHODOLOGY_VERSION
    assert 0.0 <= data["data_quality_score"] <= 100.0

    # Two-tier invalidation condition
    inval = data["invalidation_conditions"]
    assert isinstance(inval, str)
    assert len(inval) > 0


def test_analysis_timeframes_endpoint(client):
    """Verify GET /api/v1/analysis/timeframes returns alignment across primary timeframes."""
    response = client.get("/api/v1/analysis/timeframes?symbol=XAUUSDT")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "XAUUSDT"
    assert "overall_direction" in data
    assert "timeframe_alignment" in data
    assert data["methodology_version"] == settings.DECISION_METHODOLOGY_VERSION


def test_analysis_evidence_endpoint(client):
    """Verify GET /api/v1/analysis/evidence returns distinct supporting and contradicting factors."""
    response = client.get("/api/v1/analysis/evidence?symbol=XAUUSDT")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "XAUUSDT"
    assert isinstance(data["supporting_evidence"], list)
    assert isinstance(data["contradicting_evidence"], list)
    assert "key_levels" in data
    assert "invalidation_conditions" in data


def test_analysis_cached_fast_path(client):
    """Verify subsequent requests serve cached data with fast response time."""
    # First request primes or fetches
    client.get("/api/v1/analysis/current?symbol=XAUUSDT")

    # Second request should hit cache
    start = time.perf_counter()
    cached_resp = client.get("/api/v1/analysis/current?symbol=XAUUSDT&max_age_seconds=300")
    elapsed = time.perf_counter() - start

    assert cached_resp.status_code == 200
    cached_data = cached_resp.json()
    assert cached_data.get("source") == "CACHE"
    # Fast path should complete well under 200ms
    assert elapsed < 0.200
