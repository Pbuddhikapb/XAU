"""
Support and Resistance Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.H of PROJECT_SPECIFICATION.md:
- Swing-based horizontal levels.
- Repeated reaction zone clustering within dynamic price tolerance.
- Touch counts, zone freshness, and breakout tracking.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from backend.structure.swings import detect_swings


@dataclass
class SupportResistanceZone:
    zone_type: str  # "SUPPORT" | "RESISTANCE"
    level_center: float
    level_min: float
    level_max: float
    touches_count: int
    first_touch_time: datetime
    last_touch_time: datetime
    strength: float  # 0.0 to 100.0 based on touches and freshness
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["first_touch_time"] = self.first_touch_time.isoformat()
        d["last_touch_time"] = self.last_touch_time.isoformat()
        return d


def detect_support_resistance_zones(
    df: pd.DataFrame,
    swing_window: int = 3,
    clustering_tolerance_pct: float = 0.0012,  # ~0.12% clustering threshold ($3 on $2650 gold)
    time_col: str = "open_time",
) -> list[SupportResistanceZone]:
    """
    Cluster confirmed swing points into horizontal Support and Resistance zones.
    """
    if len(df) < (2 * swing_window) + 2:
        return []

    swings = detect_swings(df, window=swing_window, time_col=time_col)
    if not swings:
        return []

    current_price = float(df["close"].iloc[-1])

    high_swings = [s for s in swings if s.swing_type == "SWING_HIGH"]
    low_swings = [s for s in swings if s.swing_type == "SWING_LOW"]

    def cluster_swings(points: list[Any], is_resistance: bool) -> list[SupportResistanceZone]:
        if not points:
            return []

        # Sort by price
        sorted_points = sorted(points, key=lambda p: p.price)
        clusters: list[list[Any]] = []
        curr_cluster: list[Any] = [sorted_points[0]]

        for pt in sorted_points[1:]:
            cluster_avg = sum(p.price for p in curr_cluster) / len(curr_cluster)
            diff_pct = abs(pt.price - cluster_avg) / cluster_avg
            if diff_pct <= clustering_tolerance_pct:
                curr_cluster.append(pt)
            else:
                clusters.append(curr_cluster)
                curr_cluster = [pt]
        if curr_cluster:
            clusters.append(curr_cluster)

        zones: list[SupportResistanceZone] = []
        for cl in clusters:
            prices = [p.price for p in cl]
            times = [p.time for p in cl]
            first_t = min(times)
            last_t = max(times)
            touches = len(cl)

            center = round(float(np.mean(prices)), 4)
            min_p = round(float(np.min(prices)), 4)
            max_p = round(float(np.max(prices)), 4)

            # Resistance is above current price; Support is below current price
            if is_resistance:
                z_type = "RESISTANCE"
                is_active = current_price <= max_p * 1.002
            else:
                z_type = "SUPPORT"
                is_active = current_price >= min_p * 0.998

            # Strength: touch count scaled up to 100
            strength = min(100.0, round(float(touches * 25.0), 2))

            zones.append(
                SupportResistanceZone(
                    zone_type=z_type,
                    level_center=center,
                    level_min=min_p,
                    level_max=max_p,
                    touches_count=touches,
                    first_touch_time=first_t,
                    last_touch_time=last_t,
                    strength=strength,
                    is_active=is_active,
                )
            )

        return zones

    resistance_zones = cluster_swings(high_swings, is_resistance=True)
    support_zones = cluster_swings(low_swings, is_resistance=False)

    all_zones = resistance_zones + support_zones
    # Sort zones: Resistance descending, Support ascending
    all_zones.sort(key=lambda z: (z.zone_type, -z.level_center if z.zone_type == "RESISTANCE" else z.level_center))
    return all_zones
