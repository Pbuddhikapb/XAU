"""
Momentum Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.B of PROJECT_SPECIFICATION.md:
- RSI 14 (Welles Wilder exact smoothing with arithmetic SMA initialization)
- MACD (12, 26, 9: Fast EMA, Slow EMA, Signal EMA, Histogram)
- Rate of Change (ROC 14)
- Momentum State Evaluation
- Delegates directly to authoritative analytical_engine library.
"""

from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.indicators.momentum import (
    calculate_macd as ae_macd,
)
from analytical_engine.indicators.momentum import (
    calculate_roc as ae_roc,
)
from analytical_engine.indicators.momentum import (
    calculate_rsi as ae_rsi,
)


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Welles Wilder's Relative Strength Index (RSI).
    Delegates to analytical_engine for exact mathematical compliance.
    """
    if len(series) == 0:
        return pd.Series(dtype=np.float64, index=series.index)
    arr = ae_rsi(series.values, period=period)
    return pd.Series(arr, index=series.index, dtype=np.float64)


def calculate_macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """
    Calculate Moving Average Convergence Divergence (MACD).
    Delegates to analytical_engine for exact SMA-seeded EMAs.
    """
    if len(series) == 0:
        empty = pd.Series(dtype=np.float64, index=series.index)
        return pd.DataFrame({"macd": empty, "signal": empty, "hist": empty}, index=series.index)

    res = ae_macd(series.values, fast_period=fast_period, slow_period=slow_period, signal_period=signal_period)
    return pd.DataFrame(
        {
            "macd": res["macd_line"],
            "signal": res["signal_line"],
            "hist": res["histogram"],
        },
        index=series.index,
    )


def calculate_roc(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Rate of Change (ROC).
    Delegates to analytical_engine.
    """
    if len(series) == 0:
        return pd.Series(dtype=np.float64, index=series.index)
    arr = ae_roc(series.values, period=period)
    return pd.Series(arr, index=series.index, dtype=np.float64)


def evaluate_momentum(series: pd.Series) -> dict[str, Any]:
    """
    Evaluate comprehensive momentum state for the latest candle.
    Returns RSI, MACD, ROC values, and qualitative momentum bias.
    """
    if len(series) < 35:
        return {
            "rsi_14": 50.0,
            "macd_val": 0.0,
            "macd_signal": 0.0,
            "macd_hist": 0.0,
            "roc_14": 0.0,
            "momentum_bias": "NEUTRAL",
            "is_overbought": False,
            "is_oversold": False,
        }

    rsi_s = calculate_rsi(series, period=14)
    macd_df = calculate_macd(series, 12, 26, 9)
    roc_s = calculate_roc(series, period=14)

    last_idx = series.index[-1]
    rsi_raw = float(rsi_s.loc[last_idx])
    m_raw = float(macd_df["macd"].loc[last_idx])
    s_raw = float(macd_df["signal"].loc[last_idx])
    h_raw = float(macd_df["hist"].loc[last_idx])
    roc_raw = float(roc_s.loc[last_idx])

    def safe_num(v: float, decimals: int = 4) -> float | None:
        if np.isnan(v):
            return None
        return round(float(v), decimals)

    rsi_val = rsi_raw if not np.isnan(rsi_raw) else 50.0
    h_val = h_raw if not np.isnan(h_raw) else 0.0
    roc_val = roc_raw if not np.isnan(roc_raw) else 0.0

    is_overbought = rsi_val >= 70.0
    is_oversold = rsi_val <= 30.0

    # Determine momentum bias
    if rsi_val > 55.0 and h_val > 0 and roc_val > 0:
        bias = "BULLISH"
    elif rsi_val < 45.0 and h_val < 0 and roc_val < 0:
        bias = "BEARISH"
    elif h_val > 0 and rsi_val >= 50.0:
        bias = "POTENTIAL_BULLISH"
    elif h_val < 0 and rsi_val <= 50.0:
        bias = "POTENTIAL_BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "rsi_14": safe_num(rsi_raw, 2) if not np.isnan(rsi_raw) else 50.0,
        "macd_val": safe_num(m_raw, 4),
        "macd_signal": safe_num(s_raw, 4),
        "macd_hist": safe_num(h_raw, 4),
        "roc_14": safe_num(roc_raw, 4),
        "momentum_bias": bias,
        "is_overbought": is_overbought,
        "is_oversold": is_oversold,
    }
