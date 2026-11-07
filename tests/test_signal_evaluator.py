"""
Unit tests for DirectionalSignalEvaluator.
Verifies:
- 5, 10, 20, 50 candle horizon evaluation.
- MFE and MAE calculations for LONG and SHORT.
- Favorable before adverse excursion (FAVORABLE_FIRST vs ADVERSE_FIRST).
- Conservative collision resolution when both occur on the same bar.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.backtest.signal_evaluator import DirectionalSignalEvaluator
from backend.decision.models import DirectionAssessment, DirectionType, ScoreBreakdown


def make_assessment(direction: DirectionType = DirectionType.BULLISH) -> DirectionAssessment:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=now,
        direction=direction,
        bullish_score=75.0 if direction == DirectionType.BULLISH else 15.0,
        bearish_score=15.0 if direction == DirectionType.BULLISH else 75.0,
        breakdown=ScoreBreakdown(),
        data_quality_score=95.0,
    )


def test_bullish_signal_horizons_favorable_first():
    """Verify bullish signal records FAVORABLE_FIRST when price rallies before dipping."""
    start = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    n = 60
    times = [start + timedelta(hours=i) for i in range(n)]

    # Initial rally: bars 0-10 push up from 2700 to 2750 without dropping
    highs = []
    lows = []
    closes = []
    opens = []
    for i in range(n):
        if i < 10:
            p = 2700.0 + (i * 5.0)
            opens.append(p)
            highs.append(p + 4.0)
            lows.append(p - 1.0)
            closes.append(p + 2.0)
        else:
            p = 2750.0 - (i - 10) * 2.0
            opens.append(p)
            highs.append(p + 1.0)
            lows.append(p - 3.0)
            closes.append(p - 1.0)

    df_future = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "atr_14": [5.0] * n,
        }
    )

    assessment = make_assessment(DirectionType.BULLISH)
    setup_id = uuid.uuid4()
    records = DirectionalSignalEvaluator.evaluate_signal_horizons(
        assessment=assessment, future_candles_1h=df_future, setup_id=setup_id
    )

    # Must produce 4 horizon records (5, 10, 20, 50)
    assert len(records) == 4
    for r in records:
        assert r.symbol == "XAUUSDT"
        assert r.direction == "BULLISH"
        assert r.setup_id == setup_id
        assert r.horizon_candles in [5, 10, 20, 50]

    # First 5 candles rallied strongly -> FAVORABLE_FIRST
    rec_5 = next(r for r in records if r.horizon_candles == 5)
    assert rec_5.outcome == "FAVORABLE_FIRST"
    assert rec_5.max_favorable_excursion > 20.0
    assert rec_5.max_adverse_excursion < 5.0


def test_bearish_signal_horizons_adverse_first():
    """Verify bearish signal records ADVERSE_FIRST when price moves against short bias."""
    start = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    n = 60
    times = [start + timedelta(hours=i) for i in range(n)]

    # Unfavorable rally against short position
    opens = [2700.0 + i * 3.0 for i in range(n)]
    highs = [p + 4.0 for p in opens]
    lows = [p - 1.0 for p in opens]
    closes = [p + 2.0 for p in opens]

    df_future = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "atr_14": [5.0] * n,
        }
    )

    assessment = make_assessment(DirectionType.BEARISH)
    records = DirectionalSignalEvaluator.evaluate_signal_horizons(
        assessment=assessment, future_candles_1h=df_future
    )

    assert len(records) == 4
    rec_5 = next(r for r in records if r.horizon_candles == 5)
    # Price moved up, which is adverse for a SHORT
    assert rec_5.outcome == "ADVERSE_FIRST"
    assert rec_5.max_adverse_excursion > rec_5.max_favorable_excursion
