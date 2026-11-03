"""
Trend Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.A of PROJECT_SPECIFICATION.md:
- EMA 20, 50, 100, 200 (SMA seeded Welles Wilder convention)
- ADX 14 and DMI (+DI, -DI) using Wilder's smoothing
- Authoritative Trend Direction and Trend Strength calculations
- Delegates directly to authoritative analytical_engine library.
"""

from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.indicators.moving_averages import calculate_ema_series
from analytical_engine.indicators.trend import calculate_adx as ae_adx


def calculate_ema(series: pd.Series, period: int, min_periods: int | None = None) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).
    Delegates to analytical_engine for exact SMA-seeded formulation.
    """
    if series.empty:
        return pd.Series(dtype=np.float64, index=series.index)
    arr = calculate_ema_series(series.values, period=period)
    return pd.Series(arr, index=series.index, dtype=np.float64)


def calculate_trend_emas(close: pd.Series, periods: tuple[int, ...] = (20, 50, 100, 200)) -> dict[str, pd.Series]:
    """
    Compute multiple EMAs across configured periods.
    Returns dict mapping 'ema_<period>' to resulting pd.Series.
    """
    return {f"ema_{p}": calculate_ema(close, period=p) for p in periods}


def calculate_adx_dmi(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """
    Calculate Wilder's Average Directional Index (ADX) and Directional Movement Index (DMI).
    Delegates to analytical_engine for exact Welles Wilder formulation.
    """
    if len(close) < period + 1:
        empty = pd.Series(np.nan, index=close.index, dtype=np.float64)
        return pd.DataFrame({"plus_di": empty, "minus_di": empty, "dx": empty, "adx": empty}, index=close.index)

    res = ae_adx(high.values, low.values, close.values, period=period)
    return pd.DataFrame(
        {
            "plus_di": res["plus_di"],
            "minus_di": res["minus_di"],
            "dx": res["dx"],
            "adx": res["adx"],
        },
        index=close.index,
    )


def evaluate_trend_direction_and_strength(close: pd.Series, high: pd.Series, low: pd.Series) -> dict[str, Any]:
    """
    Evaluate authoritative trend direction and strength for the latest candle.
    Outputs:
        direction: 'BULLISH' | 'POTENTIAL_BULLISH' | 'NEUTRAL' | 'POTENTIAL_BEARISH' | 'BEARISH'
        strength: float 0.0 to 100.0
        adx: float
        plus_di: float
        minus_di: float
        emas: dict of latest EMA values
    """
    if len(close) < 20:
        return {
            "direction": "NEUTRAL",
            "strength": 0.0,
            "adx": 0.0,
            "plus_di": 0.0,
            "minus_di": 0.0,
            "emas": {},
        }

    emas = calculate_trend_emas(close, periods=(20, 50, 100, 200))
    dmi = calculate_adx_dmi(high, low, close, period=14)

    last_idx = close.index[-1]
    c_val = float(close.loc[last_idx])
    e20 = float(emas["ema_20"].loc[last_idx])
    e50 = float(emas["ema_50"].loc[last_idx])
    e100 = float(emas["ema_100"].loc[last_idx])
    e200 = float(emas["ema_200"].loc[last_idx])

    def safe_num(v: float | None, decimals: int = 4) -> float | None:
        if v is None or np.isnan(v):
            return None
        return round(float(v), decimals)

    adx_val = float(dmi["adx"].loc[last_idx]) if not np.isnan(dmi["adx"].loc[last_idx]) else 20.0
    plus_di_raw = float(dmi["plus_di"].loc[last_idx])
    plus_di_val = plus_di_raw if not np.isnan(plus_di_raw) else 0.0
    minus_di_raw = float(dmi["minus_di"].loc[last_idx])
    minus_di_val = minus_di_raw if not np.isnan(minus_di_raw) else 0.0

    # Direction evaluation
    has_valid_emas = not (np.isnan(e20) or np.isnan(e50) or np.isnan(e100) or np.isnan(e200))
    is_bullish_stack = has_valid_emas and (e20 > e50 > e100 > e200)
    is_bearish_stack = has_valid_emas and (e20 < e50 < e100 < e200)

    if is_bullish_stack and c_val > e20:
        direction = "BULLISH"
    elif is_bearish_stack and c_val < e20:
        direction = "BEARISH"
    elif not np.isnan(e20) and not np.isnan(e50) and e20 > e50 and (np.isnan(e200) or c_val > e200):
        direction = "POTENTIAL_BULLISH"
    elif not np.isnan(e20) and not np.isnan(e50) and e20 < e50 and (np.isnan(e200) or c_val < e200):
        direction = "POTENTIAL_BEARISH"
    else:
        direction = "NEUTRAL"

    # Strength calculation: normalize ADX (typically 10-60) to 0-100 scale
    # ADX >= 50 indicates maximum trend strength
    strength = min(100.0, max(0.0, (adx_val / 50.0) * 100.0))

    return {
        "direction": direction,
        "strength": round(strength, 2),
        "adx": round(adx_val, 2),
        "plus_di": round(plus_di_val, 2),
        "minus_di": round(minus_di_val, 2),
        "emas": {
            "ema_20": safe_num(e20, 4),
            "ema_50": safe_num(e50, 4),
            "ema_100": safe_num(e100, 4),
            "ema_200": safe_num(e200, 4),
        },
    }
