"""
Tests for Trend Indicators: EMA ribbon, Directional Movement (+DI/-DI), and ADX.
"""

import numpy as np

from analytical_engine.indicators.trend import calculate_adx, calculate_ema_ribbon


def test_ema_ribbon():
    """Verify EMA ribbon calculates correct periods."""
    data = [100.0 + i for i in range(250)]
    ribbon = calculate_ema_ribbon(data, periods=[20, 50, 100, 200])

    assert "ema_20" in ribbon
    assert "ema_50" in ribbon
    assert "ema_100" in ribbon
    assert "ema_200" in ribbon

    # For monotonically increasing price, EMA 20 > EMA 50 > EMA 100 > EMA 200
    last_idx = 249
    assert ribbon["ema_20"][last_idx] > ribbon["ema_50"][last_idx]
    assert ribbon["ema_50"][last_idx] > ribbon["ema_100"][last_idx]
    assert ribbon["ema_100"][last_idx] > ribbon["ema_200"][last_idx]


def test_adx_strong_trend():
    """Verify ADX reaches high values in a sustained strong uptrend."""
    n = 60
    high = [100.0 + i * 2.0 + 1.0 for i in range(n)]
    low = [100.0 + i * 2.0 - 1.0 for i in range(n)]
    close = [100.0 + i * 2.0 for i in range(n)]

    res = calculate_adx(high, low, close, period=14)

    # In a persistent uptrend:
    # +DI must dominate -DI
    last_idx = n - 1
    assert res["plus_di"][last_idx] > res["minus_di"][last_idx]
    assert res["adx"][last_idx] > 25.0  # Indicates strong trend


def test_adx_flat_market():
    """Verify ADX handles flat prices (zero movement) cleanly without division-by-zero crashes."""
    n = 50
    high = [100.0] * n
    low = [100.0] * n
    close = [100.0] * n

    res = calculate_adx(high, low, close, period=14)

    # In completely flat prices, +DI, -DI, and ADX should evaluate to 0.0 or finite values without error
    assert np.isfinite(res["plus_di"][-1])
    assert res["plus_di"][-1] == 0.0
    assert res["minus_di"][-1] == 0.0
    assert res["adx"][-1] == 0.0
