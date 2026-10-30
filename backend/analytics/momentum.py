"""
Momentum Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.B of PROJECT_SPECIFICATION.md:
- RSI 14 (Wilder's exponential smoothing)
- MACD (12, 26, 9: Fast EMA, Slow EMA, Signal EMA, Histogram)
- Rate of Change (ROC 14)
- Momentum State Evaluation
"""

from typing import Any

import numpy as np
import pandas as pd

from backend.analytics.trend import calculate_ema


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Wilder's Relative Strength Index (RSI).

    Formula:
        delta = P_t - P_{t-1}
        U = max(delta, 0), D = max(-delta, 0)
        AvgGain = WilderSmooth(U, period)
        AvgLoss = WilderSmooth(D, period)
        RS = AvgGain / (AvgLoss + epsilon)
        RSI = 100 - (100 / (1 + RS))
    """
    if len(series) < period + 1:
        return pd.Series(np.nan, index=series.index, dtype=np.float64)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    # Wilder's smoothing: alpha = 1 / period
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    eps = 1e-9
    rs = avg_gain / (avg_loss + eps)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Clean up warmup index
    rsi.iloc[:period] = np.nan
    return rsi


def calculate_macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """
    Calculate Moving Average Convergence Divergence (MACD).

    Formula:
        MACD_Line = EMA(series, fast_period) - EMA(series, slow_period)
        Signal_Line = EMA(MACD_Line, signal_period)
        Histogram = MACD_Line - Signal_Line
    """
    if len(series) < slow_period:
        empty = pd.Series(np.nan, index=series.index, dtype=np.float64)
        return pd.DataFrame({"macd": empty, "signal": empty, "hist": empty})

    fast_ema = calculate_ema(series, period=fast_period)
    slow_ema = calculate_ema(series, period=slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = calculate_ema(macd_line, period=signal_period)
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "hist": histogram,
        },
        index=series.index,
    )


def calculate_roc(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Rate of Change (ROC).

    Formula:
        ROC_t = 100 * (P_t - P_{t-period}) / P_{t-period}
    """
    if len(series) < period + 1:
        return pd.Series(np.nan, index=series.index, dtype=np.float64)

    prev_p = series.shift(period)
    eps = 1e-9
    return 100.0 * ((series - prev_p) / (prev_p.abs() + eps))


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
