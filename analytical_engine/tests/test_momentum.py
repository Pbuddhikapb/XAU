"""
Tests for Momentum indicators: RSI, MACD, and ROC.
Includes zero-loss, zero-gain, flat variance, and standard numerical examples.
"""

import numpy as np
import pytest

from analytical_engine.indicators.momentum import (
    calculate_macd,
    calculate_roc,
    calculate_rsi,
)


def test_rsi_pure_uptrend_zero_loss():
    """Verify that pure monotonically increasing price yields RSI = 100.0."""
    close = [100.0 + i for i in range(30)]
    rsi = calculate_rsi(close, period=14)

    # For idx >= 14, zero losses occur, so RSI must be 100.0
    assert pytest.approx(rsi[14], 1e-9) == 100.0
    assert pytest.approx(rsi[-1], 1e-9) == 100.0


def test_rsi_pure_downtrend_zero_gain():
    """Verify that pure monotonically decreasing price yields RSI = 0.0."""
    close = [200.0 - i for i in range(30)]
    rsi = calculate_rsi(close, period=14)

    assert pytest.approx(rsi[14], 1e-9) == 0.0
    assert pytest.approx(rsi[-1], 1e-9) == 0.0


def test_rsi_flat_zero_variance():
    """Verify that flat prices yield RSI = 50.0 without division-by-zero crashes."""
    close = [150.0] * 30
    rsi = calculate_rsi(close, period=14)

    assert pytest.approx(rsi[14], 1e-9) == 50.0
    assert pytest.approx(rsi[-1], 1e-9) == 50.0


def test_macd_initialization_and_crossover():
    """Verify MACD fast/slow calculation, signal line, and histogram."""
    # Create alternating oscillating trend
    close = [100.0 + np.sin(i / 5.0) * 10.0 + (i * 0.5) for i in range(60)]
    macd = calculate_macd(close, fast_period=12, slow_period=26, signal_period=9)

    # First valid MACD line at idx 25 (26-1)
    assert np.isnan(macd["macd_line"][24])
    assert np.isfinite(macd["macd_line"][25])

    # First valid signal line occurs when 9 valid MACD values exist (idx 25 + 9 - 1 = 33)
    assert np.isnan(macd["signal_line"][32])
    assert np.isfinite(macd["signal_line"][33])

    # Histogram = MACD - Signal
    assert pytest.approx(macd["histogram"][33], 1e-9) == (macd["macd_line"][33] - macd["signal_line"][33])


def test_roc_calculation():
    """Verify Rate of Change calculation and zero denominator protection."""
    # Data: [100, 110, 120] -> ROC(1) at idx 1: (110 - 100)/100 * 100 = 10.0%
    close = [100.0, 110.0, 120.0, 105.0]
    roc = calculate_roc(close, period=1)

    assert np.isnan(roc[0])
    assert pytest.approx(roc[1], 1e-9) == 10.0
    assert pytest.approx(roc[2], 1e-9) == (10.0 / 110.0) * 100.0

    # Test with 0 denominator
    close_zero = [0.0, 100.0]
    roc_zero = calculate_roc(close_zero, period=1)
    assert np.isnan(roc_zero[1])
