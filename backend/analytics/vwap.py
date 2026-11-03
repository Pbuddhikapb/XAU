"""
Volume-Weighted Average Price (VWAP) Module for Binance XAUUSDT.
Strictly conforms to Section 5.H of PROJECT_SPECIFICATION.md:
- Anchored to official TradFi Gold CME session start (18:00 New York / 23:00 or 22:00 UTC)
- Anchored to UTC calendar day (00:00:00 UTC)
- Includes VWAP Upper and Lower Standard Deviation Bands (+/- 1 sigma, +/- 2 sigma)
- Delegates directly to authoritative analytical_engine implementation.
"""

from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.indicators.vwap import (
    calculate_daily_vwap,
    calculate_session_anchored_vwap,
    calculate_utc_daily_vwap,
)

__all__ = [
    "calculate_session_anchored_vwap",
    "calculate_utc_daily_vwap",
    "calculate_daily_vwap",
    "evaluate_vwap_position",
]


def evaluate_vwap_position(
    df: pd.DataFrame,
    session_reset_hour_utc: int | None = None,
    session_reset_hour_local: int = 18,
    session_timezone: str = "America/New_York",
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

    vwap_df = calculate_session_anchored_vwap(
        df,
        session_reset_hour_utc=session_reset_hour_utc,
        session_reset_hour_local=session_reset_hour_local,
        session_timezone=session_timezone,
        time_col=time_col,
    )
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

    def safe_num(v: float, decimals: int = 4) -> float | None:
        if np.isnan(v):
            return None
        return round(float(v), decimals)

    return {
        "vwap": safe_num(vwap_val, 4) if not np.isnan(vwap_val) else 0.0,
        "vwap_upper_1": safe_num(u1, 4),
        "vwap_lower_1": safe_num(l1, 4),
        "vwap_upper_2": safe_num(u2, 4),
        "vwap_lower_2": safe_num(l2, 4),
        "distance_pct": safe_num(distance_pct, 4) if not np.isnan(distance_pct) else 0.0,
        "zone": zone,
    }
