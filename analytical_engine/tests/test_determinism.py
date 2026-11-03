"""
Determinism and Reproducibility tests.
Verifies that identical inputs and parameters produce bit-identical results.
"""

import numpy as np
import pandas as pd

from analytical_engine.indicators.momentum import calculate_rsi
from analytical_engine.indicators.moving_averages import calculate_ema_series
from analytical_engine.indicators.volatility import calculate_bollinger_bands
from analytical_engine.structure.pivots import PivotDetector


def test_calculation_determinism():
    """Verify that multiple repeated runs produce identical floating-point outputs."""
    np.random.seed(42)
    prices = 4000.0 + np.cumsum(np.random.randn(200) * 2.0)

    # Run 1
    ema_1 = calculate_ema_series(prices, period=20)
    rsi_1 = calculate_rsi(prices, period=14)
    bb_1 = calculate_bollinger_bands(prices, period=20)

    # Run 2
    ema_2 = calculate_ema_series(prices, period=20)
    rsi_2 = calculate_rsi(prices, period=14)
    bb_2 = calculate_bollinger_bands(prices, period=20)

    assert np.array_equal(ema_1, ema_2, equal_nan=True)
    assert np.array_equal(rsi_1, rsi_2, equal_nan=True)
    assert np.array_equal(bb_1["upper"], bb_2["upper"], equal_nan=True)
    assert np.array_equal(bb_1["lower"], bb_2["lower"], equal_nan=True)


def test_pivot_detector_determinism():
    """Verify pivot detection output is strictly deterministic across runs."""
    records = []
    base_epoch = 1765440000
    np.random.seed(42)
    p = 4000.0
    for i in range(100):
        p += np.random.randn() * 2.0
        records.append({
            "open_time": pd.to_datetime(base_epoch + i * 60, unit="s", utc=True),
            "close_time": pd.to_datetime(base_epoch + (i + 1) * 60, unit="s", utc=True),
            "high": p + 1.5,
            "low": p - 1.5,
            "close": p,
            "open": p,
            "volume": 100.0,
        })
    df = pd.DataFrame(records)

    det_1 = PivotDetector(left_bars=2, right_bars=2).find_pivots(df)
    det_2 = PivotDetector(left_bars=2, right_bars=2).find_pivots(df)

    assert len(det_1) == len(det_2)
    for p1, p2 in zip(det_1, det_2, strict=False):
        assert p1.pivot_time == p2.pivot_time
        assert p1.pivot_price == p2.pivot_price
        assert p1.confirmation_time == p2.confirmation_time
        assert p1.pivot_type == p2.pivot_type
