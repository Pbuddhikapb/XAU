"""
Volume indicators: Moving average, Relative Volume (RVOL), Volume Change,
and Taker Buy/Sell Ratios and Imbalance.
Explicitly labeled as Binance XAUUSDT contract-specific activity.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd


def calculate_volume_ma(
    volume: Sequence[float] | np.ndarray | pd.Series,
    period: int = 20,
) -> np.ndarray:
    """
    Calculate Simple Moving Average of Volume.
    """
    v = np.asarray(volume, dtype=np.float64)
    s = pd.Series(v)
    return s.rolling(window=period, min_periods=period).mean().values


def calculate_rvol(
    volume: Sequence[float] | np.ndarray | pd.Series,
    period: int = 20,
) -> np.ndarray:
    """
    Calculate Relative Volume (RVOL).

    Formula:
        Baseline_t = SMA(Volume_{t-period} ... Volume_{t-1}, period)
        RVOL_t = Volume_t / Baseline_t

    Excludes the current candle from the baseline to prevent self-inflation.
    Returns 1.0 if both current volume and baseline are 0.
    """
    v = np.asarray(volume, dtype=np.float64)
    n = len(v)
    rvol = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n <= period:
        return rvol

    s = pd.Series(v)
    # Shift by 1 so the baseline consists strictly of prior `period` bars
    baseline = s.shift(1).rolling(window=period, min_periods=period).mean().values

    for i in range(period, n):
        base_val = baseline[i]
        curr_vol = v[i]

        if not np.isfinite(base_val):
            continue

        if base_val > 1e-12:
            rvol[i] = curr_vol / base_val
        elif curr_vol == 0.0:
            rvol[i] = 1.0  # Zero volume relative to zero baseline
        else:
            rvol[i] = 10.0  # Spike from zero baseline

    return rvol


def calculate_volume_change(
    volume: Sequence[float] | np.ndarray | pd.Series,
    period: int = 1,
) -> np.ndarray:
    """
    Calculate percentage change in volume over `period` bars.

    Formula:
        VolChange_t = ((Volume_t - Volume_{t-period}) / Volume_{t-period}) * 100.0
    """
    v = np.asarray(volume, dtype=np.float64)
    n = len(v)
    change = np.full(n, np.nan, dtype=np.float64)

    if period <= 0 or n <= period:
        return change

    for i in range(period, n):
        prev = v[i - period]
        curr = v[i]

        if prev > 1e-12:
            change[i] = ((curr - prev) / prev) * 100.0
        elif curr == 0.0 and prev == 0.0:
            change[i] = 0.0
        else:
            change[i] = np.nan

    return change


def calculate_taker_ratios(
    volume: Sequence[float] | np.ndarray | pd.Series,
    taker_buy_volume: Sequence[float] | np.ndarray | pd.Series | None,
) -> dict[str, np.ndarray]:
    """
    Calculate Binance-specific taker order flow dynamics:
        Taker Buy Ratio = TakerBuyVol / TotalVol
        Taker Sell Ratio = (TotalVol - TakerBuyVol) / TotalVol
        Taker Imbalance = (TakerBuyVol - TakerSellVol) / TotalVol

    If taker_buy_volume is None or contains all NaNs, returns all NaNs.
    """
    v = np.asarray(volume, dtype=np.float64)
    n = len(v)

    empty_res = {
        "taker_buy_ratio": np.full(n, np.nan, dtype=np.float64),
        "taker_sell_ratio": np.full(n, np.nan, dtype=np.float64),
        "taker_imbalance": np.full(n, np.nan, dtype=np.float64),
    }

    if taker_buy_volume is None:
        return empty_res

    tbv = np.asarray(taker_buy_volume, dtype=np.float64)
    if len(tbv) != n or not np.isfinite(tbv).any():
        return empty_res

    buy_ratio = np.full(n, np.nan, dtype=np.float64)
    sell_ratio = np.full(n, np.nan, dtype=np.float64)
    imbalance = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        tot = v[i]
        b_vol = tbv[i]

        if not np.isfinite(tot) or not np.isfinite(b_vol):
            continue

        if tot > 1e-12:
            # Bound taker buy volume to not exceed total volume
            clean_b = min(max(b_vol, 0.0), tot)
            clean_s = tot - clean_b

            b_rat = clean_b / tot
            s_rat = clean_s / tot

            buy_ratio[i] = b_rat
            sell_ratio[i] = s_rat
            imbalance[i] = (clean_b - clean_s) / tot
        else:
            # Zero volume period
            buy_ratio[i] = 0.5
            sell_ratio[i] = 0.5
            imbalance[i] = 0.0

    return {
        "taker_buy_ratio": buy_ratio,
        "taker_sell_ratio": sell_ratio,
        "taker_imbalance": imbalance,
    }
