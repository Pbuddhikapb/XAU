"""
Volume-Weighted Average Price (VWAP) calculation engine.
Provides:
1. TradFi session-anchored VWAP with standard deviation bands (+/- 1 sigma, +/- 2 sigma),
   dynamically anchored to the CME Globex Gold session reset (18:00 ET in America/New_York),
   automatically handling US Daylight Saving Time (EDT vs EST) transitions.
2. Daily anchored VWAP strictly resetting at 00:00:00 UTC calendar day boundary.
3. Explicit metadata columns: anchor_type ('TRADIFI_SESSION' vs 'UTC_CALENDAR_DAY') and anchor_time.
"""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CME_TIMEZONE = ZoneInfo("America/New_York")


def calculate_session_anchored_vwap(
    df: pd.DataFrame,
    session_reset_hour_utc: int | None = None,
    session_reset_hour_local: int = 18,
    session_timezone: str | ZoneInfo = "America/New_York",
    time_col: str = "open_time",
) -> pd.DataFrame:
    """
    Calculate Volume Weighted Average Price (VWAP) anchored to TradFi Gold session reset.
    By default, anchors dynamically to 18:00 New York Time (CME Globex calendar):
    - In EDT (summer/autumn): resets at 22:00:00 UTC
    - In EST (winter): resets at 23:00:00 UTC

    If session_reset_hour_utc is explicitly provided, uses that static UTC hour instead.

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
            {
                "vwap": empty,
                "vwap_upper_1": empty,
                "vwap_lower_1": empty,
                "vwap_upper_2": empty,
                "vwap_lower_2": empty,
                "vwap_std": empty,
                "cum_volume": empty,
                "anchor_type": pd.Series(dtype=str),
                "anchor_time": pd.Series(dtype="datetime64[ns, UTC]"),
            }
        )

    candles = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(candles[time_col]):
        candles[time_col] = pd.to_datetime(candles[time_col], utc=True)
    elif candles[time_col].dt.tz is None:
        candles[time_col] = candles[time_col].dt.tz_localize("UTC")
    else:
        candles[time_col] = candles[time_col].dt.tz_convert("UTC")

    tz_obj = ZoneInfo(session_timezone) if isinstance(session_timezone, str) else session_timezone

    if session_reset_hour_utc is not None:
        # Static UTC hour override
        shifted_time = candles[time_col] - pd.Timedelta(hours=session_reset_hour_utc)
        session_id = shifted_time.dt.floor("1D")
        anchor_times = session_id + pd.Timedelta(hours=session_reset_hour_utc)
    else:
        # Dynamic timezone-aware session anchoring
        local_times = candles[time_col].dt.tz_convert(tz_obj)
        shifted_local = local_times - pd.Timedelta(hours=session_reset_hour_local)
        session_id = shifted_local.dt.floor("1D")
        # Anchor timestamp in UTC
        anchor_local = session_id + pd.Timedelta(hours=session_reset_hour_local)
        anchor_times = anchor_local.dt.tz_convert("UTC")

    candles["_session_id"] = session_id

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

    safe_cum_vol = np.where(cum_vol > 0, cum_vol, 1.0)
    vwap_arr = np.where(cum_vol > 0, cum_tp_vol / safe_cum_vol, tp)
    vwap = pd.Series(vwap_arr, index=candles.index, dtype=np.float64)

    # Calculate VWAP variance & standard deviation
    candles["_vwap"] = vwap
    candles["_diff_sq_vol"] = vol * (tp - vwap) ** 2
    cum_diff_sq_vol = candles.groupby("_session_id", sort=False)["_diff_sq_vol"].cumsum()
    variance = np.where(cum_vol > 0, cum_diff_sq_vol / safe_cum_vol, 0.0)
    std_dev = pd.Series(np.sqrt(np.maximum(variance, 0.0)), index=candles.index, dtype=np.float64)

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
            "cum_volume": cum_vol,
            "anchor_type": "TRADIFI_SESSION",
            "anchor_time": anchor_times,
        },
        index=candles.index,
    )


def calculate_utc_daily_vwap(
    df: pd.DataFrame,
    time_col: str = "open_time",
) -> pd.DataFrame:
    """
    Calculate Daily Anchored Volume-Weighted Average Price (VWAP) strictly resetting
    at 00:00:00 UTC calendar day boundary.
    """
    if df.empty:
        empty = pd.Series(dtype=np.float64)
        return pd.DataFrame(
            {
                "vwap": empty,
                "vwap_upper_1": empty,
                "vwap_lower_1": empty,
                "vwap_upper_2": empty,
                "vwap_lower_2": empty,
                "vwap_std": empty,
                "cum_volume": empty,
                "anchor_type": pd.Series(dtype=str),
                "anchor_time": pd.Series(dtype="datetime64[ns, UTC]"),
            }
        )

    candles = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(candles[time_col]):
        candles[time_col] = pd.to_datetime(candles[time_col], utc=True)
    elif candles[time_col].dt.tz is None:
        candles[time_col] = candles[time_col].dt.tz_localize("UTC")
    else:
        candles[time_col] = candles[time_col].dt.tz_convert("UTC")

    session_id = candles[time_col].dt.floor("1D")
    candles["_session_id"] = session_id

    tp = (candles["high"] + candles["low"] + candles["close"]) / 3.0
    vol = candles["volume"].fillna(0.0)
    tp_vol = tp * vol

    candles["_tp"] = tp
    candles["_tp_vol"] = tp_vol

    grouped = candles.groupby("_session_id", sort=False)
    cum_tp_vol = grouped["_tp_vol"].cumsum()
    cum_vol = grouped["volume"].cumsum()

    safe_cum_vol = np.where(cum_vol > 0, cum_vol, 1.0)
    vwap_arr = np.where(cum_vol > 0, cum_tp_vol / safe_cum_vol, tp)
    vwap = pd.Series(vwap_arr, index=candles.index, dtype=np.float64)

    candles["_vwap"] = vwap
    candles["_diff_sq_vol"] = vol * (tp - vwap) ** 2
    cum_diff_sq_vol = candles.groupby("_session_id", sort=False)["_diff_sq_vol"].cumsum()
    variance = np.where(cum_vol > 0, cum_diff_sq_vol / safe_cum_vol, 0.0)
    std_dev = pd.Series(np.sqrt(np.maximum(variance, 0.0)), index=candles.index, dtype=np.float64)

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
            "cum_volume": cum_vol,
            "anchor_type": "UTC_CALENDAR_DAY",
            "anchor_time": session_id,
        },
        index=candles.index,
    )


def calculate_daily_vwap(df: pd.DataFrame) -> dict[str, np.ndarray | list]:
    """
    Backward-compatible dictionary interface for UTC calendar day VWAP.
    """
    res_df = calculate_utc_daily_vwap(df)
    return {
        "vwap": res_df["vwap"].to_numpy(),
        "cum_volume": res_df["cum_volume"].to_numpy(),
        "anchor_time": res_df["anchor_time"].tolist(),
    }
