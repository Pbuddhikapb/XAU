"""
Authoritative Liquidity Sweep Detection Engine.
Strictly conforms to Section 5.F of PROJECT_SPECIFICATION.md:
- Detects stop hunts / false breakouts where wicks pierce beyond confirmed swing levels
  but candles close back within the prior range.
- Enforces Level-Validity Policy:
  1. Only confirmed swing points (PivotRecord) are eligible.
  2. Levels broken by candle close are immediately invalidated.
  3. Swept levels are marked consumed to prevent duplicate sweeps.
  4. Unswept levels expire after max_age_bars.
- Pure analytical event detection — zero trade setup or execution recommendations.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.models.outputs import LiquiditySweepRecord, PivotRecord
from analytical_engine.structure.pivots import PivotDetector


class LiquiditySweepDetector:
    """
    Detects confirmed liquidity sweeps against active swing levels.
    """

    def __init__(
        self,
        swing_window: int = 3,
        max_age_bars: int = 50,
        timeframe: str = "1h",
    ):
        self.swing_window = swing_window
        self.max_age_bars = max_age_bars
        self.timeframe = timeframe

    def detect_sweeps(
        self,
        df: pd.DataFrame,
        pivots: list[PivotRecord] | None = None,
        timeframe: str | None = None,
        max_age_bars: int | None = None,
        time_col: str = "open_time",
        close_time_col: str = "close_time",
    ) -> list[LiquiditySweepRecord]:
        """
        Scan candles and evaluate active swing levels for confirmed liquidity sweeps.
        """
        tf = timeframe or self.timeframe
        age_limit = max_age_bars or self.max_age_bars

        if df.empty or len(df) < (2 * self.swing_window) + 2:
            return []

        if pivots is None:
            detector = PivotDetector(left_bars=self.swing_window, right_bars=self.swing_window)
            pivots = detector.find_pivots(df, time_col=time_col, close_time_col=close_time_col)

        if not pivots:
            return []

        highs = df["high"].astype(float).to_numpy()
        lows = df["low"].astype(float).to_numpy()
        closes = df["close"].astype(float).to_numpy()
        open_times = df[time_col].tolist()

        if close_time_col in df.columns:
            close_times = df[close_time_col].tolist()
        else:
            diffs = [
                open_times[k] - open_times[k - 1]
                for k in range(1, len(open_times))
                if hasattr(open_times[k], "__sub__")
            ]
            bar_delta = sorted(diffs)[len(diffs) // 2] if diffs else timedelta(hours=1)
            close_times = [t + bar_delta for t in open_times]

        def _to_utc(t: Any) -> datetime:
            if isinstance(t, datetime):
                return t if t.tzinfo else t.replace(tzinfo=UTC)
            elif isinstance(t, str):
                return datetime.fromisoformat(t).replace(tzinfo=UTC)
            elif hasattr(t, "to_pydatetime"):
                py_dt = t.to_pydatetime()
                return py_dt if py_dt.tzinfo else py_dt.replace(tzinfo=UTC)
            return datetime.now(UTC)

        dt_close_times = [_to_utc(t) for t in close_times]

        invalidated_levels: set[tuple[int, str]] = set()
        consumed_swept_levels: set[tuple[int, str]] = set()
        sweeps: list[LiquiditySweepRecord] = []

        # Process chronologically candle-by-candle
        for idx in range(len(df)):
            h_p = highs[idx]
            l_p = lows[idx]
            c_p = closes[idx]
            c_close_time = dt_close_times[idx]

            # 1. Update invalidation for active swings based on current candle close
            for p in pivots:
                if p.confirmed_index < idx:
                    key = (p.index, p.pivot_type)
                    if key in invalidated_levels or key in consumed_swept_levels:
                        continue

                    # Check expiration
                    if (idx - p.index) > age_limit:
                        invalidated_levels.add(key)
                        continue

                    # Check structural breakout invalidation by close
                    if p.pivot_type == "HIGH" and c_p > p.pivot_price:
                        invalidated_levels.add(key)
                    elif p.pivot_type == "LOW" and c_p < p.pivot_price:
                        invalidated_levels.add(key)

            # 2. Check for sweeps against active, confirmed, uninvalidated swings
            active_pivots = [
                p for p in pivots
                if p.confirmed_index < idx
                and (p.index, p.pivot_type) not in invalidated_levels
                and (p.index, p.pivot_type) not in consumed_swept_levels
            ]

            active_pivots.sort(key=lambda p: p.index, reverse=True)

            for p in active_pivots:
                key = (p.index, p.pivot_type)

                if p.pivot_type == "HIGH":
                    if h_p > p.pivot_price and c_p <= p.pivot_price:
                        sweeps.append(
                            LiquiditySweepRecord(
                                sweep_type="SWEEP_HIGH",
                                swept_level=p.pivot_price,
                                penetration_price=float(h_p),
                                close_price=float(c_p),
                                sweep_distance=round(float(h_p - p.pivot_price), 4),
                                event_time=p.pivot_time,
                                confirmed_candle_time=c_close_time,
                                timeframe=tf,
                                is_wick_reversal=True,
                                swept_pivot_time=p.pivot_time,
                            )
                        )
                        consumed_swept_levels.add(key)

                elif p.pivot_type == "LOW":
                    if l_p < p.pivot_price and c_p >= p.pivot_price:
                        sweeps.append(
                            LiquiditySweepRecord(
                                sweep_type="SWEEP_LOW",
                                swept_level=p.pivot_price,
                                penetration_price=float(l_p),
                                close_price=float(c_p),
                                sweep_distance=round(float(p.pivot_price - l_p), 4),
                                event_time=p.pivot_time,
                                confirmed_candle_time=c_close_time,
                                timeframe=tf,
                                is_wick_reversal=True,
                                swept_pivot_time=p.pivot_time,
                            )
                        )
                        consumed_swept_levels.add(key)

        sweeps.sort(key=lambda s: s.confirmed_candle_time)
        return sweeps


def detect_liquidity_sweeps(
    df: pd.DataFrame,
    pivots: list[PivotRecord] | None = None,
    timeframe: str = "1h",
    swing_window: int = 3,
    max_age_bars: int = 50,
    time_col: str = "open_time",
    close_time_col: str = "close_time",
) -> list[LiquiditySweepRecord]:
    """Convenience functional wrapper delegating to LiquiditySweepDetector."""
    detector = LiquiditySweepDetector(swing_window=swing_window, max_age_bars=max_age_bars, timeframe=timeframe)
    return detector.detect_sweeps(
        df=df,
        pivots=pivots,
        timeframe=timeframe,
        max_age_bars=max_age_bars,
        time_col=time_col,
        close_time_col=close_time_col,
    )
