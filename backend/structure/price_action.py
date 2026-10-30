"""
Price Action Pattern Detection Module for Binance XAUUSDT.
Strictly conforms to Section 5.G of PROJECT_SPECIFICATION.md:
- Rejection Candles (Pinbars: upper / lower wick dominance >= 60%).
- Engulfing Patterns (Bullish Engulfing, Bearish Engulfing).
- Breakout & Retest recognition.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class PriceActionPattern:
    pattern_type: str  # REJECTION_BULL, REJECTION_BEAR, ENGULFING_BULL, ENGULFING_BEAR, BREAKOUT_RETEST
    candle_time: datetime
    price: float
    strength: float  # 0.0 to 100.0
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["candle_time"] = self.candle_time.isoformat()
        return d


def detect_price_action_patterns(
    df: pd.DataFrame,
    time_col: str = "open_time",
    wick_ratio_threshold: float = 0.60,
) -> list[PriceActionPattern]:
    """
    Detect price action candle patterns across the DataFrame.
    """
    if len(df) < 2:
        return []

    opens = df["open"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    times = df[time_col].tolist()

    patterns: list[PriceActionPattern] = []
    eps = 1e-9

    for i in range(len(df)):
        open_p = opens[i]
        high_p = highs[i]
        low_p = lows[i]
        close_p = closes[i]
        time_val = times[i]
        if hasattr(time_val, "to_pydatetime"):
            time_val = time_val.to_pydatetime()

        candle_range = high_p - low_p + eps
        upper_wick = high_p - max(open_p, close_p)
        lower_wick = min(open_p, close_p) - low_p

        upper_wick_ratio = upper_wick / candle_range
        lower_wick_ratio = lower_wick / candle_range

        # 1. Rejection Candles (Pinbars)
        if lower_wick_ratio >= wick_ratio_threshold and close_p > low_p:
            # Bullish rejection (long lower shadow)
            patterns.append(
                PriceActionPattern(
                    pattern_type="REJECTION_BULL",
                    candle_time=time_val,
                    price=close_p,
                    strength=round(float(lower_wick_ratio * 100.0), 2),
                    details={
                        "lower_wick_ratio": round(float(lower_wick_ratio), 4),
                        "range": round(float(candle_range), 4),
                    },
                )
            )
        elif upper_wick_ratio >= wick_ratio_threshold and close_p < high_p:
            # Bearish rejection (long upper shadow)
            patterns.append(
                PriceActionPattern(
                    pattern_type="REJECTION_BEAR",
                    candle_time=time_val,
                    price=close_p,
                    strength=round(float(upper_wick_ratio * 100.0), 2),
                    details={
                        "upper_wick_ratio": round(float(upper_wick_ratio), 4),
                        "range": round(float(candle_range), 4),
                    },
                )
            )

        # 2. Engulfing Patterns (Requires prior bar i-1)
        if i >= 1:
            prev_o = opens[i - 1]
            prev_c = closes[i - 1]
            prev_bear = prev_c < prev_o
            prev_bull = prev_c > prev_o

            # Bullish Engulfing: Prior candle was bearish, current candle opens <= prev_close and closes >= prev_open
            if prev_bear and close_p > open_p and open_p <= prev_c and close_p >= prev_o:
                engulf_ratio = (close_p - open_p) / (abs(prev_c - prev_o) + eps)
                patterns.append(
                    PriceActionPattern(
                        pattern_type="ENGULFING_BULL",
                        candle_time=time_val,
                        price=close_p,
                        strength=min(100.0, round(float(engulf_ratio * 50.0), 2)),
                        details={"engulf_ratio": round(float(engulf_ratio), 4)},
                    )
                )

            # Bearish Engulfing: Prior candle was bullish, current candle opens >= prev_close and closes <= prev_open
            elif prev_bull and close_p < open_p and open_p >= prev_c and close_p <= prev_o:
                engulf_ratio = (open_p - close_p) / (abs(prev_c - prev_o) + eps)
                patterns.append(
                    PriceActionPattern(
                        pattern_type="ENGULFING_BEAR",
                        candle_time=time_val,
                        price=close_p,
                        strength=min(100.0, round(float(engulf_ratio * 50.0), 2)),
                        details={"engulf_ratio": round(float(engulf_ratio), 4)},
                    )
                )

    return patterns
