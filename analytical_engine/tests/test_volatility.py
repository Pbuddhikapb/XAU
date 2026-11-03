"""
Tests for Volatility indicators: True Range, ATR, Bollinger Bands, Historical Volatility,
and Causal Volatility Percentile.
"""

import numpy as np
import pytest

from analytical_engine.indicators.volatility import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_true_range,
    calculate_volatility_percentile,
)


def test_true_range_and_atr():
    """Verify True Range formula and ATR Wilder smoothing."""
    high = [105.0, 108.0, 106.0]
    low = [100.0, 102.0, 101.0]
    close = [103.0, 104.0, 105.0]

    tr = calculate_true_range(high, low, close)
    # tr[0] = 105 - 100 = 5.0
    # tr[1] = max(108-102=6, |108-103|=5, |102-103|=1) = 6.0
    # tr[2] = max(106-101=5, |106-104|=2, |101-104|=3) = 5.0
    assert pytest.approx(tr[0], 1e-9) == 5.0
    assert pytest.approx(tr[1], 1e-9) == 6.0
    assert pytest.approx(tr[2], 1e-9) == 5.0

    # ATR(2):
    # Seed at idx 1: (5.0 + 6.0) / 2 = 5.5
    # Value at idx 2: (5.5 * 1 + 5.0) / 2 = 5.25
    atr = calculate_atr(high, low, close, period=2)
    assert np.isnan(atr[0])
    assert pytest.approx(atr[1], 1e-9) == 5.5
    assert pytest.approx(atr[2], 1e-9) == 5.25


def test_bollinger_bands():
    """Verify Bollinger Bands middle, upper, lower, bandwidth, and %B."""
    close = [100.0 + i for i in range(25)]
    bb = calculate_bollinger_bands(close, period=20, num_std=2.0, ddof=1)

    # Middle is 20-period SMA
    # At idx 19 (first 20 bars, 100 to 119): mean = 109.5
    assert pytest.approx(bb["middle"][19], 1e-9) == 109.5
    assert bb["upper"][19] > bb["middle"][19]
    assert bb["lower"][19] < bb["middle"][19]
    assert bb["bandwidth"][19] > 0.0
    assert 0.0 <= bb["percent_b"][19] <= 1.0


def test_bollinger_bands_zero_std():
    """Verify Bollinger Bands handle flat prices without zero division error."""
    close = [150.0] * 25
    bb = calculate_bollinger_bands(close, period=20, num_std=2.0)

    assert bb["middle"][20] == 150.0
    assert bb["upper"][20] == 150.0
    assert bb["lower"][20] == 150.0
    assert bb["bandwidth"][20] == 0.0
    assert bb["percent_b"][20] == 0.5


def test_volatility_percentile_causal():
    """Verify volatility percentile ranks strictly against historical lookback window."""
    # Create array where value starts low (1.0) for 100 bars, then spikes to 10.0
    vals = [1.0] * 100 + [10.0]
    pct = calculate_volatility_percentile(vals, lookback=100)

    # For first 99 bars, returns NaN
    assert np.isnan(pct[98])
    # At idx 99 (100th bar of 1.0s), 1.0 is equal to all values -> 100%
    assert pct[99] == 100.0
    # At idx 100 (value 10.0), 10.0 is the maximum of the lookback window -> 100%
    assert pct[100] == 100.0
