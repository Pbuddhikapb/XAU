"""
Moving average calculations: Simple Moving Average (SMA) and Exponential Moving Average (EMA).
Mathematically exact, vectorized, and deterministic implementations.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd


def calculate_sma_series(values: Sequence[float] | np.ndarray | pd.Series, period: int) -> np.ndarray:
    """
    Calculate Simple Moving Average (SMA) series across a 1D sequence.

    Returns an array of identical length with NaN for indices < period - 1.
    """
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    sma = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n < period:
        return sma

    # Efficient convolution or cumulative sum for SMA
    cumsum = np.cumsum(np.insert(arr, 0, 0.0))
    sma[period - 1 :] = (cumsum[period:] - cumsum[:-period]) / period
    return sma


def calculate_ema_series(
    values: Sequence[float] | np.ndarray | pd.Series,
    period: int,
    alpha: float | None = None,
) -> np.ndarray:
    """
    Calculate Exponential Moving Average (EMA) series across a 1D sequence.

    Formula:
        alpha = 2 / (period + 1)
        EMA_t = alpha * Value_t + (1 - alpha) * EMA_{t-1}

    Initialization Convention:
        The EMA is seeded with the SMA of the first `period` valid observations at index `period - 1`.
        Prefix indices (< period - 1) return NaN.
    """
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    ema = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n < period:
        return ema

    smooth_alpha = alpha if alpha is not None else (2.0 / (period + 1.0))

    # Seed with SMA of the first `period` bars
    seed_sma = np.mean(arr[:period])
    ema[period - 1] = seed_sma

    # Iterative recurrence for numerical precision
    curr_ema = seed_sma
    one_minus_alpha = 1.0 - smooth_alpha

    for i in range(period, n):
        val = arr[i]
        if np.isnan(val):
            # If input is NaN, EMA remains NaN and resets seed on next valid observation
            curr_ema = np.nan
            ema[i] = np.nan
        elif np.isnan(curr_ema):
            # Attempt to re-seed if sufficient observations follow
            if i + period <= n:
                curr_ema = np.mean(arr[i : i + period])
                ema[i + period - 1] = curr_ema
        else:
            curr_ema = (smooth_alpha * val) + (one_minus_alpha * curr_ema)
            ema[i] = curr_ema

    return ema
