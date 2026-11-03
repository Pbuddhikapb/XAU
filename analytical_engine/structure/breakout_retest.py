"""
Authoritative Breakout and Retest Event Engine.
Strictly conforms to Section 5.E & 5.G of PROJECT_SPECIFICATION.md:
- Detects structural breakouts confirmed by candle close beyond confirmed swing levels (PivotRecord).
- Tracks subsequent retests of broken levels within a defined causal lookback window.
- Classifies retest outcomes:
    * SUCCESSFUL: Price retests the broken level and rejects it in the breakout direction.
    * FAILED: Price closes back inside the prior range, invalidating the breakout.
    * PENDING: Breakout confirmed, awaiting retest within the validity window.
    * EXPIRED: Validity window elapsed without a retest touch.
- Enforces strict no-lookahead: does not confirm a retest before the confirming candle closes.
- Pure analytical event detection — does NOT generate trade setups, entry/exit orders, or R:R scores.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from analytical_engine.models.outputs import BreakoutRetestRecord, PivotRecord
from analytical_engine.structure.pivots import PivotDetector


class BreakoutRetestDetector:
    """
    Detects structural breakouts and tracks retest states from confirmed pivots.
    """

    def __init__(
        self,
        swing_window: int = 3,
        max_retest_bars: int = 20,
        retest_tolerance_pct: float = 0.0015,
        timeframe: str = "1h",
    ):
        self.swing_window = swing_window
        self.max_retest_bars = max_retest_bars
        self.retest_tolerance_pct = retest_tolerance_pct
        self.timeframe = timeframe

    def detect_events(
        self,
        df: pd.DataFrame,
        pivots: list[PivotRecord] | None = None,
        timeframe: str | None = None,
        max_retest_bars: int | None = None,
        retest_tolerance_pct: float | None = None,
        time_col: str = "open_time",
        close_time_col: str = "close_time",
    ) -> list[BreakoutRetestRecord]:
        """
        Scan candles and evaluate breakouts and subsequent retests.
        """
        tf = timeframe or self.timeframe
        max_bars = max_retest_bars or self.max_retest_bars
        tol_pct = retest_tolerance_pct or self.retest_tolerance_pct

        if df.empty or len(df) < (2 * self.swing_window) + 3:
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

        events: list[BreakoutRetestRecord] = []
        processed_levels: set[tuple[int, str]] = set()
        n = len(df)

        for i in range(n):
            c_p = closes[i]
            b_time = dt_close_times[i]

            eligible_pivots = [
                p for p in pivots
                if p.confirmed_index < i and (p.index, p.pivot_type) not in processed_levels
            ]

            for p in eligible_pivots:
                key = (p.index, p.pivot_type)

                # Bullish Breakout
                if p.pivot_type == "HIGH" and c_p > p.pivot_price:
                    processed_levels.add(key)
                    level_p = p.pivot_price
                    tol = level_p * tol_pct

                    retest_found = False
                    end_search = min(n, i + max_bars + 1)

                    for j in range(i + 1, end_search):
                        low_j = lows[j]
                        close_j = closes[j]
                        retest_dt = dt_close_times[j]

                        if low_j <= level_p + tol:
                            if close_j >= level_p - tol:
                                events.append(
                                    BreakoutRetestRecord(
                                        direction="BULLISH",
                                        level_price=level_p,
                                        level_pivot_time=p.pivot_time,
                                        breakout_time=b_time,
                                        breakout_confirmed_time=b_time,
                                        breakout_price=float(c_p),
                                        retest_time=retest_dt,
                                        retest_confirmed_time=retest_dt,
                                        retest_price=float(low_j),
                                        status="SUCCESSFUL",
                                        timeframe=tf,
                                        details={"retest_bar_index": j, "breakout_bar_index": i},
                                    )
                                )
                            else:
                                events.append(
                                    BreakoutRetestRecord(
                                        direction="BULLISH",
                                        level_price=level_p,
                                        level_pivot_time=p.pivot_time,
                                        breakout_time=b_time,
                                        breakout_confirmed_time=b_time,
                                        breakout_price=float(c_p),
                                        retest_time=retest_dt,
                                        retest_confirmed_time=retest_dt,
                                        retest_price=float(close_j),
                                        status="FAILED",
                                        timeframe=tf,
                                        details={"failure_bar_index": j, "breakout_bar_index": i},
                                    )
                                )
                            retest_found = True
                            break

                    if not retest_found:
                        if (n - 1) >= (i + max_bars):
                            events.append(
                                BreakoutRetestRecord(
                                    direction="BULLISH",
                                    level_price=level_p,
                                    level_pivot_time=p.pivot_time,
                                    breakout_time=b_time,
                                    breakout_confirmed_time=b_time,
                                    breakout_price=float(c_p),
                                    retest_time=None,
                                    retest_confirmed_time=None,
                                    retest_price=None,
                                    status="EXPIRED",
                                    timeframe=tf,
                                    details={"bars_elapsed": n - 1 - i},
                                )
                            )
                        else:
                            events.append(
                                BreakoutRetestRecord(
                                    direction="BULLISH",
                                    level_price=level_p,
                                    level_pivot_time=p.pivot_time,
                                    breakout_time=b_time,
                                    breakout_confirmed_time=b_time,
                                    breakout_price=float(c_p),
                                    retest_time=None,
                                    retest_confirmed_time=None,
                                    retest_price=None,
                                    status="PENDING",
                                    timeframe=tf,
                                    details={"bars_elapsed": n - 1 - i},
                                )
                            )

                # Bearish Breakout
                elif p.pivot_type == "LOW" and c_p < p.pivot_price:
                    processed_levels.add(key)
                    level_p = p.pivot_price
                    tol = level_p * tol_pct

                    retest_found = False
                    end_search = min(n, i + max_bars + 1)

                    for j in range(i + 1, end_search):
                        high_j = highs[j]
                        close_j = closes[j]
                        retest_dt = dt_close_times[j]

                        if high_j >= level_p - tol:
                            if close_j <= level_p + tol:
                                events.append(
                                    BreakoutRetestRecord(
                                        direction="BEARISH",
                                        level_price=level_p,
                                        level_pivot_time=p.pivot_time,
                                        breakout_time=b_time,
                                        breakout_confirmed_time=b_time,
                                        breakout_price=float(c_p),
                                        retest_time=retest_dt,
                                        retest_confirmed_time=retest_dt,
                                        retest_price=float(high_j),
                                        status="SUCCESSFUL",
                                        timeframe=tf,
                                        details={"retest_bar_index": j, "breakout_bar_index": i},
                                    )
                                )
                            else:
                                events.append(
                                    BreakoutRetestRecord(
                                        direction="BEARISH",
                                        level_price=level_p,
                                        level_pivot_time=p.pivot_time,
                                        breakout_time=b_time,
                                        breakout_confirmed_time=b_time,
                                        breakout_price=float(c_p),
                                        retest_time=retest_dt,
                                        retest_confirmed_time=retest_dt,
                                        retest_price=float(close_j),
                                        status="FAILED",
                                        timeframe=tf,
                                        details={"failure_bar_index": j, "breakout_bar_index": i},
                                    )
                                )
                            retest_found = True
                            break

                    if not retest_found:
                        if (n - 1) >= (i + max_bars):
                            events.append(
                                BreakoutRetestRecord(
                                    direction="BEARISH",
                                    level_price=level_p,
                                    level_pivot_time=p.pivot_time,
                                    breakout_time=b_time,
                                    breakout_confirmed_time=b_time,
                                    breakout_price=float(c_p),
                                    retest_time=None,
                                    retest_confirmed_time=None,
                                    retest_price=None,
                                    status="EXPIRED",
                                    timeframe=tf,
                                    details={"bars_elapsed": n - 1 - i},
                                )
                            )
                        else:
                            events.append(
                                BreakoutRetestRecord(
                                    direction="BEARISH",
                                    level_price=level_p,
                                    level_pivot_time=p.pivot_time,
                                    breakout_time=b_time,
                                    breakout_confirmed_time=b_time,
                                    breakout_price=float(c_p),
                                    retest_time=None,
                                    retest_confirmed_time=None,
                                    retest_price=None,
                                    status="PENDING",
                                    timeframe=tf,
                                    details={"bars_elapsed": n - 1 - i},
                                )
                            )

        events.sort(key=lambda e: e.confirmed_time if e.confirmed_time else e.breakout_time)
        return events


def detect_breakout_retests(
    df: pd.DataFrame,
    pivots: list[PivotRecord] | None = None,
    timeframe: str = "1h",
    swing_window: int = 3,
    max_retest_bars: int = 20,
    retest_tolerance_pct: float = 0.0015,
    time_col: str = "open_time",
    close_time_col: str = "close_time",
) -> list[BreakoutRetestRecord]:
    """Convenience functional wrapper delegating to BreakoutRetestDetector."""
    detector = BreakoutRetestDetector(
        swing_window=swing_window,
        max_retest_bars=max_retest_bars,
        retest_tolerance_pct=retest_tolerance_pct,
        timeframe=timeframe,
    )
    return detector.detect_events(
        df=df,
        pivots=pivots,
        timeframe=timeframe,
        max_retest_bars=max_retest_bars,
        retest_tolerance_pct=retest_tolerance_pct,
        time_col=time_col,
        close_time_col=close_time_col,
    )
