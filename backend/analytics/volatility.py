"""
Volatility Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.C of PROJECT_SPECIFICATION.md:
- ATR 14 (Wilder's exponential smoothing)
- Bollinger Bands (20, 2.0: Upper, Middle, Lower, Bandwidth, %B)
- Volatility Expansion & Contraction (Squeeze Detection)
- Historical Volatility Percentile
"""

from typing import Any

import numpy as np
import pandas as pd


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Wilder's Average True Range (ATR).

    Formula:
        TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
        ATR_t = WilderSmooth(TR, period)
    """
    if len(close) < period:
        return pd.Series(np.nan, index=close.index, dtype=np.float64)

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    atr.iloc[:period] = np.nan
    return atr


def calculate_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """
    Calculate Bollinger Bands, Bandwidth, and %B.

    Formulas:
        Middle = SMA(series, period)
        Upper = Middle + num_std * StdDev(series, period)
        Lower = Middle - num_std * StdDev(series, period)
        Bandwidth = (Upper - Lower) / Middle
        %B = (Close - Lower) / (Upper - Lower + epsilon)
    """
    if len(series) < period:
        empty = pd.Series(np.nan, index=series.index, dtype=np.float64)
        return pd.DataFrame({"upper": empty, "middle": empty, "lower": empty, "bandwidth": empty, "pct_b": empty})

    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std(ddof=0)
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    eps = 1e-9
    bandwidth = (upper - lower) / (middle.abs() + eps)
    pct_b = (series - lower) / (upper - lower + eps)

    return pd.DataFrame(
        {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "bandwidth": bandwidth,
            "pct_b": pct_b,
        },
        index=series.index,
    )


def calculate_historical_volatility_percentile(atr_series: pd.Series, lookback: int = 100) -> pd.Series:
    """
    Calculate rolling historical percentile rank (0.0 to 100.0) of current ATR
    relative to past `lookback` periods.

    Formula:
        Percentile_t = 100 * count(ATR_i <= ATR_t) / window_size
    """
    if len(atr_series) < 2:
        return pd.Series(50.0, index=atr_series.index, dtype=np.float64)

    def percentile_rank(window: np.ndarray) -> float:
        valid = window[~np.isnan(window)]
        if len(valid) == 0:
            return 50.0
        current = valid[-1]
        rank = (valid <= current).sum()
        return float(rank / len(valid) * 100.0)

    return (
        atr_series.rolling(window=lookback, min_periods=min(10, len(atr_series)))
        .apply(percentile_rank, raw=True)
        .fillna(50.0)
    )


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
    bw_ma = bb_df["bandwidth"].rolling(20).mean().loc[last_idx]
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
