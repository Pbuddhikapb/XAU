"""
Market structure engine: Classifies structural points (HH, HL, LH, LL) and
detects structural breaks (BOS and CHoCH) from confirmed pivots.
"""

import numpy as np
import pandas as pd

from analytical_engine.models.outputs import PivotRecord, StructureEventRecord


class MarketStructureClassifier:
    """
    Evaluates market structure sequences and breaks using confirmed pivots.

    Definitions:
        - Structural Level: A confirmed swing point (PivotRecord).
        - Break: When a confirmed candle CLOSE exceeds an active structural level.
        - Higher High (HH): Confirmed swing high price > previous confirmed swing high price.
        - Lower High (LH): Confirmed swing high price < previous confirmed swing high price.
        - Higher Low (HL): Confirmed swing low price > previous confirmed swing low price.
        - Lower Low (LL): Confirmed swing low price < previous confirmed swing low price.
        - Break of Structure (BOS):
            * Bullish BOS: Price closes above the active swing high during an uptrend (continuation).
            * Bearish BOS: Price closes below the active swing low during a downtrend (continuation).
        - Change of Character (CHoCH):
            * Bullish CHoCH: Price closes above the most recent lower high in a downtrend (reversal).
            * Bearish CHoCH: Price closes below the most recent higher low in an uptrend (reversal).
    """

    def __init__(self, break_by_close: bool = True):
        self.break_by_close = break_by_close

    def classify_swings(self, pivots: list[PivotRecord]) -> list[StructureEventRecord]:
        """
        Classify confirmed pivots into HH, HL, LH, LL events.
        Events become available at the pivot's confirmation_time.
        """
        events: list[StructureEventRecord] = []
        last_high: PivotRecord | None = None
        last_low: PivotRecord | None = None

        for p in pivots:
            if p.pivot_type == "HIGH":
                if last_high is not None:
                    event_type = "HH" if p.pivot_price > last_high.pivot_price else "LH"
                    events.append(
                        StructureEventRecord(
                            event_time=p.pivot_time,
                            event_type=event_type,
                            price=p.pivot_price,
                            broken_level=last_high.pivot_price,
                            broken_pivot_time=last_high.pivot_time,
                            confirmed_candle_time=p.confirmation_time,
                            timeframe=p.timeframe,
                            metadata={"previous_pivot_price": last_high.pivot_price},
                        )
                    )
                last_high = p
            elif p.pivot_type == "LOW":
                if last_low is not None:
                    event_type = "HL" if p.pivot_price > last_low.pivot_price else "LL"
                    events.append(
                        StructureEventRecord(
                            event_time=p.pivot_time,
                            event_type=event_type,
                            price=p.pivot_price,
                            broken_level=last_low.pivot_price,
                            broken_pivot_time=last_low.pivot_time,
                            confirmed_candle_time=p.confirmation_time,
                            timeframe=p.timeframe,
                            metadata={"previous_pivot_price": last_low.pivot_price},
                        )
                    )
                last_low = p

        return events

    def detect_structural_breaks(
        self,
        df: pd.DataFrame,
        pivots: list[PivotRecord],
    ) -> list[StructureEventRecord]:
        """
        Detect BOS and CHoCH breaks chronologically across candles.

        Strict Causal Rule:
            A break can only occur at candle i if the swing level was already CONFIRMED
            at or before candle i's open_time (confirmation_time <= candle_i.open_time).
            The break event itself is confirmed when candle i closes.
        """
        if df.empty or len(pivots) < 2:
            return []

        timeframe = df.attrs.get("timeframe", "1m")
        open_times = pd.to_datetime(df["open_time"])
        if "close_time" in df.columns:
            close_times = pd.to_datetime(df["close_time"])
        else:
            close_times = open_times + pd.Timedelta(seconds=60)
        closes = df["close"].values.astype(np.float64)
        highs = df["high"].values.astype(np.float64)
        lows = df["low"].values.astype(np.float64)

        breaks: list[StructureEventRecord] = []

        # Track active structural state
        # Trend: 1 = Bullish, -1 = Bearish, 0 = Undefined
        current_trend = 0
        active_high: PivotRecord | None = None
        active_low: PivotRecord | None = None
        broken_levels: set = set()

        # Iterate chronologically through candles
        p_idx = 0
        n_pivots = len(pivots)
        n_candles = len(df)

        for i in range(n_candles):
            c_open_time = open_times.iloc[i].to_pydatetime()
            c_close_time = close_times.iloc[i].to_pydatetime()
            close_p = closes[i]
            high_p = highs[i]
            low_p = lows[i]

            # Ingest all pivots whose confirmation_time <= c_open_time
            while p_idx < n_pivots and pivots[p_idx].confirmation_time <= c_open_time:
                p = pivots[p_idx]
                if p.pivot_type == "HIGH":
                    active_high = p
                elif p.pivot_type == "LOW":
                    active_low = p
                p_idx += 1

            # Check for Bullish Break (above active_high)
            if active_high is not None and active_high.pivot_time not in broken_levels:
                break_price = close_p if self.break_by_close else high_p
                if break_price > active_high.pivot_price:
                    # Break occurred
                    event_type = "BOS_BULL" if current_trend == 1 else "CHOCH_BULL"
                    current_trend = 1
                    broken_levels.add(active_high.pivot_time)

                    breaks.append(
                        StructureEventRecord(
                            event_time=c_close_time,
                            event_type=event_type,
                            price=float(break_price),
                            broken_level=active_high.pivot_price,
                            broken_pivot_time=active_high.pivot_time,
                            confirmed_candle_time=c_close_time,
                            timeframe=timeframe,
                            metadata={
                                "level_pivot_time": str(active_high.pivot_time),
                                "level_confirmation_time": str(active_high.confirmation_time),
                            },
                        )
                    )

            # Check for Bearish Break (below active_low)
            if active_low is not None and active_low.pivot_time not in broken_levels:
                break_price = close_p if self.break_by_close else low_p
                if break_price < active_low.pivot_price:
                    # Break occurred
                    event_type = "BOS_BEAR" if current_trend == -1 else "CHOCH_BEAR"
                    current_trend = -1
                    broken_levels.add(active_low.pivot_time)

                    breaks.append(
                        StructureEventRecord(
                            event_time=c_close_time,
                            event_type=event_type,
                            price=float(break_price),
                            broken_level=active_low.pivot_price,
                            broken_pivot_time=active_low.pivot_time,
                            confirmed_candle_time=c_close_time,
                            timeframe=timeframe,
                            metadata={
                                "level_pivot_time": str(active_low.pivot_time),
                                "level_confirmation_time": str(active_low.confirmation_time),
                            },
                        )
                    )

        return breaks
