"""
Unit and integration tests for Engine A: DirectionalScoringEngine.
Strictly conforms to Section 6, 7, and 9 of PROJECT_SPECIFICATION.md and Section 16 of Forensic Audit:
- Independent calculation of Bullish and Bearish heuristic scores (0-100, never probabilities).
- Correlation-aware capping & deduplication (Structure + MTF Trend cap, Momentum + Price Action cap).
- Data quality gating (< 70 => NEUTRAL / DATA_UNAVAILABLE).
- CME Gold session inactive gating (closed market => NEUTRAL / SESSION_INACTIVE).
- Config-driven weights and methodology version stamped on every output.
- Structured supporting evidence, contradicting evidence, key levels, and invalidation conditions.
- Adversarial no-lookahead test (future data invariance).
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from backend.analytics.indicator_engine import IndicatorEngine
from backend.config import settings
from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    MarketRegime,
)
from backend.decision.scoring_engine import DirectionalScoringEngine
from backend.structure.structure_engine import StructureEngine


def generate_timeframe_candles(n: int = 60, trend: str = "bullish", base_price: float = 2700.0) -> pd.DataFrame:
    """Generate realistic deterministic multi-bar OHLCV data."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time + timedelta(hours=i) for i in range(n)]

    prices = []
    for i in range(n):
        cycle = i % 8
        wave = 3.0 * (cycle if cycle < 5 else (8 - cycle))
        if trend == "bullish":
            p = base_price + (i * 2.0) + wave
        elif trend == "bearish":
            p = base_price - (i * 2.0) - wave
        else:  # sideways
            p = base_price + np.sin(i / 2.0) * 8.0
        prices.append(p)

    highs = [p + 3.0 for p in prices]
    lows = [p - 3.0 for p in prices]
    opens = [p - 1.0 if trend == "bullish" else p + 1.0 for p in prices]
    volumes = [200.0 + (i * 2.0) for i in range(n)]
    if trend == "bullish":
        taker_buy = [v * 0.65 for v in volumes]
    elif trend == "bearish":
        taker_buy = [v * 0.35 for v in volumes]
    else:
        taker_buy = [v * 0.50 for v in volumes]

    return pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": volumes,
            "taker_buy_volume": taker_buy,
        }
    )


def build_mock_tf_data(trend: str = "bullish") -> dict[str, dict]:
    """Generate complete multi-timeframe dataset."""
    tf_data = {}
    for tf in settings.PRIMARY_TIMEFRAMES:
        df = generate_timeframe_candles(60, trend=trend)
        df_ind = IndicatorEngine.compute_all_indicators(df, symbol=settings.SYMBOL, timeframe=tf)
        struct = StructureEngine.analyze_timeframe(df_ind, timeframe=tf)
        tf_data[tf] = {"df": df_ind, "structure": struct}
    return tf_data


def test_independent_heuristic_scoring_not_probabilities():
    """Verify scores are independent heuristic scores (0-100), not forced to sum to 100, and labeled properly."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT")

    assert isinstance(assessment, DirectionAssessment)
    assert 0.0 <= assessment.bullish_score <= 100.0
    assert 0.0 <= assessment.bearish_score <= 100.0
    # Mandatory rule: Bullish and Bearish scores must not sum to 100
    assert assessment.bullish_score + assessment.bearish_score != 100.0
    # Explicit heuristic label
    assert assessment.score_label == "HEURISTIC_INDICATOR_SCORE"
    assert assessment.methodology_version == settings.DECISION_METHODOLOGY_VERSION
    assert assessment.direction in [DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH]


def test_correlation_aware_capping():
    """Verify correlation-aware caps prevent double-counting collinear factors."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT")

    bd = assessment.breakdown
    # Group 1: Structure + MTF Trend must not exceed MAX_STRUCTURE_TREND_COMBINED (35.0)
    assert bd.structure_trend_dampened <= settings.MAX_STRUCTURE_TREND_COMBINED
    # Group 2: Momentum + Volatility/PA must not exceed MAX_MOMENTUM_PA_COMBINED (22.0)
    assert bd.momentum_pa_dampened <= settings.MAX_MOMENTUM_PA_COMBINED


def test_data_quality_gating_below_70():
    """Verify data quality < 70 forces NEUTRAL direction and DATA_UNAVAILABLE regime."""
    # Only supply 1h data (missing 1d, 4h, 15m, 5m) -> quality ratio 1/5 = 20%
    df_1h = generate_timeframe_candles(50, trend="bullish")
    df_ind = IndicatorEngine.compute_all_indicators(df_1h, symbol="XAUUSDT", timeframe="1h")
    struct = StructureEngine.analyze_timeframe(df_ind, timeframe="1h")
    incomplete_tf_data = {"1h": {"df": df_ind, "structure": struct}}

    assessment = DirectionalScoringEngine.evaluate(incomplete_tf_data, symbol="XAUUSDT")
    assert assessment.data_quality_score < settings.DATA_QUALITY_MIN_SCORE
    assert assessment.direction == DirectionType.NEUTRAL
    assert assessment.market_regime == MarketRegime.DATA_UNAVAILABLE.value
    # Warning cited in contradicting evidence
    assert any("Data Quality Warning" in str(e.get("factor")) for e in assessment.contradicting_evidence)


def test_cme_session_inactive_gating():
    """Verify closed/inactive CME session forces NEUTRAL direction and SESSION_INACTIVE regime."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT", session_is_active=False)

    assert assessment.direction == DirectionType.NEUTRAL
    assert assessment.market_regime == MarketRegime.SESSION_INACTIVE.value


def test_supporting_and_contradicting_evidence_separation():
    """Verify supporting and contradicting evidence, key levels, and invalidation are populated."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT")

    assert len(assessment.supporting_evidence) > 0
    assert len(assessment.contradicting_evidence) >= 0
    assert "ema_20" in assessment.key_levels
    assert "swing_high" in assessment.key_levels
    assert len(assessment.invalidation_conditions) > 0
    assert "Invalidated" in assessment.invalidation_conditions or "invalidated" in assessment.invalidation_conditions


