"""
Swing Point Detection Module for Binance XAUUSDT.
Strictly conforms to Section 5.E of PROJECT_SPECIFICATION.md:
- Detects Swing Highs and Swing Lows with parameterized radius k (or asymmetrical shoulders L, R).
- Enforces strict no-lookahead confirmation: a swing at index i is confirmed only when candle (i + R) closes.
- Records original occurrence time and confirmed candle time as distinct fields.
- Delegates to or aligns directly with authoritative analytical_engine library.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from analytical_engine.structure.pivots import PivotDetector


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: datetime
    price: float
    swing_type: str  # "SWING_HIGH" | "SWING_LOW"
    confirmed_index: int
    confirmed_time: datetime

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["time"] = self.time.isoformat()
        d["confirmed_time"] = self.confirmed_time.isoformat()
        return d


def detect_swings(
    df: pd.DataFrame,
    window: int = 3,
    left_bars: int | None = None,
    right_bars: int | None = None,
    time_col: str = "open_time",
    close_time_col: str = "close_time",
    current_time: datetime | None = None,
) -> list[SwingPoint]:
    """
    Detect local swing highs and lows with confirmation radius.

    Parameters:
        df: Input DataFrame containing high, low, and timestamp columns.
        window: Symmetrical confirmation radius (used if left_bars/right_bars are None).
        left_bars: Confirmation bars required to the left (must be <= candidate peak).
        right_bars: Confirmation bars required to the right (must be < candidate peak).
        time_col: Column name for candle open timestamp.
        close_time_col: Column name for candle close timestamp.
        current_time: Optional evaluation timestamp; any pivot whose confirmation candle
                      closes after current_time will be withheld as unconfirmed.

    A peak at index i requires left_bars to be lower/equal and right_bars to be strictly lower.
    A trough at index i requires left_bars to be higher/equal and right_bars to be strictly higher.
    Confirmation occurs at bar index i + right_bars, and confirmed_time is strictly
    the close_time of candle (i + right_bars) to eliminate temporal lookahead bias.
    """
    l_bars = left_bars if left_bars is not None else window
    r_bars = right_bars if right_bars is not None else window

    if l_bars < 1 or r_bars < 1:
        raise ValueError(f"left_bars ({l_bars}) and right_bars ({r_bars}) must be >= 1.")

    n = len(df)
    if n < (l_bars + r_bars + 1):
        return []

    detector = PivotDetector(left_bars=l_bars, right_bars=r_bars)
    pivots = detector.find_pivots(
        df,
        current_time=current_time,
        time_col=time_col,
        close_time_col=close_time_col,
    )

    swings: list[SwingPoint] = []
    for p in pivots:
        swings.append(
            SwingPoint(
                index=p.index,
                time=p.pivot_time,
                price=p.pivot_price,
                swing_type=f"SWING_{p.pivot_type}",
                confirmed_index=p.confirmed_index,
                confirmed_time=p.confirmation_time,
            )
        )

    # Sort chronologically by original occurrence index
    swings.sort(key=lambda s: (s.index, s.swing_type))
    return swings
