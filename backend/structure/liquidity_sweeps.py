"""
Liquidity Sweep Detection Module for Binance XAUUSDT.
Strictly conforms to Section 5.F of PROJECT_SPECIFICATION.md:
- Detects stop hunts / false breakouts where wicks pierce beyond swing levels
  but candles close back within the prior range.
- Timestamped observations with exact penetration depth and closure levels.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backend.structure.swings import detect_swings


@dataclass
class LiquiditySweepEvent:
    sweep_type: str  # SWEEP_HIGH (bearish reversal bias) | SWEEP_LOW (bullish reversal bias)
    swept_level: float
    penetration_price: float
    close_price: float
    sweep_distance: float
    event_time: datetime
    confirmed_candle_time: datetime
    timeframe: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_time"] = self.event_time.isoformat()
        d["confirmed_candle_time"] = self.confirmed_candle_time.isoformat()
        return d


def detect_liquidity_sweeps(
    df: pd.DataFrame,
    timeframe: str = "1h",
    swing_window: int = 3,
    time_col: str = "open_time",
) -> list[LiquiditySweepEvent]:
    """
    Detect liquidity sweeps across candles where:
    - High_t > SwingHigh but Close_t <= SwingHigh (SWEEP_HIGH)
    - Low_t < SwingLow but Close_t >= SwingLow (SWEEP_LOW)
    """
    if len(df) < (2 * swing_window) + 2:
        return []

    swings = detect_swings(df, window=swing_window, time_col=time_col)
    if not swings:
        return []

    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    times = df[time_col].tolist()

    sweeps: list[LiquiditySweepEvent] = []

    for idx in range(len(df)):
        h_p = highs[idx]
        l_p = lows[idx]
        c_p = closes[idx]
        c_time = times[idx]
        if hasattr(c_time, "to_pydatetime"):
            c_time = c_time.to_pydatetime()

        # Swings confirmed BEFORE this bar
        confirmed_swings = [s for s in swings if s.confirmed_index < idx]
        if not confirmed_swings:
            continue

        # Look at recent confirmed swing highs
        for s in confirmed_swings:
            if s.swing_type == "SWING_HIGH":
                # High pierced above, but close remained below or equal to swing level
                if h_p > s.price and c_p <= s.price:
                    sweeps.append(
                        LiquiditySweepEvent(
                            sweep_type="SWEEP_HIGH",
                            swept_level=s.price,
                            penetration_price=float(h_p),
                            close_price=float(c_p),
                            sweep_distance=round(float(h_p - s.price), 4),
                            event_time=s.time,
                            confirmed_candle_time=c_time,
                            timeframe=timeframe,
                        )
                    )

            elif s.swing_type == "SWING_LOW":
                # Low pierced below, but close remained above or equal to swing level
                if l_p < s.price and c_p >= s.price:
                    sweeps.append(
                        LiquiditySweepEvent(
                            sweep_type="SWEEP_LOW",
                            swept_level=s.price,
                            penetration_price=float(l_p),
                            close_price=float(c_p),
                            sweep_distance=round(float(s.price - l_p), 4),
                            event_time=s.time,
                            confirmed_candle_time=c_time,
                            timeframe=timeframe,
                        )
                    )

    # Sort chronologically by confirmed_candle_time
    sweeps.sort(key=lambda s: s.confirmed_candle_time)
    return sweeps
