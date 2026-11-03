"""
Momentum Divergence Detection Engine for Binance XAUUSDT.
Strictly conforms to Section 5.B of PROJECT_SPECIFICATION.md:
- Detects Regular Bullish, Regular Bearish, Hidden Bullish, and Hidden Bearish Divergences
- Operates on RSI 14 and MACD Histogram
- Enforces strict no-lookahead swing confirmation (lookback k-window confirmation)
- Produces explainable divergence event structures with price and indicator coordinate points
"""

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.structure.pivots import PivotDetector
from backend.analytics.momentum import calculate_macd, calculate_rsi



@dataclass
class DivergencePoint:
    time: str
    price: float
    indicator_val: float
    bar_index: int


@dataclass
class DivergenceResult:
    divergence_type: str  # REGULAR_BULLISH, REGULAR_BEARISH, HIDDEN_BULLISH, HIDDEN_BEARISH
    indicator_name: str  # RSI, MACD_HIST
    point_1: DivergencePoint
    point_2: DivergencePoint
    slope_price: float
    slope_indicator: float
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_swings(series: pd.Series, window: int = 4) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Identify local swing highs and swing lows without forward leakage.
    Delegates to PivotDetector for single authoritative shoulder mathematics.
    Returns: (swing_highs, swing_lows) where each element is (index_pos, value).
    """
    n = len(series)
    if n < (2 * window) + 1:
        return [], []

    vals = series.to_numpy(dtype=np.float64)
    dummy_df = pd.DataFrame({
        "open_time": pd.date_range("2026-01-01", periods=n, freq="1min"),
        "high": vals,
        "low": vals,
        "close": vals,
    })
    detector = PivotDetector(left_bars=window, right_bars=window)
    pivots = detector.find_pivots(dummy_df)
    highs = [(p.index, p.pivot_price) for p in pivots if p.pivot_type == "HIGH"]
    lows = [(p.index, p.pivot_price) for p in pivots if p.pivot_type == "LOW"]
    return highs, lows



def detect_divergences(
    df: pd.DataFrame,
    indicator_name: str = "RSI",
    swing_window: int = 3,
    max_lookback_bars: int = 40,
    time_col: str = "open_time",
) -> list[DivergenceResult]:
    """
    Detect momentum divergences between price and the specified indicator (RSI or MACD_HIST).

    Rules:
        - Regular Bullish: Price Lower Low (LL), Indicator Higher Low (HL)
        - Regular Bearish: Price Higher High (HH), Indicator Lower High (LH)
        - Hidden Bullish:  Price Higher Low (HL), Indicator Lower Low (LL)
        - Hidden Bearish:  Price Lower High (LH), Indicator Higher High (HH)
    """
    if len(df) < 35:
        return []

    close_s = df["close"]
    low_s = df["low"]
    high_s = df["high"]
    times = df[time_col].astype(str).tolist()

    ind_key = indicator_name.upper().strip()
    if ind_key == "RSI":
        ind_series = calculate_rsi(close_s, period=14)
    elif ind_key in ("MACD_HIST", "MACD"):
        macd_df = calculate_macd(close_s)
        ind_series = macd_df["hist"]
    else:
        raise ValueError(f"Unsupported indicator: {indicator_name}")

    _, p_low_swings = find_swings(low_s, window=swing_window)
    p_high_swings, _ = find_swings(high_s, window=swing_window)

    divergences: list[DivergenceResult] = []

    # 1. Evaluate Low Swings (Bullish Divergences)
    if len(p_low_swings) >= 2:
        for idx in range(len(p_low_swings) - 1, 0, -1):
            i2, p2 = p_low_swings[idx]
            i1, p1 = p_low_swings[idx - 1]

            if (i2 - i1) > max_lookback_bars or (i2 - i1) < (swing_window * 2):
                continue

            ind1 = float(ind_series.iloc[i1])
            ind2 = float(ind_series.iloc[i2])

            if np.isnan(ind1) or np.isnan(ind2):
                continue

            # Invalidation: subsequent price dropped below swing low p2
            is_invalidated = bool((low_s.iloc[i2 + 1 :] < p2).any()) if (i2 + 1 < len(low_s)) else False
            is_active = not is_invalidated

            # Regular Bullish: Lower Low in price, Higher Low in indicator
            if p2 < p1 and ind2 > ind1:
                pt1 = DivergencePoint(time=times[i1], price=p1, indicator_val=ind1, bar_index=i1)
                pt2 = DivergencePoint(time=times[i2], price=p2, indicator_val=ind2, bar_index=i2)
                divergences.append(
                    DivergenceResult(
                        divergence_type="REGULAR_BULLISH",
                        indicator_name=ind_key,
                        point_1=pt1,
                        point_2=pt2,
                        slope_price=(p2 - p1) / (i2 - i1),
                        slope_indicator=(ind2 - ind1) / (i2 - i1),
                        is_active=is_active,
                    )
                )

            # Hidden Bullish: Higher Low in price, Lower Low in indicator
            elif p2 > p1 and ind2 < ind1:
                pt1 = DivergencePoint(time=times[i1], price=p1, indicator_val=ind1, bar_index=i1)
                pt2 = DivergencePoint(time=times[i2], price=p2, indicator_val=ind2, bar_index=i2)
                divergences.append(
                    DivergenceResult(
                        divergence_type="HIDDEN_BULLISH",
                        indicator_name=ind_key,
                        point_1=pt1,
                        point_2=pt2,
                        slope_price=(p2 - p1) / (i2 - i1),
                        slope_indicator=(ind2 - ind1) / (i2 - i1),
                        is_active=is_active,
                    )
                )

    # 2. Evaluate High Swings (Bearish Divergences)
    if len(p_high_swings) >= 2:
        for idx in range(len(p_high_swings) - 1, 0, -1):
            i2, p2 = p_high_swings[idx]
            i1, p1 = p_high_swings[idx - 1]

            if (i2 - i1) > max_lookback_bars or (i2 - i1) < (swing_window * 2):
                continue

            ind1 = float(ind_series.iloc[i1])
            ind2 = float(ind_series.iloc[i2])

            if np.isnan(ind1) or np.isnan(ind2):
                continue

            # Invalidation: subsequent price rose above swing high p2
            is_invalidated = bool((high_s.iloc[i2 + 1 :] > p2).any()) if (i2 + 1 < len(high_s)) else False
            is_active = not is_invalidated

            # Regular Bearish: Higher High in price, Lower High in indicator
            if p2 > p1 and ind2 < ind1:
                pt1 = DivergencePoint(time=times[i1], price=p1, indicator_val=ind1, bar_index=i1)
                pt2 = DivergencePoint(time=times[i2], price=p2, indicator_val=ind2, bar_index=i2)
                divergences.append(
                    DivergenceResult(
                        divergence_type="REGULAR_BEARISH",
                        indicator_name=ind_key,
                        point_1=pt1,
                        point_2=pt2,
                        slope_price=(p2 - p1) / (i2 - i1),
                        slope_indicator=(ind2 - ind1) / (i2 - i1),
                        is_active=is_active,
                    )
                )

            # Hidden Bearish: Lower High in price, Higher High in indicator
            elif p2 < p1 and ind2 > ind1:
                pt1 = DivergencePoint(time=times[i1], price=p1, indicator_val=ind1, bar_index=i1)
                pt2 = DivergencePoint(time=times[i2], price=p2, indicator_val=ind2, bar_index=i2)
                divergences.append(
                    DivergenceResult(
                        divergence_type="HIDDEN_BEARISH",
                        indicator_name=ind_key,
                        point_1=pt1,
                        point_2=pt2,
                        slope_price=(p2 - p1) / (i2 - i1),
                        slope_indicator=(ind2 - ind1) / (i2 - i1),
                        is_active=is_active,
                    )
                )

    return divergences
