"""
Trend Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.A of PROJECT_SPECIFICATION.md:
- EMA 20, 50, 100, 200
- ADX 14 and DMI (+DI, -DI) using Wilder's smoothing
- Authoritative Trend Direction and Trend Strength calculations
"""

from typing import Any

import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int, min_periods: int | None = None) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).
    Formula: EMA_t = alpha * P_t + (1 - alpha) * EMA_{t-1}, where alpha = 2 / (period + 1).
    """
    if series.empty:
        return pd.Series(dtype=np.float64, index=series.index)
    min_p = min(period, 5) if min_periods is None else min_periods
    return series.ewm(span=period, adjust=False, min_periods=min_p).mean()


def calculate_trend_emas(close: pd.Series, periods: tuple[int, ...] = (20, 50, 100, 200)) -> dict[str, pd.Series]:
    """
    Compute multiple EMAs across configured periods.
    Returns dict mapping 'ema_<period>' to resulting pd.Series.
    """
    return {f"ema_{p}": calculate_ema(close, period=p) for p in periods}


def calculate_adx_dmi(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """
    Calculate Wilder's Average Directional Index (ADX) and Directional Movement Index (DMI).

    Formulas:
        TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
        +DM_t = H_t - H_{t-1} if (H_t - H_{t-1} > L_{t-1} - L_t and H_t - H_{t-1} > 0) else 0
        -DM_t = L_{t-1} - L_t if (L_{t-1} - L_t > H_t - H_{t-1} and L_{t-1} - L_t > 0) else 0
        +DI = 100 * WilderSmooth(+DM, period) / WilderSmooth(TR, period)
        -DI = 100 * WilderSmooth(-DM, period) / WilderSmooth(TR, period)
        DX = 100 * |+DI - -DI| / (+DI + -DI)
        ADX = WilderSmooth(DX, period)
    """
    if len(close) < period + 1:
        empty = pd.Series(np.nan, index=close.index, dtype=np.float64)
        return pd.DataFrame({"plus_di": empty, "minus_di": empty, "dx": empty, "adx": empty})

    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=close.index, dtype=np.float64)
    minus_dm_s = pd.Series(minus_dm, index=close.index, dtype=np.float64)

    # Wilder's smoothing: alpha = 1 / period
    tr_smooth = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_dm_smooth = plus_dm_s.ewm(alpha=1.0 / period, adjust=False).mean()
    minus_dm_smooth = minus_dm_s.ewm(alpha=1.0 / period, adjust=False).mean()

    # Prevent division by zero
    eps = 1e-9
    plus_di = 100.0 * (plus_dm_smooth / (tr_smooth + eps))
    minus_di = 100.0 * (minus_dm_smooth / (tr_smooth + eps))

    di_sum = plus_di + minus_di + eps
    dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()

    # Mask initial warmup periods with NaN
    if len(close) >= period * 2:
        adx.iloc[: period * 2 - 1] = np.nan

    return pd.DataFrame(
        {
            "plus_di": plus_di,
            "minus_di": minus_di,
            "dx": dx,
            "adx": adx,
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
