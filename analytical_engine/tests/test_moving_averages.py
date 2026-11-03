"""
Tests for Simple and Exponential Moving Averages (SMA, EMA).
Independent verification against manually calculated numerical values.
"""

import numpy as np
import pytest

from analytical_engine.indicators.moving_averages import (
    calculate_ema_series,
    calculate_sma_series,
)


def test_sma_manual_calculation():
    """Verify SMA against manual mathematical calculations."""
    # Data: [10, 20, 30, 40, 50]
    # SMA(3):
    # idx 0: NaN
    # idx 1: NaN
    # idx 2: (10+20+30)/3 = 20.0
    # idx 3: (20+30+40)/3 = 30.0
    # idx 4: (30+40+50)/3 = 40.0
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    sma = calculate_sma_series(data, period=3)

    assert np.isnan(sma[0])
    assert np.isnan(sma[1])
    assert pytest.approx(sma[2], 1e-9) == 20.0
    assert pytest.approx(sma[3], 1e-9) == 30.0
    assert pytest.approx(sma[4], 1e-9) == 40.0


def test_ema_manual_calculation():
    """
    Verify EMA against manual step-by-step formula.
    Data: [10, 20, 30, 40]
    period = 3, alpha = 2 / (3 + 1) = 0.5
    Seed at idx 2: SMA(10, 20, 30) = 20.0
    EMA at idx 3: 0.5 * 40.0 + 0.5 * 20.0 = 30.0
    """
    data = [10.0, 20.0, 30.0, 40.0]
    ema = calculate_ema_series(data, period=3)

    assert np.isnan(ema[0])
    assert np.isnan(ema[1])
    assert pytest.approx(ema[2], 1e-9) == 20.0
    assert pytest.approx(ema[3], 1e-9) == 30.0


def test_ema_insufficient_length():
    """Verify that series shorter than period returns all NaNs."""
    data = [10.0, 20.0]
    ema = calculate_ema_series(data, period=5)
    assert len(ema) == 2
    assert all(np.isnan(x) for x in ema)


def test_moving_averages_constant_series():
    """Verify that constant prices produce exact constant moving averages without drift."""
    data = [100.0] * 50
    sma = calculate_sma_series(data, period=10)
    ema = calculate_ema_series(data, period=10)

    # For idx >= 9, should be exactly 100.0
    assert np.allclose(sma[9:], 100.0)
    assert np.allclose(ema[9:], 100.0)
