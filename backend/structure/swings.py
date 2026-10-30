"""
Swing Point Detection Module for Binance XAUUSDT.
Strictly conforms to Section 5.E of PROJECT_SPECIFICATION.md:
- Detects Swing Highs and Swing Lows with parameterized radius k.
- Enforces strict no-lookahead confirmation: a swing at index i is confirmed only at index i + k.
- Records original occurrence time and confirmed candle time.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd


@dataclass
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
    time_col: str = "open_time",
) -> list[SwingPoint]:
    """
    Detect local swing highs and lows with confirmation radius `window`.
    A peak at index i requires `window` bars on both sides to be lower.
    A trough at index i requires `window` bars on both sides to be higher.
    Confirmation occurs at bar index i + window.
    """
    n = len(df)
    if n < (2 * window) + 1:
        return []

    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    times = df[time_col].tolist()

    # Normalize times to UTC datetime
    dt_times: list[datetime] = []
    for t in times:
        if isinstance(t, datetime):
            dt_times.append(t if t.tzinfo else t.replace(tzinfo=UTC))
        elif isinstance(t, str):
            dt_times.append(datetime.fromisoformat(t).replace(tzinfo=UTC))
        elif hasattr(t, "to_pydatetime"):
            py_dt = t.to_pydatetime()
            dt_times.append(py_dt if py_dt.tzinfo else py_dt.replace(tzinfo=UTC))
        else:
            dt_times.append(datetime.now(UTC))

    swings: list[SwingPoint] = []

    for i in range(window, n - window):
        h_val = highs[i]
        l_val = lows[i]

        if np.isnan(h_val) or np.isnan(l_val):
            continue

        is_swing_high = True
        is_swing_low = True

        for k in range(1, window + 1):
            if highs[i - k] >= h_val or highs[i + k] >= h_val:
                is_swing_high = False
            if lows[i - k] <= l_val or lows[i + k] <= l_val:
                is_swing_low = False

        conf_idx = i + window
        conf_time = dt_times[conf_idx]

        if is_swing_high:
            swings.append(
                SwingPoint(
                    index=i,
                    time=dt_times[i],
                    price=float(h_val),
                    swing_type="SWING_HIGH",
                    confirmed_index=conf_idx,
                    confirmed_time=conf_time,
                )
            )

        if is_swing_low:
            swings.append(
                SwingPoint(
                    index=i,
                    time=dt_times[i],
                    price=float(l_val),
                    swing_type="SWING_LOW",
                    confirmed_index=conf_idx,
                    confirmed_time=conf_time,
                )
            )

    # Sort chronologically by original occurrence index
    swings.sort(key=lambda s: (s.index, s.swing_type))
    return swings
