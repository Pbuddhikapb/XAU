"""
Divergence calculation engine: Detects Regular and Hidden Bullish/Bearish divergences
across RSI and MACD Histogram using confirmed price and indicator pivots.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from analytical_engine.models.outputs import DivergenceRecord, PivotRecord
from analytical_engine.structure.pivots import PivotDetector


class DivergenceDetector:
    """
    Detects confirmed momentum divergences between price action and momentum oscillators (RSI, MACD Hist).

    Divergence Types:
        1. Regular Bullish:
           Price forms Lower Low (Price2 < Price1) while Indicator forms Higher Low (Ind2 > Ind1).
           Indicates bearish momentum exhaustion and potential bullish reversal.
        2. Regular Bearish:
           Price forms Higher High (Price2 > Price1) while Indicator forms Lower High (Ind2 < Ind1).
           Indicates bullish momentum exhaustion and potential bearish reversal.
        3. Hidden Bullish:
           Price forms Higher Low (Price2 > Price1) while Indicator forms Lower Low (Ind2 < Ind1).
           Indicates bullish trend continuation.
        4. Hidden Bearish:
           Price forms Lower High (Price2 < Price1) while Indicator forms Higher High (Ind2 > Ind1).
           Indicates bearish trend continuation.

    Temporal Integrity:
        A divergence is identified ONLY after Pivot 2 has been confirmed.
        confirmation_time = Pivot 2's confirmation_time.
    """

    def __init__(
        self,
        min_bars_separation: int = 5,
        max_bars_separation: int = 60,
    ):
        self.min_bars_separation = min_bars_separation
        self.max_bars_separation = max_bars_separation

    def detect_divergences(
        self,
        df: pd.DataFrame,
        indicator_series: Sequence[float] | np.ndarray | pd.Series,
        indicator_name: str = "RSI",
        pivots: list[PivotRecord] | None = None,
        left_bars: int = 2,
        right_bars: int = 2,
    ) -> list[DivergenceRecord]:
        """
        Scan price series and indicator series for confirmed divergences.

        Parameters:
            df: Validated DataFrame with open_time, high, low, close.
            indicator_series: 1D array of indicator values corresponding row-for-row with df.
            indicator_name: 'RSI' or 'MACD_HIST'.
            pivots: Optional precomputed PivotRecord list. If None, PivotDetector will extract them.
        """
        if df.empty or len(df) < (self.min_bars_separation + right_bars + 1):
            return []

        ind_arr = np.asarray(indicator_series, dtype=np.float64)
        if len(ind_arr) != len(df):
            raise ValueError(f"Indicator array length ({len(ind_arr)}) does not match DataFrame length ({len(df)}).")

        if pivots is None:
            detector = PivotDetector(left_bars=left_bars, right_bars=right_bars)
            pivots = detector.find_pivots(df)

        timeframe = df.attrs.get("timeframe", "1m")
        open_times = pd.to_datetime(df["open_time"])
        ts_to_idx = {open_times.iloc[i].to_pydatetime(): i for i in range(len(df))}

        # Separate into Highs and Lows
        high_pivots = [p for p in pivots if p.pivot_type == "HIGH"]
        low_pivots = [p for p in pivots if p.pivot_type == "LOW"]

        divergences: list[DivergenceRecord] = []

        # 1. Evaluate Low Pivots for Bullish Divergences (Regular & Hidden)
        for i in range(1, len(low_pivots)):
            p1 = low_pivots[i - 1]
            p2 = low_pivots[i]

            idx1 = ts_to_idx.get(p1.pivot_time)
            idx2 = ts_to_idx.get(p2.pivot_time)

            if idx1 is None or idx2 is None:
                continue

            bar_sep = idx2 - idx1
            if bar_sep < self.min_bars_separation or bar_sep > self.max_bars_separation:
                continue

            ind1 = ind_arr[idx1]
            ind2 = ind_arr[idx2]

            if not np.isfinite(ind1) or not np.isfinite(ind2):
                continue

            # Regular Bullish: Price LL, Indicator HL
            if p2.pivot_price < p1.pivot_price and ind2 > ind1:
                divergences.append(
                    DivergenceRecord(
                        divergence_type="REGULAR_BULLISH",
                        indicator_name=indicator_name,
                        price_pivot_1_time=p1.pivot_time,
                        price_pivot_1_price=p1.pivot_price,
                        price_pivot_2_time=p2.pivot_time,
                        price_pivot_2_price=p2.pivot_price,
                        indicator_val_1=float(ind1),
                        indicator_val_2=float(ind2),
                        confirmation_time=p2.confirmation_time,
                        confirmation_lag_bars=p2.confirmation_lag_bars,
                        timeframe=timeframe,
                        metadata={"bar_separation": bar_sep},
                    )
                )

            # Hidden Bullish: Price HL, Indicator LL
            elif p2.pivot_price > p1.pivot_price and ind2 < ind1:
                divergences.append(
                    DivergenceRecord(
                        divergence_type="HIDDEN_BULLISH",
                        indicator_name=indicator_name,
                        price_pivot_1_time=p1.pivot_time,
                        price_pivot_1_price=p1.pivot_price,
                        price_pivot_2_time=p2.pivot_time,
                        price_pivot_2_price=p2.pivot_price,
                        indicator_val_1=float(ind1),
                        indicator_val_2=float(ind2),
                        confirmation_time=p2.confirmation_time,
                        confirmation_lag_bars=p2.confirmation_lag_bars,
                        timeframe=timeframe,
                        metadata={"bar_separation": bar_sep},
                    )
                )

        # 2. Evaluate High Pivots for Bearish Divergences (Regular & Hidden)
        for i in range(1, len(high_pivots)):
            p1 = high_pivots[i - 1]
            p2 = high_pivots[i]

            idx1 = ts_to_idx.get(p1.pivot_time)
            idx2 = ts_to_idx.get(p2.pivot_time)

            if idx1 is None or idx2 is None:
                continue

            bar_sep = idx2 - idx1
            if bar_sep < self.min_bars_separation or bar_sep > self.max_bars_separation:
                continue

            ind1 = ind_arr[idx1]
            ind2 = ind_arr[idx2]

            if not np.isfinite(ind1) or not np.isfinite(ind2):
                continue

            # Regular Bearish: Price HH, Indicator LH
            if p2.pivot_price > p1.pivot_price and ind2 < ind1:
                divergences.append(
                    DivergenceRecord(
                        divergence_type="REGULAR_BEARISH",
                        indicator_name=indicator_name,
                        price_pivot_1_time=p1.pivot_time,
                        price_pivot_1_price=p1.pivot_price,
                        price_pivot_2_time=p2.pivot_time,
                        price_pivot_2_price=p2.pivot_price,
                        indicator_val_1=float(ind1),
                        indicator_val_2=float(ind2),
                        confirmation_time=p2.confirmation_time,
                        confirmation_lag_bars=p2.confirmation_lag_bars,
                        timeframe=timeframe,
                        metadata={"bar_separation": bar_sep},
                    )
                )

            # Hidden Bearish: Price LH, Indicator HH
            elif p2.pivot_price < p1.pivot_price and ind2 > ind1:
                divergences.append(
                    DivergenceRecord(
                        divergence_type="HIDDEN_BEARISH",
                        indicator_name=indicator_name,
                        price_pivot_1_time=p1.pivot_time,
                        price_pivot_1_price=p1.pivot_price,
                        price_pivot_2_time=p2.pivot_time,
                        price_pivot_2_price=p2.pivot_price,
                        indicator_val_1=float(ind1),
                        indicator_val_2=float(ind2),
                        confirmation_time=p2.confirmation_time,
                        confirmation_lag_bars=p2.confirmation_lag_bars,
                        timeframe=timeframe,
                        metadata={"bar_separation": bar_sep},
                    )
                )

        divergences.sort(key=lambda d: d.confirmation_time)
        return divergences
