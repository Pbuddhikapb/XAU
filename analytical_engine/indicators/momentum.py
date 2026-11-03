"""
Momentum indicators: Relative Strength Index (RSI), Moving Average Convergence Divergence (MACD),
and Rate of Change (ROC).
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from analytical_engine.indicators.moving_averages import calculate_ema_series


def calculate_rsi(
    close: Sequence[float] | np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """
    Calculate Welles Wilder's Relative Strength Index (RSI).

    Formulas:
        Change_t = Close_t - Close_{t-1}
        Gain_t = max(Change_t, 0)
        Loss_t = max(-Change_t, 0)

        Wilder's Smoothing:
            AvgGain_t = (AvgGain_{t-1} * (period - 1) + Gain_t) / period
            AvgLoss_t = (AvgLoss_{t-1} * (period - 1) + Loss_t) / period

        Edge-case rules:
            - If AvgLoss == 0 and AvgGain > 0: RSI = 100.0
            - If AvgGain == 0 and AvgLoss > 0: RSI = 0.0
            - If AvgGain == 0 and AvgLoss == 0: RSI = 50.0 (Flat / Zero-variance)
            - Otherwise: RS = AvgGain / AvgLoss; RSI = 100 - (100 / (1 + RS))
    """
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    rsi = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n <= period:
        return rsi

    # Price changes
    delta = np.diff(c)  # length n-1
    gains = np.maximum(delta, 0.0)
    losses = np.maximum(-delta, 0.0)

    # First average gain/loss seeded with simple mean of first `period` changes
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # First RSI at index `period`
    if avg_loss == 0.0:
        rsi[period] = 100.0 if avg_gain > 0.0 else 50.0
    elif avg_gain == 0.0:
        rsi[period] = 0.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    decay = period - 1.0

    # Wilder recurrence for subsequent bars
    for i in range(period + 1, n):
        gain = gains[i - 1]
        loss = losses[i - 1]

        avg_gain = (avg_gain * decay + gain) / period
        avg_loss = (avg_loss * decay + loss) / period

        if avg_loss <= 1e-12:
            rsi[i] = 100.0 if avg_gain > 1e-12 else 50.0
        elif avg_gain <= 1e-12:
            rsi[i] = 0.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def calculate_macd(
    close: Sequence[float] | np.ndarray | pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, np.ndarray]:
    """
    Calculate Moving Average Convergence Divergence (MACD).

    Formulas:
        Fast_EMA = EMA(Close, fast_period)
        Slow_EMA = EMA(Close, slow_period)
        MACD_Line = Fast_EMA - Slow_EMA
        Signal_Line = EMA(MACD_Line, signal_period)
        Histogram = MACD_Line - Signal_Line

    Returns:
        Dict with keys: 'macd_line', 'signal_line', 'histogram'
    """
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    empty_res = {
        "macd_line": np.full(n, np.nan, dtype=np.float64),
        "signal_line": np.full(n, np.nan, dtype=np.float64),
        "histogram": np.full(n, np.nan, dtype=np.float64),
    }

    if fast_period >= slow_period or n < slow_period:
        return empty_res

    fast_ema = calculate_ema_series(c, period=fast_period)
    slow_ema = calculate_ema_series(c, period=slow_period)

    macd_line = fast_ema - slow_ema

    # Signal line is EMA of valid MACD line values
    # Valid MACD line begins at index slow_period - 1
    valid_macd_start = slow_period - 1
    signal_line = np.full(n, np.nan, dtype=np.float64)

    if n >= valid_macd_start + signal_period:
        valid_macd_slice = macd_line[valid_macd_start:]
        sig_slice = calculate_ema_series(valid_macd_slice, period=signal_period)
        signal_line[valid_macd_start:] = sig_slice

    histogram = macd_line - signal_line

    return {
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
    }


def calculate_roc(
    close: Sequence[float] | np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """
    Calculate Rate of Change (ROC).

    Formula:
        ROC_t = ((Close_t - Close_{t-period}) / Close_{t-period}) * 100.0

    Safely handles zero or non-finite denominators by returning NaN.
    """
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    roc = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n <= period:
        return roc

    for i in range(period, n):
        denom = c[i - period]
        if np.isfinite(denom) and abs(denom) > 1e-12:
            roc[i] = ((c[i] - denom) / denom) * 100.0
        else:
            roc[i] = np.nan

    return roc
