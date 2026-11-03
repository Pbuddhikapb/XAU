"""
Volatility Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.C of PROJECT_SPECIFICATION.md:
- ATR 14 (Welles Wilder exact smoothing)
- Bollinger Bands (20, 2.0: Upper, Middle, Lower, Bandwidth, %B, ddof=1)
- Volatility Expansion & Contraction (Squeeze Detection)
- Historical Volatility Percentile
- Delegates directly to authoritative analytical_engine library.
"""

from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.indicators.moving_averages import calculate_sma_series
from analytical_engine.indicators.volatility import (
    calculate_atr as ae_atr,
)
from analytical_engine.indicators.volatility import (
    calculate_bollinger_bands as ae_bb,
)
from analytical_engine.indicators.volatility import (
    calculate_volatility_percentile as ae_pct,
)


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Welles Wilder's Average True Range (ATR).
    Delegates to analytical_engine for exact mathematical compliance.
    """
    if len(close) < period:
        return pd.Series(np.nan, index=close.index, dtype=np.float64)

    arr = ae_atr(high.values, low.values, close.values, period=period)
    return pd.Series(arr, index=close.index, dtype=np.float64)


def calculate_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """
    Calculate Bollinger Bands, Bandwidth, and %B with sample standard deviation (ddof=1).
    Delegates to analytical_engine.
    """
    if len(series) < period:
        empty = pd.Series(np.nan, index=series.index, dtype=np.float64)
        return pd.DataFrame(
            {"upper": empty, "middle": empty, "lower": empty, "bandwidth": empty, "pct_b": empty},
            index=series.index,
        )

    res = ae_bb(series.values, period=period, num_std=num_std, ddof=1)
    return pd.DataFrame(
        {
            "upper": res["upper"],
            "middle": res["middle"],
            "lower": res["lower"],
            "bandwidth": res["bandwidth"],
            "pct_b": res["percent_b"],
        },
        index=series.index,
    )


def calculate_historical_volatility_percentile(atr_series: pd.Series, lookback: int = 100) -> pd.Series:
    """
    Calculate rolling historical percentile rank (0.0 to 100.0) of current ATR
    relative to past `lookback` periods.
    Delegates to analytical_engine.
    """
    if len(atr_series) < 2:
        return pd.Series(50.0, index=atr_series.index, dtype=np.float64)

    arr = ae_pct(atr_series.values, lookback=lookback)
    s = pd.Series(arr, index=atr_series.index, dtype=np.float64).fillna(50.0)
    return s


def evaluate_volatility_regime(high: pd.Series, low: pd.Series, close: pd.Series) -> dict[str, Any]:
    """
    Evaluate comprehensive volatility conditions for the latest candle.
    Identifies expansions, squeezes (contractions), and percentile ranking.
    """
    if len(close) < 20:
        return {
            "atr_14": 0.0,
            "bb_upper": 0.0,
            "bb_middle": 0.0,
            "bb_lower": 0.0,
            "bandwidth": 0.0,
            "pct_b": 0.5,
            "volatility_percentile": 50.0,
            "regime": "NORMAL",
            "is_squeeze": False,
            "is_expanding": False,
        }

    atr_s = calculate_atr(high, low, close, period=14)
    bb_df = calculate_bollinger_bands(close, period=20, num_std=2.0)
    vol_pct_s = calculate_historical_volatility_percentile(atr_s, lookback=100)

    last_idx = close.index[-1]
    atr_val = float(atr_s.loc[last_idx]) if not np.isnan(atr_s.loc[last_idx]) else 0.0
    u_raw = float(bb_df["upper"].loc[last_idx])
    m_raw = float(bb_df["middle"].loc[last_idx])
    l_raw = float(bb_df["lower"].loc[last_idx])
    bw_raw = float(bb_df["bandwidth"].loc[last_idx])
    pct_b_raw = float(bb_df["pct_b"].loc[last_idx])
    vol_pct_raw = float(vol_pct_s.loc[last_idx])
    vol_pct = vol_pct_raw if not np.isnan(vol_pct_raw) else 50.0

    def safe_num(v: float, decimals: int = 4) -> float | None:
        if np.isnan(v):
            return None
        return round(float(v), decimals)

    # Squeeze: Bandwidth in lowest 15% of recent 50 bars
    recent_bw = bb_df["bandwidth"].dropna().tail(50)
    if len(recent_bw) >= 10 and not np.isnan(bw_raw):
        bw_threshold = float(np.percentile(recent_bw, 15))
        is_squeeze = bw_raw <= bw_threshold
    else:
        is_squeeze = False

    # Expanding: Bandwidth rising sharply above rolling 20 MA of bandwidth
    bw_ma_series = calculate_sma_series(bb_df["bandwidth"].to_numpy(), period=20)
    bw_ma = float(bw_ma_series[-1])
    is_expanding = bw_raw > bw_ma * 1.25 if not (np.isnan(bw_ma) or np.isnan(bw_raw)) else False

    if is_squeeze:
        regime = "COMPRESSED_SQUEEZE"
    elif is_expanding:
        regime = "HIGH_VOLATILITY_EXPANSION"
    elif vol_pct > 75.0:
        regime = "ELEVATED"
    elif vol_pct < 25.0:
        regime = "SUBDUED"
    else:
        regime = "NORMAL"

    return {
        "atr_14": round(atr_val, 4),
        "bb_upper": safe_num(u_raw, 4),
        "bb_middle": safe_num(m_raw, 4),
        "bb_lower": safe_num(l_raw, 4),
        "bandwidth": safe_num(bw_raw, 6),
        "pct_b": safe_num(pct_b_raw, 4),
        "volatility_percentile": round(vol_pct, 2),
        "regime": regime,
        "is_squeeze": is_squeeze,
        "is_expanding": is_expanding,
    }
