"""
Liquidity Sweep Detection Module for Binance XAUUSDT.
Strictly conforms to Section 5.F of PROJECT_SPECIFICATION.md and Phase 3 Remediation:
- Detects stop hunts / false breakouts where wicks pierce beyond active swing levels
  but candles close back within the prior range.
- Level-Validity Policy:
  1. Only confirmed swing points are eligible.
  2. Levels broken by candle close are immediately invalidated and cannot be swept.
  3. Once a level is swept, it is marked consumed to prevent duplicate repeated sweeps.
  4. Configurable recency/expiry window (default max_age_bars = 50).
- Distinguishes price-action wick reversals from executed volume claims.
- Timestamped observations preserving both level occurrence time and candle close time.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from analytical_engine.structure.liquidity_sweeps import (
    detect_liquidity_sweeps as ae_detect_liquidity_sweeps,
)


@dataclass(frozen=True)
class LiquiditySweepEvent:
    sweep_type: str  # SWEEP_HIGH (bearish reversal bias) | SWEEP_LOW (bullish reversal bias)
    swept_level: float
    penetration_price: float
    close_price: float
    sweep_distance: float
    event_time: datetime  # Original swing level occurrence time
    confirmed_candle_time: datetime  # Exact close time of the candle executing the sweep
    timeframe: str
    is_wick_reversal: bool = True  # Distinguishes wick pattern from executed book flow

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_time"] = self.event_time.isoformat()
        d["confirmed_candle_time"] = self.confirmed_candle_time.isoformat()
        return d


def detect_liquidity_sweeps(
    df: pd.DataFrame,
    timeframe: str = "1h",
    swing_window: int = 3,
    max_age_bars: int = 50,
    time_col: str = "open_time",
    close_time_col: str = "close_time",
) -> list[LiquiditySweepEvent]:
    """
    Detect liquidity sweeps across candles with strict obsolete-level filtering.

    Parameters:
        df: Input DataFrame containing open, high, low, close, and timestamp columns.
        timeframe: Bar interval label.
        swing_window: Left/right confirmation shoulder radius.
        max_age_bars: Maximum age in bars before an untouched swing level expires.
        time_col: Open timestamp column.
        close_time_col: Close timestamp column.
    """
    records = ae_detect_liquidity_sweeps(
        df=df,
        timeframe=timeframe,
        swing_window=swing_window,
        max_age_bars=max_age_bars,
        time_col=time_col,
        close_time_col=close_time_col,
    )

    events: list[LiquiditySweepEvent] = []
    for r in records:
        events.append(
            LiquiditySweepEvent(
                sweep_type=r.sweep_type,
                swept_level=r.swept_level,
                penetration_price=r.penetration_price,
                close_price=r.close_price,
                sweep_distance=r.sweep_distance,
                event_time=r.event_time,
                confirmed_candle_time=r.confirmed_candle_time,
                timeframe=r.timeframe,
                is_wick_reversal=r.is_wick_reversal,
            )
        )
    return events
