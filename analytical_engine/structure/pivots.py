"""
Pivot detection engine: Confirmed Swing Highs and Swing Lows.
Enforces separation between pivot occurrence timestamp and confirmation timestamp.
"""

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from analytical_engine.models.outputs import PivotRecord


class PivotDetector:
    """
    Detects confirmed swing highs and swing lows using an (L, R) shoulder algorithm.

    A candle at index i is a Pivot High if:
        High[i] > High[i - k] for all k in 1..left_bars
        AND High[i] >= High[i + k] for all k in 1..right_bars

    A candle at index i is a Pivot Low if:
        Low[i] < Low[i - k] for all k in 1..left_bars
        AND Low[i] <= Low[i + k] for all k in 1..right_bars

    Temporal Guarantee:
        The pivot occurs at index i, but is STRICTLY UNCONFIRMED until index i + right_bars closes.
        Therefore:
            confirmation_time = close_time[i + right_bars]
            confirmation_lag_bars = right_bars
    """

    def __init__(self, left_bars: int = 2, right_bars: int = 2):
        if left_bars < 1 or right_bars < 1:
            raise ValueError(f"left_bars ({left_bars}) and right_bars ({right_bars}) must be >= 1.")
        self.left_bars = left_bars
        self.right_bars = right_bars

    def find_pivots(
        self,
        df: pd.DataFrame,
        current_time: datetime | None = None,
        time_col: str = "open_time",
        close_time_col: str = "close_time",
    ) -> list[PivotRecord]:
        """
        Scan a validated DataFrame and extract all confirmed pivots.
        Optionally filter by current_time point-in-time boundary.
        """
        n = len(df)
        required_span = self.left_bars + self.right_bars + 1
        if n < required_span:
            return []

        highs = df["high"].values.astype(np.float64)
        lows = df["low"].values.astype(np.float64)
        open_times = pd.to_datetime(df[time_col])

        if close_time_col in df.columns:
            close_times = pd.to_datetime(df[close_time_col])
        else:
            # Fallback for close time: next open time or open + interval
            time_diff = open_times.diff().median()
            close_times = open_times + time_diff

        timeframe = df.attrs.get("timeframe", "1m")
        pivots: list[PivotRecord] = []

        # Convert current_time to UTC if present
        if current_time is not None:
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=UTC)

        # We can test candidate pivots from index left_bars up to n - right_bars - 1
        for i in range(self.left_bars, n - self.right_bars):
            curr_h = highs[i]
            curr_l = lows[i]

            if np.isnan(curr_h) or np.isnan(curr_l):
                continue

            conf_idx = i + self.right_bars
            conf_ts = close_times.iloc[conf_idx].to_pydatetime()
            if conf_ts.tzinfo is None:
                conf_ts = conf_ts.replace(tzinfo=UTC)

            # Strict point-in-time gating
            if current_time is not None and conf_ts > current_time:
                continue

            # 1. Test for Swing High (non-strict left, strict right)
            is_high = True
            for k in range(1, self.left_bars + 1):
                if curr_h < highs[i - k]:
                    is_high = False
                    break
            if is_high:
                for k in range(1, self.right_bars + 1):
                    if curr_h <= highs[i + k]:
                        is_high = False
                        break

            if is_high:
                pivot_ts = open_times.iloc[i].to_pydatetime()
                if pivot_ts.tzinfo is None:
                    pivot_ts = pivot_ts.replace(tzinfo=UTC)

                pivots.append(
                    PivotRecord(
                        pivot_time=pivot_ts,
                        pivot_price=float(curr_h),
                        pivot_type="HIGH",
                        confirmation_time=conf_ts,
                        confirmation_lag_bars=self.right_bars,
                        left_bars=self.left_bars,
                        right_bars=self.right_bars,
                        timeframe=timeframe,
                        index=i,
                        confirmed_index=conf_idx,
                    )
                )

            # 2. Test for Swing Low (non-strict left, strict right)
            is_low = True
            for k in range(1, self.left_bars + 1):
                if curr_l > lows[i - k]:
                    is_low = False
                    break
            if is_low:
                for k in range(1, self.right_bars + 1):
                    if curr_l >= lows[i + k]:
                        is_low = False
                        break

            if is_low:
                pivot_ts = open_times.iloc[i].to_pydatetime()
                if pivot_ts.tzinfo is None:
                    pivot_ts = pivot_ts.replace(tzinfo=UTC)

                pivots.append(
                    PivotRecord(
                        pivot_time=pivot_ts,
                        pivot_price=float(curr_l),
                        pivot_type="LOW",
                        confirmation_time=conf_ts,
                        confirmation_lag_bars=self.right_bars,
                        left_bars=self.left_bars,
                        right_bars=self.right_bars,
                        timeframe=timeframe,
                        index=i,
                        confirmed_index=conf_idx,
                    )
                )


        # Sort chronologically by confirmation_time, then pivot_time
        pivots.sort(key=lambda p: (p.confirmation_time, p.pivot_time))
        return pivots
