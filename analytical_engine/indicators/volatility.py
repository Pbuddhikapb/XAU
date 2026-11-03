"""
Volatility indicators: True Range, Average True Range (ATR), Bollinger Bands,
Historical Volatility, and Causal Volatility Percentile.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd


def calculate_true_range(
    high: Sequence[float] | np.ndarray | pd.Series,
    low: Sequence[float] | np.ndarray | pd.Series,
    close: Sequence[float] | np.ndarray | pd.Series,
) -> np.ndarray:
    """
    Calculate True Range (TR).

    Formula:
        TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
        TR_0 = High_0 - Low_0
    """
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(high_arr)

    tr = np.zeros(n, dtype=np.float64)
    if n == 0:
        return tr

    tr[0] = high_arr[0] - low_arr[0]
    for i in range(1, n):
        hl = high_arr[i] - low_arr[i]
        hc = abs(high_arr[i] - close_arr[i - 1])
        lc = abs(low_arr[i] - close_arr[i - 1])
        tr[i] = max(hl, hc, lc)

    return tr


def calculate_atr(
    high: Sequence[float] | np.ndarray | pd.Series,
    low: Sequence[float] | np.ndarray | pd.Series,
    close: Sequence[float] | np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """
    Calculate Welles Wilder's Average True Range (ATR).

    Convention:
        - True Range is computed across all bars.
        - First ATR value at index `period - 1` is seeded with the SMA of the first `period` TR values.
        - Subsequent values follow Wilder's recurrence:
            ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
        - Returns NaN for indices < period - 1.
    """
    tr = calculate_true_range(high, low, close)
    n = len(tr)
    atr = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n < period:
        return atr

    # Seed with SMA of first `period` bars
    atr[period - 1] = np.mean(tr[:period])
    decay = period - 1.0

    for i in range(period, n):
        atr[i] = (atr[i - 1] * decay + tr[i]) / period

    return atr


def calculate_bollinger_bands(
    close: Sequence[float] | np.ndarray | pd.Series,
    period: int = 20,
    num_std: float = 2.0,
    ddof: int = 1,
) -> dict[str, np.ndarray]:
    """
    Calculate Bollinger Bands (Middle, Upper, Lower, Bandwidth, %B).

    Convention:
        - Middle Band = SMA(Close, period)
        - Standard Deviation = Rolling sample standard deviation (ddof=1)
        - Upper Band = Middle + num_std * Std
        - Lower Band = Middle - num_std * Std
        - Bandwidth = (Upper - Lower) / Middle
        - %B = (Close - Lower) / (Upper - Lower)

    Protected against zero standard deviation or zero bandwidth.
    """
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    empty_res = {
        "middle": np.full(n, np.nan, dtype=np.float64),
        "upper": np.full(n, np.nan, dtype=np.float64),
        "lower": np.full(n, np.nan, dtype=np.float64),
        "bandwidth": np.full(n, np.nan, dtype=np.float64),
        "percent_b": np.full(n, np.nan, dtype=np.float64),
    }

    if period <= 1 or n < period:
        return empty_res

    # Use pandas rolling for numerical precision with sample standard deviation
    s = pd.Series(c)
    middle = s.rolling(window=period, min_periods=period).mean().values
    std = s.rolling(window=period, min_periods=period).std(ddof=ddof).values

    upper = middle + (num_std * std)
    lower = middle - (num_std * std)

    # Bandwidth: (Upper - Lower) / Middle
    with np.errstate(divide="ignore", invalid="ignore"):
        bandwidth = np.where(middle > 1e-12, (upper - lower) / middle, 0.0)

        # %B: (Close - Lower) / (Upper - Lower)
        denom = upper - lower
        percent_b = np.where(denom > 1e-12, (c - lower) / denom, 0.5)

    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "bandwidth": bandwidth,
        "percent_b": percent_b,
    }


def calculate_historical_volatility(
    close: Sequence[float] | np.ndarray | pd.Series,
    window: int = 20,
    annualize: bool = False,
    annualization_factor: float = np.sqrt(365.25),
) -> np.ndarray:
    """
    Calculate Historical Volatility based on log returns standard deviation.

    Formula:
        r_t = ln(Close_t / Close_{t-1})
        HV_t = std(r_{t-window+1 : t}, ddof=1)
        If annualize=True, multiplied by annualization_factor.
    """
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    hv = np.full(n, np.nan, dtype=np.float64)

    if window <= 1 or n <= window:
        return hv

    # Calculate log returns
    with np.errstate(divide="ignore", invalid="ignore"):
        log_returns = np.diff(np.log(c))  # length n-1

    s_ret = pd.Series(log_returns)
    roll_std = s_ret.rolling(window=window, min_periods=window).std(ddof=1).values

    # Offset by 1 because log_returns is length n-1
    hv[1:] = roll_std
    if annualize:
        hv[1:] *= annualization_factor

    return hv


def calculate_volatility_percentile(
    series: Sequence[float] | np.ndarray | pd.Series,
    lookback: int = 100,
) -> np.ndarray:
    """
    Calculate strictly causal Volatility Percentile rank of current metric
    against its historical values over the preceding `lookback` observations.

    Formula:
        Percentile_t = (Count(Metric_i <= Metric_t for i in [t-lookback+1, t]) / lookback) * 100.0

    No future data is ever inspected. Returns NaN for indices < lookback - 1.
    """
    arr = np.asarray(series, dtype=np.float64)
    n = len(arr)
    pct = np.full(n, np.nan, dtype=np.float64)

    if lookback <= 0 or n < lookback:
        return pct

    for i in range(lookback - 1, n):
        window = arr[i - lookback + 1 : i + 1]
        valid_vals = window[np.isfinite(window)]
        if len(valid_vals) < (lookback // 2):
            continue

        curr_val = arr[i]
        if not np.isfinite(curr_val):
            continue

        count_le = np.sum(valid_vals <= curr_val)
        pct[i] = (count_le / len(valid_vals)) * 100.0

    return pct
