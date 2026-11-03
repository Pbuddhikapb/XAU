"""
Unit tests for Swing Point Detection (No-Lookahead Confirmation).
Strictly verifies that:
1. Occurrence time and confirmation time remain separate.
2. Confirmation timestamp reflects candle CLOSE time.
3. Asymmetrical shoulder radii (single vs multiple right bars) function causally.
4. Pivots near the end of incomplete datasets are never exposed prematurely.
5. Confirmation candle must be closed in real-time evaluation.
6. Incremental streaming matches historical batch calculation.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.structure.swings import detect_swings


@pytest.fixture
def hourly_sample_df():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]
    close_times = [t + timedelta(hours=1) for t in times]
    closes = [
        2640.0, 2645.0, 2650.0, 2655.0, 2660.0,  # Peak at idx 4 (2660)
        2652.0, 2645.0, 2638.0, 2630.0, 2640.0,  # Trough at idx 8 (2630)
        2650.0, 2658.0, 2665.0, 2660.0, 2655.0,
    ]
    highs = [c + 2.0 for c in closes]
    lows = [c - 2.0 for c in closes]

    return pd.DataFrame(
        {
            "open_time": times,
            "close_time": close_times,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )


def test_detect_swings_clear_peaks_and_troughs(hourly_sample_df):
    df = hourly_sample_df
    swings = detect_swings(df, window=2)
    assert len(swings) >= 2

    # Peak at index 4 confirmed at close of candle 4 + 2 = 6
    peak = [s for s in swings if s.swing_type == "SWING_HIGH"][0]
    assert peak.index == 4
    assert peak.confirmed_index == 6
    assert peak.confirmed_time == df["close_time"].iloc[6]
    assert peak.time == df["open_time"].iloc[4]
    assert peak.time != peak.confirmed_time


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


def test_pivot_single_right_bar_confirmation(hourly_sample_df):
    """Case 1: Pivot with exactly one right-side confirmation candle (R=1)."""
    df = hourly_sample_df
    # Peak is at index 4
    swings = detect_swings(df, left_bars=2, right_bars=1)
    peak = [s for s in swings if s.swing_type == "SWING_HIGH"][0]
    assert peak.index == 4
    # With R=1, confirmation occurs at bar 4 + 1 = 5
    assert peak.confirmed_index == 5
    assert peak.confirmed_time == df["close_time"].iloc[5]


def test_pivot_multiple_right_bars_confirmation(hourly_sample_df):
    """Case 2: Pivot with multiple right-side confirmation candles (R=3)."""
    df = hourly_sample_df
    # Peak at index 4
    swings = detect_swings(df, left_bars=2, right_bars=3)
    peak = [s for s in swings if s.swing_type == "SWING_HIGH"][0]
    assert peak.index == 4
    # With R=3, confirmation occurs at bar 4 + 3 = 7
    assert peak.confirmed_index == 7
    assert peak.confirmed_time == df["close_time"].iloc[7]


def test_pivot_near_end_of_incomplete_dataset(hourly_sample_df):
    """Case 3: Pivot near the end of an incomplete dataset is withheld."""
    # Peak is at index 4. If we truncate at index 5, index 4 cannot be confirmed with R=2
    truncated = hourly_sample_df.iloc[:6].copy()  # indices 0..5 (bar 5 is the last bar)
    swings = detect_swings(truncated, window=2)  # requires bar 4 + 2 = 6, which does not exist
    high_swings = [s for s in swings if s.swing_type == "SWING_HIGH"]
    assert len(high_swings) == 0  # Not yet confirmed!

    # Once bar 6 is added, the peak appears
    completed = hourly_sample_df.iloc[:7].copy()  # indices 0..6
    swings_completed = detect_swings(completed, window=2)
    high_swings_completed = [s for s in swings_completed if s.swing_type == "SWING_HIGH"]
    assert len(high_swings_completed) == 1
    assert high_swings_completed[0].index == 4
    assert high_swings_completed[0].confirmed_index == 6


def test_pivot_whose_confirmation_candle_has_not_closed(hourly_sample_df):
    """Case 4: Real-time current_time gating prevents unclosed candle confirmation."""
    df = hourly_sample_df
    # Confirmation candle for peak at index 4 with window=2 is bar 6.
    # Bar 6 open_time is df["open_time"].iloc[6], close_time is df["close_time"].iloc[6].
    # At bar 6 open_time + 30 mins, candle 6 has NOT closed yet.
    halfway_through_bar_6 = df["open_time"].iloc[6] + timedelta(minutes=30)
    swings_during = detect_swings(df, window=2, current_time=halfway_through_bar_6)
    assert not any(s.swing_type == "SWING_HIGH" and s.index == 4 for s in swings_during)

    # When current_time reaches or passes bar 6 close_time, it is confirmed
    at_close_of_bar_6 = df["close_time"].iloc[6]
    swings_after = detect_swings(df, window=2, current_time=at_close_of_bar_6)
    assert any(s.swing_type == "SWING_HIGH" and s.index == 4 for s in swings_after)


def test_historical_live_parity_swings(hourly_sample_df):
    """Case 5: Incremental streaming matches batch historical calculation."""
    df = hourly_sample_df
    batch_swings = detect_swings(df, window=2)

    # Replay candle by candle
    streamed_swings_by_time = {}
    for t in range(5, len(df) + 1):
        sub_df = df.iloc[:t].copy()
        current_close = df["close_time"].iloc[t - 1]
        active = detect_swings(sub_df, window=2, current_time=current_close)
        for s in active:
            key = (s.index, s.swing_type)
            if key not in streamed_swings_by_time:
                streamed_swings_by_time[key] = s

    streamed_list = sorted(streamed_swings_by_time.values(), key=lambda s: (s.index, s.swing_type))
    assert len(batch_swings) == len(streamed_list)
    for b, s in zip(batch_swings, streamed_list):
        assert b.index == s.index
        assert b.price == s.price
        assert b.swing_type == s.swing_type
        assert b.confirmed_index == s.confirmed_index
        assert b.confirmed_time == s.confirmed_time
