"""
Continuity and gap detection for financial time-series.
Identifies gaps and missing intervals without fabricating or interpolating data.
"""

import pandas as pd

from analytical_engine.data.timeframe import get_timeframe_seconds
from analytical_engine.models.inputs import DiscontinuityEvent, DiscontinuityReport


class ContinuityDetector:
    """Audits temporal sequencing and identifies gaps between consecutive candles."""

    def __init__(self, timeframe: str = "1m"):
        self.timeframe = timeframe
        self.interval_seconds = get_timeframe_seconds(timeframe)

    def detect_discontinuities(self, df: pd.DataFrame) -> DiscontinuityReport:
        """
        Scan a validated, sorted DataFrame for timestamp gaps.
        Returns DiscontinuityReport detailing each missing span.
        """
        if df.empty or len(df) < 2:
            return DiscontinuityReport(total_discontinuities=0, total_missing_candles=0, events=[])

        events: list[DiscontinuityEvent] = []
        total_missing = 0

        # Calculate time difference between consecutive open_time rows
        open_times = pd.to_datetime(df["open_time"])
        diffs = (open_times.diff().dt.total_seconds()).fillna(self.interval_seconds)

        # A gap occurs whenever the step between rows is strictly greater than expected interval
        # Allow 1-second tolerance for floating drift if any, though integer seconds expected
        gap_mask = diffs > (self.interval_seconds + 1.0)
        gap_indices = df.index[gap_mask].tolist()

        for idx in gap_indices:
            prev_ts = open_times.loc[idx - 1]
            curr_ts = open_times.loc[idx]
            duration_sec = (curr_ts - prev_ts).total_seconds()
            missing_count = int(round(duration_sec / self.interval_seconds)) - 1

            prev_dt = prev_ts.to_pydatetime() if hasattr(prev_ts, "to_pydatetime") else prev_ts
            curr_dt = curr_ts.to_pydatetime() if hasattr(curr_ts, "to_pydatetime") else curr_ts

            if missing_count > 0:
                events.append(
                    DiscontinuityEvent(
                        start_time=prev_dt,
                        end_time=curr_dt,
                        expected_interval_seconds=self.interval_seconds,
                        missing_intervals=missing_count,
                        duration_seconds=duration_sec,
                    )
                )
                total_missing += missing_count

        return DiscontinuityReport(
            total_discontinuities=len(events),
            total_missing_candles=total_missing,
            events=events,
        )

    def get_gap_boundary_indices(self, df: pd.DataFrame) -> set[int]:
        """
        Return indices of rows immediately following a detected discontinuity.
        Rolling indicators can use this to trigger warm-up resets.
        """
        if df.empty or len(df) < 2:
            return set()

        open_times = pd.to_datetime(df["open_time"])
        diffs = (open_times.diff().dt.total_seconds()).fillna(self.interval_seconds)
        gap_mask = diffs > (self.interval_seconds + 1.0)
        return set(df.index[gap_mask].tolist())
