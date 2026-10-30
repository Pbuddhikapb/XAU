"""
Volume-Weighted Average Price (VWAP) Module for Binance XAUUSDT.
Strictly conforms to Section 5.H of PROJECT_SPECIFICATION.md:
- Anchored to official TradFi Gold CME session start (23:00 UTC daily)
- Includes VWAP Upper and Lower Standard Deviation Bands (+/- 1 sigma, +/- 2 sigma)
- Pure vectorized pandas implementation
"""

from typing import Any

import numpy as np
import pandas as pd


def calculate_session_anchored_vwap(
    df: pd.DataFrame,
    session_reset_hour_utc: int = 23,
    time_col: str = "open_time",
) -> pd.DataFrame:
    """
    Calculate Volume Weighted Average Price (VWAP) anchored to the daily 23:00 UTC session open.

    Formulas:
        Typical Price TP_t = (High_t + Low_t + Close_t) / 3
        VWAP_t = sum(TP_k * Volume_k) / sum(Volume_k) from session start s to t
        Sigma_VWAP = sqrt( sum(Volume_k * (TP_k - VWAP_t)^2) / sum(Volume_k) )
        Upper Band 1 = VWAP + 1 * Sigma
        Lower Band 1 = VWAP - 1 * Sigma
        Upper Band 2 = VWAP + 2 * Sigma
        Lower Band 2 = VWAP - 2 * Sigma
    """
    if df.empty:
        empty = pd.Series(dtype=np.float64)
        return pd.DataFrame(
            {"vwap": empty, "vwap_upper_1": empty, "vwap_lower_1": empty, "vwap_upper_2": empty, "vwap_lower_2": empty}
        )

    candles = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(candles[time_col]):
        candles[time_col] = pd.to_datetime(candles[time_col], utc=True)
    elif candles[time_col].dt.tz is None:
        candles[time_col] = candles[time_col].dt.tz_localize("UTC")

    # Shift time by -23 hours so that 23:00 UTC marks the start of a calendar date bucket
    shifted_time = candles[time_col] - pd.Timedelta(hours=session_reset_hour_utc)
    candles["_session_id"] = shifted_time.dt.floor("1D")

    # Typical Price
    tp = (candles["high"] + candles["low"] + candles["close"]) / 3.0
    vol = candles["volume"].fillna(0.0)
    tp_vol = tp * vol

    candles["_tp"] = tp
    candles["_tp_vol"] = tp_vol

    # Group by session and cumsum
    grouped = candles.groupby("_session_id", sort=False)
    cum_tp_vol = grouped["_tp_vol"].cumsum()
    cum_vol = grouped["volume"].cumsum()

    eps = 1e-9
    vwap = cum_tp_vol / (cum_vol + eps)

    # Calculate VWAP variance & standard deviation
    candles["_vwap"] = vwap
    candles["_diff_sq_vol"] = vol * (tp - vwap) ** 2
    cum_diff_sq_vol = candles.groupby("_session_id", sort=False)["_diff_sq_vol"].cumsum()
    variance = cum_diff_sq_vol / (cum_vol + eps)
    std_dev = np.sqrt(variance.clip(lower=0.0))

    upper_1 = vwap + std_dev
    lower_1 = vwap - std_dev
    upper_2 = vwap + (2.0 * std_dev)
    lower_2 = vwap - (2.0 * std_dev)

    return pd.DataFrame(
        {
            "vwap": vwap,
            "vwap_upper_1": upper_1,
            "vwap_lower_1": lower_1,
            "vwap_upper_2": upper_2,
            "vwap_lower_2": lower_2,
            "vwap_std": std_dev,
        },
        index=candles.index,
    )


def evaluate_vwap_position(
    df: pd.DataFrame,
    session_reset_hour_utc: int = 23,
    time_col: str = "open_time",
) -> dict[str, Any]:
    """
    Evaluate latest price relation to session-anchored VWAP and standard deviation bands.
    """
    if df.empty or len(df) < 1:
        return {
            "vwap": 0.0,
            "vwap_upper_1": 0.0,
            "vwap_lower_1": 0.0,
            "vwap_upper_2": 0.0,
            "vwap_lower_2": 0.0,
            "distance_pct": 0.0,
            "zone": "AT_VWAP",
        }

    vwap_df = calculate_session_anchored_vwap(df, session_reset_hour_utc, time_col)
    last_idx = df.index[-1]

    close_p = float(df.loc[last_idx, "close"])
    vwap_val = float(vwap_df.loc[last_idx, "vwap"])
    u1 = float(vwap_df.loc[last_idx, "vwap_upper_1"])
    l1 = float(vwap_df.loc[last_idx, "vwap_lower_1"])
    u2 = float(vwap_df.loc[last_idx, "vwap_upper_2"])
    l2 = float(vwap_df.loc[last_idx, "vwap_lower_2"])

    eps = 1e-9
    distance_pct = ((close_p - vwap_val) / (vwap_val + eps)) * 100.0

    if close_p > u2:
        zone = "EXTREME_OVERBOUGHT"
    elif close_p > u1:
        zone = "MODERATELY_ABOVE"
    elif close_p < l2:
        zone = "EXTREME_OVERSOLD"
    elif close_p < l1:
        zone = "MODERATELY_BELOW"
    else:
        zone = "AT_VWAP"

    return {
        "vwap": round(vwap_val, 4),
        "vwap_upper_1": round(u1, 4),
        "vwap_lower_1": round(l1, 4),
        "vwap_upper_2": round(u2, 4),
        "vwap_lower_2": round(l2, 4),
        "distance_pct": round(distance_pct, 4),
        "zone": zone,
    }
