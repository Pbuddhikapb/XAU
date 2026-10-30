"""
Unit tests for Price Action Patterns (Rejections, Engulfing).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.price_action import detect_price_action_patterns


def test_rejection_pinbar():
    # Construct a strong bullish rejection pinbar (long lower wick)
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time, base_time + timedelta(hours=1)]

    # Candle 1: Open=2650, High=2652, Low=2635, Close=2651
    # Total range = 17. Lower wick = 2650 - 2635 = 15. Wick ratio = 15 / 17 = 88.2%
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": [2650.0, 2650.0],
            "high": [2655.0, 2652.0],
            "low": [2645.0, 2635.0],
            "close": [2650.0, 2651.0],
            "volume": [100.0, 100.0],
        }
    )

    patterns = detect_price_action_patterns(df)
    types = [p.pattern_type for p in patterns]
    assert "REJECTION_BULL" in types


def test_bullish_engulfing():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time, base_time + timedelta(hours=1)]

    # Candle 0: Bearish (Open=2655, Close=2645)
    # Candle 1: Bullish engulfing (Open=2644, High=2662, Low=2642, Close=2660)
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": [2655.0, 2644.0],
            "high": [2656.0, 2662.0],
            "low": [2644.0, 2642.0],
            "close": [2645.0, 2660.0],
            "volume": [100.0, 150.0],
        }
    )

    patterns = detect_price_action_patterns(df)
    types = [p.pattern_type for p in patterns]
    assert "ENGULFING_BULL" in types
