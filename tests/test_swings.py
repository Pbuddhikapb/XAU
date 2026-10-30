"""
Unit tests for Swing Point Detection (No-Lookahead Confirmation).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.swings import detect_swings


def test_detect_swings_clear_peaks_and_troughs():
    # Construct a series with distinct swing high at index 4 and swing low at index 8
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    # Prices: rise to 2660 at index 4, fall to 2630 at index 8, rise to 2670
    closes = [
        2640.0,
        2645.0,
        2650.0,
        2655.0,
        2660.0,
        2652.0,
        2645.0,
        2638.0,
        2630.0,
        2640.0,
        2650.0,
        2658.0,
        2665.0,
        2660.0,
        2655.0,
    ]
    highs = [c + 2.0 for c in closes]
    lows = [c - 2.0 for c in closes]

    df = pd.DataFrame(
        {
            "open_time": times,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )

    swings = detect_swings(df, window=2)
    assert len(swings) >= 2

    swing_types = [s.swing_type for s in swings]
    assert "SWING_HIGH" in swing_types
    assert "SWING_LOW" in swing_types

    # Find the peak swing
    peak = [s for s in swings if s.swing_type == "SWING_HIGH"][0]
    assert peak.index == 4
    # With window=2, confirmation occurs at bar 4 + 2 = 6
    assert peak.confirmed_index == 6
    assert peak.confirmed_time == times[6]


def test_detect_swings_insufficient_bars():
    df = pd.DataFrame(
        {
            "open_time": [datetime.now(UTC)],
            "high": [2650.0],
            "low": [2640.0],
            "close": [2645.0],
        }
    )
    swings = detect_swings(df, window=3)
    assert swings == []