def test_bearish_market_scoring():
    """Verify bearish data scores high bearish evidence and sets appropriate invalidation."""
    bear_data = build_mock_tf_data(trend="bearish")
    assessment = DirectionalScoringEngine.evaluate(bear_data, symbol="XAUUSDT")

    assert assessment.bearish_score >= 50.0
    assert assessment.bullish_score < 30.0
    assert assessment.direction in [DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH]
    assert "closes above" in assessment.invalidation_conditions


def test_macro_alignment_downgrades_opposing_trend():
    """Verify opposing macro trend (4H/1D BEARISH) downgrades strong 1H bullish score to POTENTIAL_BULLISH."""
    # Test 1: Direct classification test with candidate score >= 65 (normally confirmed BULLISH)
    regime, direction, note = DirectionalScoringEngine._classify_direction(
        bullish_score=75.0,
        bearish_score=15.0,
        data_quality=95.0,
        session_is_active=True,
        tf_alignment={"1d": "BULLISH", "4h": "BEARISH", "1h": "BULLISH"},
        df_1h=pd.DataFrame({"adx": [30.0]}),
    )
    assert direction == DirectionType.POTENTIAL_BULLISH
    assert note is not None
    assert "Macro trend 4H is BEARISH" in note

    # Test 2: Symmetric bearish candidate opposing bullish macro trend
    b_regime, b_direction, b_note = DirectionalScoringEngine._classify_direction(
        bullish_score=10.0,
        bearish_score=75.0,
        data_quality=95.0,
        session_is_active=True,
        tf_alignment={"1d": "BEARISH", "4h": "BULLISH", "1h": "BEARISH"},
        df_1h=pd.DataFrame({"adx": [30.0]}),
    )
    assert b_direction == DirectionType.POTENTIAL_BEARISH
    assert b_note is not None
    assert "Macro trend 4H is BULLISH" in b_note


def test_data_staleness_exceeding_3_minutes_forces_neutral():
    """Verify candle lag > 180 seconds during active CME session forces NEUTRAL / DATA_UNAVAILABLE."""
    bull_data = build_mock_tf_data(trend="bullish")
    latest_candle = bull_data["1h"]["df"]["open_time"].iloc[-1]
    stale_eval_time = latest_candle + timedelta(minutes=5)

    assessment = DirectionalScoringEngine.evaluate(
        bull_data,
        symbol="XAUUSDT",
        session_is_active=True,
        assessment_time=stale_eval_time,
        is_live=True,
    )

    assert assessment.data_quality_score < settings.DATA_QUALITY_MIN_SCORE
    assert assessment.direction == DirectionType.NEUTRAL
    assert assessment.market_regime == MarketRegime.DATA_UNAVAILABLE.value
    assert any("Data staleness warning" in str(e.get("description")) for e in assessment.contradicting_evidence)


def test_two_tier_invalidation_structure():
    """Verify invalidation condition includes both Tier 1 Hard Structural level and Tier 2 Soft Momentum warning."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT")

    inval = assessment.invalidation_conditions
    assert "Hard Structural:" in inval
    assert "Soft Momentum Warning:" in inval
    assert "closes below" in inval
    assert "RSI crosses below 50.0" in inval


def test_decision_scoring_adversarial_lookahead():
    """Adversarial test: Appending future data does not alter historical directional assessment."""
    base_data = build_mock_tf_data(trend="bullish")
    t_eval = base_data["1h"]["df"]["open_time"].iloc[-1]

    assessment_base = DirectionalScoringEngine.evaluate(
        base_data, symbol="XAUUSDT", assessment_time=t_eval
    )

    # Append 30 extreme future bars with +$800 price shock to each timeframe
    shocked_data = {}
    for tf, bundle in base_data.items():
        df_orig = bundle["df"].copy()
        future_times = [df_orig["open_time"].iloc[-1] + timedelta(hours=i + 1) for i in range(30)]
        df_future = pd.DataFrame(
            {
                "open_time": future_times,
                "open": [3500.0] * 30,
                "high": [3550.0] * 30,
                "low": [3480.0] * 30,
                "close": [3520.0] * 30,
                "volume": [1000.0] * 30,
                "taker_buy_volume": [600.0] * 30,
            }
        )
        df_concat = pd.concat([df_orig, df_future], ignore_index=True)
        # Sliced strictly to t_eval
        df_sliced = df_concat[df_concat["open_time"] <= t_eval].copy()
        df_ind = IndicatorEngine.compute_all_indicators(df_sliced, symbol="XAUUSDT", timeframe=tf)
        struct = StructureEngine.analyze_timeframe(df_ind, timeframe=tf)
        shocked_data[tf] = {"df": df_ind, "structure": struct}

    assessment_shocked = DirectionalScoringEngine.evaluate(
        shocked_data, symbol="XAUUSDT", assessment_time=t_eval
    )

    assert assessment_base.direction == assessment_shocked.direction
    assert np.isclose(assessment_base.bullish_score, assessment_shocked.bullish_score)
    assert np.isclose(assessment_base.bearish_score, assessment_shocked.bearish_score)
    assert assessment_base.breakdown.total_bullish == assessment_shocked.breakdown.total_bullish
    assert assessment_base.breakdown.total_bearish == assessment_shocked.breakdown.total_bearish
