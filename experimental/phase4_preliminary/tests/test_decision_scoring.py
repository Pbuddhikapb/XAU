"""
Unit and integration tests for Engine A: DirectionalScoringEngine.
Strictly tests Section 6, 7, and 9 of PROJECT_SPECIFICATION.md:
- Independent calculation of Bullish and Bearish scores (no forced sum to 100).
- Multi-factor scoring across 6 weighted categories.
- Data quality gating and CME Gold session halt handling.
- Deterministic invalidation and key level extraction.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from backend.analytics.indicator_engine import IndicatorEngine
from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    MarketRegime,
)
from backend.decision.scoring_engine import DirectionalScoringEngine
from backend.structure.structure_engine import StructureEngine


def generate_timeframe_candles(n: int = 60, trend: str = "bullish", base_price: float = 2700.0) -> pd.DataFrame:
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
    tf_data = {}
    for tf in ["1d", "4h", "1h", "15m", "5m"]:
        df = generate_timeframe_candles(60, trend=trend)
        df_ind = IndicatorEngine.compute_all_indicators(df, symbol="XAUUSDT", timeframe=tf)
        struct = StructureEngine.analyze_timeframe(df_ind, timeframe=tf)
        tf_data[tf] = {"df": df_ind, "structure": struct}
    return tf_data


def test_independent_scoring_not_sum_to_100():
    """Verify Bullish and Bearish scores are calculated independently and do not sum to 100."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT")

    assert isinstance(assessment, DirectionAssessment)
    assert assessment.bullish_score >= 50.0
    assert assessment.bearish_score < 25.0
    # Mandatory rule: Bullish + Bearish != 100
    assert assessment.bullish_score + assessment.bearish_score != 100.0
    assert assessment.direction in [DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH]


def test_bearish_market_scoring():
    """Verify strongly downward trending data triggers high bearish score."""
    bear_data = build_mock_tf_data(trend="bearish")
    assessment = DirectionalScoringEngine.evaluate(bear_data, symbol="XAUUSDT")

    assert assessment.bearish_score >= 50.0
    assert assessment.bullish_score < 25.0
    assert assessment.direction in [DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH]
    assert "closes above" in assessment.invalidation_conditions


def test_neutral_chop_market():
    """Verify sideways/choppy market produces NEUTRAL direction and neither side meets directional threshold."""
    chop_data = build_mock_tf_data(trend="sideways")
    assessment = DirectionalScoringEngine.evaluate(chop_data, symbol="XAUUSDT")

    assert assessment.direction == DirectionType.NEUTRAL
    assert assessment.bullish_score < 65.0
    assert assessment.bearish_score < 65.0


def test_data_quality_gating():
    """Verify missing primary timeframes lowers data quality and forces NEUTRAL direction."""
    # Only supply 1h data (missing 1d, 4h, 15m, 5m)
    df_1h = generate_timeframe_candles(50, trend="bullish")
    df_ind = IndicatorEngine.compute_all_indicators(df_1h, symbol="XAUUSDT", timeframe="1h")
    struct = StructureEngine.analyze_timeframe(df_ind, timeframe="1h")
    incomplete_tf_data = {"1h": {"df": df_ind, "structure": struct}}

    assessment = DirectionalScoringEngine.evaluate(incomplete_tf_data, symbol="XAUUSDT")
    assert assessment.data_quality_score < 70.0
    assert assessment.direction == DirectionType.NEUTRAL


def test_cme_session_inactive_handling():
    """Verify when CME Gold session is inactive, engine reports SESSION_INACTIVE and NEUTRAL direction."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT", session_is_active=False)

    assert assessment.market_regime == MarketRegime.SESSION_INACTIVE.value
    assert assessment.direction == DirectionType.NEUTRAL


def test_key_levels_and_evidence_citations():
    """Verify key technical levels and structured evidence citations are present."""
    bull_data = build_mock_tf_data(trend="bullish")
    assessment = DirectionalScoringEngine.evaluate(bull_data, symbol="XAUUSDT")

    assert assessment.key_levels is not None
    assert "ema_20" in assessment.key_levels
    assert "swing_high" in assessment.key_levels
    assert len(assessment.supporting_evidence) > 0
    first_ev = assessment.supporting_evidence[0]
    assert "factor" in first_ev
    assert "description" in first_ev
    assert "score_contribution" in first_ev
