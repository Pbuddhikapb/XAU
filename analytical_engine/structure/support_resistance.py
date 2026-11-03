"""
Authoritative Support and Resistance Clustering Engine.
Strictly conforms to Section 5.H of PROJECT_SPECIFICATION.md:
- Clusters confirmed swing points (PivotRecord) within relative price tolerance.
- Evaluates active state point-in-time strictly up to as_of_time.
- Invalidates resistance when candle closes above level_max * (1 + tol).
- Invalidates support when candle closes below level_min * (1 - tol).
- Pure analytical event detection — zero trade setup or execution recommendations.
"""

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.models.outputs import PivotRecord, SupportResistanceZoneRecord
from analytical_engine.structure.pivots import PivotDetector


class SRZoneDetector:
    """
    Clusters confirmed swing points into horizontal Support and Resistance zones.
    """

    def __init__(
        self,
        swing_window: int = 3,
        clustering_tolerance_pct: float = 0.0012,
        timeframe: str = "1h",
    ):
        self.swing_window = swing_window
        self.clustering_tolerance_pct = clustering_tolerance_pct
        self.timeframe = timeframe

    def detect_zones(
        self,
        df: pd.DataFrame,
        pivots: list[PivotRecord] | None = None,
        as_of_time: datetime | None = None,
        clustering_tolerance_pct: float | None = None,
        timeframe: str | None = None,
        time_col: str = "open_time",
        close_time_col: str = "close_time",
    ) -> list[SupportResistanceZoneRecord]:
        """
        Cluster confirmed swing points into point-in-time S/R zones.
        """
        tol = clustering_tolerance_pct or self.clustering_tolerance_pct
        tf = timeframe or self.timeframe

        if df.empty or len(df) < (2 * self.swing_window) + 2:
            return []

        # Slice data up to as_of_time if provided to ensure strict causality
        if as_of_time is not None:
            if as_of_time.tzinfo is None:
                as_of_time = as_of_time.replace(tzinfo=UTC)

            time_series = pd.to_datetime(df[time_col], utc=True)
            eval_df = df.loc[time_series <= as_of_time].copy()
            if len(eval_df) < (2 * self.swing_window) + 2:
                return []
        else:
            eval_df = df.copy()

        if pivots is None:
            detector = PivotDetector(left_bars=self.swing_window, right_bars=self.swing_window)
            pivots = detector.find_pivots(
                eval_df,
                current_time=as_of_time,
                time_col=time_col,
                close_time_col=close_time_col,
            )

        if as_of_time is not None:
            confirmed_pivots = [p for p in pivots if p.confirmation_time <= as_of_time]
        else:
            confirmed_pivots = pivots

        if not confirmed_pivots:
            return []

        current_price = float(eval_df["close"].iloc[-1])
        high_pivots = [p for p in confirmed_pivots if p.pivot_type == "HIGH"]
        low_pivots = [p for p in confirmed_pivots if p.pivot_type == "LOW"]

        closes = eval_df["close"].astype(float).to_numpy()

        def cluster_pivots(points: list[PivotRecord], is_resistance: bool) -> list[SupportResistanceZoneRecord]:
            if not points:
                return []

            sorted_points = sorted(points, key=lambda p: p.pivot_price)
            clusters: list[list[PivotRecord]] = []
            curr_cluster: list[PivotRecord] = [sorted_points[0]]

            for pt in sorted_points[1:]:
                cluster_avg = sum(p.pivot_price for p in curr_cluster) / len(curr_cluster)
                diff_pct = abs(pt.pivot_price - cluster_avg) / cluster_avg
                if diff_pct <= tol:
                    curr_cluster.append(pt)
                else:
                    clusters.append(curr_cluster)
                    curr_cluster = [pt]
            if curr_cluster:
                clusters.append(curr_cluster)

            zones: list[SupportResistanceZoneRecord] = []
            for cl in clusters:
                prices = [p.pivot_price for p in cl]
                times = [p.pivot_time for p in cl]
                conf_times = [p.confirmation_time for p in cl]
                first_t = min(times)
                last_t = max(times)
                latest_conf = max(conf_times)
                touches = len(cl)

                center = round(float(np.mean(prices)), 4)
                min_p = round(float(np.min(prices)), 4)
                max_p = round(float(np.max(prices)), 4)

                # Invalidation Check:
                is_broken = False
                last_conf_idx = max(p.confirmed_index for p in cl)

                if is_resistance:
                    z_type = "RESISTANCE"
                    break_threshold = max_p * (1.0 + tol)
                    for k in range(last_conf_idx + 1, len(closes)):
                        if closes[k] > break_threshold:
                            is_broken = True
                            break
                    is_active = (not is_broken) and (current_price <= max_p * 1.002)
                else:
                    z_type = "SUPPORT"
                    break_threshold = min_p * (1.0 - tol)
                    for k in range(last_conf_idx + 1, len(closes)):
                        if closes[k] < break_threshold:
                            is_broken = True
                            break
                    is_active = (not is_broken) and (current_price >= min_p * 0.998)

                strength = min(100.0, round(float(touches * 25.0), 2))

                zones.append(
                    SupportResistanceZoneRecord(
                        zone_type=z_type,
                        level_center=center,
                        level_min=min_p,
                        level_max=max_p,
                        touch_count=touches,
                        first_touch_time=first_t,
                        last_touch_time=last_t,
                        confirmed_time=latest_conf,
                        strength_score=strength,
                        is_active=is_active,
                        timeframe=tf,
                    )
                )

            return zones

        resistance_zones = cluster_pivots(high_pivots, is_resistance=True)
        support_zones = cluster_pivots(low_pivots, is_resistance=False)

        all_zones = resistance_zones + support_zones
        all_zones.sort(key=lambda z: (z.zone_type, -z.level_center if z.zone_type == "RESISTANCE" else z.level_center))
        return all_zones


def detect_support_resistance_zones(
    df: pd.DataFrame,
    pivots: list[PivotRecord] | None = None,
    swing_window: int = 3,
    clustering_tolerance_pct: float = 0.0012,
    as_of_time: datetime | None = None,
    timeframe: str = "1h",
    time_col: str = "open_time",
    close_time_col: str = "close_time",
) -> list[SupportResistanceZoneRecord]:
    """Convenience functional wrapper delegating to SRZoneDetector."""
    detector = SRZoneDetector(
        swing_window=swing_window,
        clustering_tolerance_pct=clustering_tolerance_pct,
        timeframe=timeframe,
    )
    return detector.detect_zones(
        df=df,
        pivots=pivots,
        as_of_time=as_of_time,
        clustering_tolerance_pct=clustering_tolerance_pct,
        timeframe=timeframe,
        time_col=time_col,
        close_time_col=close_time_col,
    )
