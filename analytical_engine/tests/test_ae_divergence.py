"""
Tests for Momentum Divergence Detection across RSI and MACD Histogram.
"""

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from analytical_engine.models.outputs import PivotRecord
from analytical_engine.structure.divergence import DivergenceDetector


def create_mock_pivots_and_series():
    """
    Construct synthetic scenario for Regular Bullish Divergence:
    Price Pivot 1 at t1: Price = 100.0, RSI = 30.0
    Price Pivot 2 at t2: Price = 95.0 (Lower Low), RSI = 38.0 (Higher Low)
    """
    base_epoch = 1765440000
    n = 30
    records = []
    for i in range(n):
        records.append({
            "open_time": datetime.fromtimestamp(base_epoch + i * 60, tz=UTC),
            "high": 100.0,
            "low": 90.0,
            "close": 95.0,
            "volume": 100.0,
        })
    df = pd.DataFrame(records)
    df.attrs["timeframe"] = "1m"

    # Define pivots at index 5 and index 15 (separation = 10 bars)
    t1 = df.loc[5, "open_time"]
    c1 = datetime.fromtimestamp(base_epoch + 7 * 60, tz=UTC)
    t2 = df.loc[15, "open_time"]
    c2 = datetime.fromtimestamp(base_epoch + 17 * 60, tz=UTC)

    pivots = [
        PivotRecord(
            pivot_time=t1,
            pivot_price=100.0,
            pivot_type="LOW",
            confirmation_time=c1,
            confirmation_lag_bars=2,
            left_bars=2,
            right_bars=2,
            timeframe="1m",
        ),
        PivotRecord(
            pivot_time=t2,
            pivot_price=95.0,  # Lower Low
            pivot_type="LOW",
            confirmation_time=c2,
            confirmation_lag_bars=2,
            left_bars=2,
            right_bars=2,
            timeframe="1m",
        ),
    ]

    rsi_series = np.full(n, 50.0, dtype=np.float64)
    rsi_series[5] = 30.0
    rsi_series[15] = 38.0  # Higher Low

    return df, pivots, rsi_series, c2


def test_regular_bullish_divergence():
    """Verify detection of Regular Bullish Divergence with correct confirmation timestamp."""
    df, pivots, rsi_series, expected_conf_time = create_mock_pivots_and_series()

    detector = DivergenceDetector(min_bars_separation=5, max_bars_separation=20)
    divs = detector.detect_divergences(
        df=df,
        indicator_series=rsi_series,
        indicator_name="RSI",
        pivots=pivots,
    )

    assert len(divs) == 1
    d = divs[0]
    assert d.divergence_type == "REGULAR_BULLISH"
    assert d.indicator_name == "RSI"
    assert d.price_pivot_1_price == 100.0
    assert d.price_pivot_2_price == 95.0
    assert d.indicator_val_1 == 30.0
    assert d.indicator_val_2 == 38.0
    # Available only at Pivot 2's confirmation time
    assert d.confirmation_time == expected_conf_time


def test_regular_bearish_divergence():
    """Verify detection of Regular Bearish Divergence (Price HH, Indicator LH)."""
    base_epoch = 1765440000
    n = 30
    records = []
    for i in range(n):
        records.append({
            "open_time": datetime.fromtimestamp(base_epoch + i * 60, tz=UTC),
            "high": 110.0,
            "low": 90.0,
            "close": 100.0,
            "volume": 100.0,
        })
    df = pd.DataFrame(records)

    t1 = df.loc[5, "open_time"]
    c1 = datetime.fromtimestamp(base_epoch + 7 * 60, tz=UTC)
    t2 = df.loc[15, "open_time"]
    c2 = datetime.fromtimestamp(base_epoch + 17 * 60, tz=UTC)

    pivots = [
        PivotRecord(
            pivot_time=t1,
            pivot_price=105.0,
            pivot_type="HIGH",
            confirmation_time=c1,
            confirmation_lag_bars=2,
            left_bars=2,
            right_bars=2,
            timeframe="1m",
        ),
        PivotRecord(
            pivot_time=t2,
            pivot_price=112.0,  # Higher High
            pivot_type="HIGH",
            confirmation_time=c2,
            confirmation_lag_bars=2,
            left_bars=2,
            right_bars=2,
            timeframe="1m",
        ),
    ]

    rsi_series = np.full(n, 50.0, dtype=np.float64)
    rsi_series[5] = 75.0
    rsi_series[15] = 68.0  # Lower High

    detector = DivergenceDetector(min_bars_separation=5, max_bars_separation=20)
    divs = detector.detect_divergences(df, rsi_series, indicator_name="RSI", pivots=pivots)

    assert len(divs) == 1
    assert divs[0].divergence_type == "REGULAR_BEARISH"
    assert divs[0].confirmation_time == c2


def test_divergence_separation_filter():
    """Verify that divergences exceeding max_bars_separation are rejected."""
    df, pivots, rsi_series, _ = create_mock_pivots_and_series()

    # Set max separation to 5 bars (actual separation is 10 bars)
    detector = DivergenceDetector(min_bars_separation=2, max_bars_separation=5)
    divs = detector.detect_divergences(df, rsi_series, indicator_name="RSI", pivots=pivots)

    assert len(divs) == 0
