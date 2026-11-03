"""
Trend indicators: Multi-period EMA ribbon, Directional Movement (+DI/-DI), and ADX.
Strictly implements Wilder's smoothing with defined warm-up boundaries.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from analytical_engine.indicators.moving_averages import calculate_ema_series


def calculate_ema_ribbon(
    close: Sequence[float] | np.ndarray | pd.Series,
    periods: list[int] | None = None,
) -> dict[str, np.ndarray]:
    """
    Calculate multi-period Exponential Moving Average (EMA) ribbon.
    Returns dict mapping 'ema_{period}' to numpy array.
    """
    if periods is None:
        periods = [20, 50, 100, 200]
    results = {}
    for p in periods:
        results[f"ema_{p}"] = calculate_ema_series(close, period=p)
    return results


def calculate_adx(
    high: Sequence[float] | np.ndarray | pd.Series,
    low: Sequence[float] | np.ndarray | pd.Series,
    close: Sequence[float] | np.ndarray | pd.Series,
    period: int = 14,
) -> dict[str, np.ndarray]:
    """
    Calculate Welles Wilder's Average Directional Index (ADX), +DI, and -DI.

    Formulas:
        TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
        +DM_t = (High_t - High_{t-1}) if (High_t - High_{t-1}) > (Low_{t-1} - Low_t) and > 0 else 0
        -DM_t = (Low_{t-1} - Low_t) if (Low_{t-1} - Low_t) > (High_t - High_{t-1}) and > 0 else 0

        Wilder Smoothing for TR, +DM, -DM:
            Smooth_t = Smooth_{t-1} * (period - 1) / period + Value_t

        +DI_t = 100 * (+DM_Smooth_t / TR_Smooth_t)
        -DI_t = 100 * (-DM_Smooth_t / TR_Smooth_t)
        DX_t = 100 * |+DI_t - -DI_t| / (+DI_t + -DI_t)
        ADX_t = WilderSmooth(DX_t, period)

    Returns:
        Dict with keys: 'plus_di', 'minus_di', 'dx', 'adx'
    """
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(high_arr)

    empty_res = {
        "plus_di": np.full(n, np.nan, dtype=np.float64),
        "minus_di": np.full(n, np.nan, dtype=np.float64),
        "dx": np.full(n, np.nan, dtype=np.float64),
        "adx": np.full(n, np.nan, dtype=np.float64),
    }

    if period <= 0 or n < (2 * period):
        return empty_res

    # 1. Compute raw TR, +DM, -DM
    tr = np.zeros(n, dtype=np.float64)
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)

    # First bar TR is simply High - Low
    tr[0] = high_arr[0] - low_arr[0]

    for i in range(1, n):
        hl = high_arr[i] - low_arr[i]
        hc = abs(high_arr[i] - close_arr[i - 1])
        lc = abs(low_arr[i] - close_arr[i - 1])
        tr[i] = max(hl, hc, lc)

        up_move = high_arr[i] - high_arr[i - 1]
        down_move = low_arr[i - 1] - low_arr[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0.0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0.0

    # 2. Wilder's Smoothing for TR, +DM, -DM
    smooth_tr = np.full(n, np.nan, dtype=np.float64)
    smooth_pdm = np.full(n, np.nan, dtype=np.float64)
    smooth_mdm = np.full(n, np.nan, dtype=np.float64)

    # Initial seed: SMA of first `period` bars (indices 0 to period-1)
    smooth_tr[period - 1] = np.mean(tr[:period])
    smooth_pdm[period - 1] = np.mean(plus_dm[:period])
    smooth_mdm[period - 1] = np.mean(minus_dm[:period])

    decay = (period - 1.0) / period
    inv_period = 1.0 / period

    for i in range(period, n):
        smooth_tr[i] = (smooth_tr[i - 1] * decay) + tr[i] * inv_period
        smooth_pdm[i] = (smooth_pdm[i - 1] * decay) + plus_dm[i] * inv_period
        smooth_mdm[i] = (smooth_mdm[i - 1] * decay) + minus_dm[i] * inv_period

    # 3. Compute +DI, -DI, and DX
    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)
    dx = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        str_val = smooth_tr[i]
        if str_val > 1e-12:
            p_di = 100.0 * (smooth_pdm[i] / str_val)
            m_di = 100.0 * (smooth_mdm[i] / str_val)
        else:
            p_di = 0.0
            m_di = 0.0

        plus_di[i] = p_di
        minus_di[i] = m_di

        di_sum = p_di + m_di
        if di_sum > 1e-12:
            dx[i] = 100.0 * (abs(p_di - m_di) / di_sum)
        else:
            dx[i] = 0.0

    # 4. Compute ADX via Wilder's Smoothing of DX
    adx = np.full(n, np.nan, dtype=np.float64)
    adx_start_idx = (2 * period) - 2

    if n > adx_start_idx:
        # Seed ADX with SMA of the first `period` DX values (indices period-1 to 2*period-2)
        dx_window = dx[period - 1 : adx_start_idx + 1]
        adx[adx_start_idx] = np.mean(dx_window)

        for i in range(adx_start_idx + 1, n):
            adx[i] = ((adx[i - 1] * (period - 1.0)) + dx[i]) / period

    return {
        "plus_di": plus_di,
        "minus_di": minus_di,
        "dx": dx,
        "adx": adx,
    }
