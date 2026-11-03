"""
Support and Resistance Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.H of PROJECT_SPECIFICATION.md and Phase 3 Remediation:
- Swing-based horizontal level clustering within explicit price tolerance.
- Clustering tolerance: 0.0012 (0.12% relative tolerance, ~$3.00 on $2500 gold).
- Point-in-time causal active-level determination: evaluates levels and current price
  strictly as of the evaluation timestamp (as_of_time), completely eliminating
  iloc[-1] lookahead leakage.
- Explicit invalidation rules:
    * Resistance is invalidated if candle closes above level_max * (1 + tolerance).
    * Support is invalidated if candle closes below level_min * (1 - tolerance).
- Preserves level creation, first touch, last touch, and confirmation timestamps.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from analytical_engine.structure.support_resistance import (
    detect_support_resistance_zones as ae_detect_sr,
)
from backend.structure.swings import SwingPoint, detect_swings



@dataclass(frozen=True)
class SupportResistanceZone:
    zone_type: str  # "SUPPORT" | "RESISTANCE"
    level_center: float
    level_min: float
    level_max: float
    touches_count: int
    first_touch_time: datetime
    last_touch_time: datetime
    confirmed_time: datetime  # Timestamp when the latest constituent swing was confirmed
    strength: float  # 0.0 to 100.0 based on touches and freshness
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["first_touch_time"] = self.first_touch_time.isoformat()
        d["last_touch_time"] = self.last_touch_time.isoformat()
        d["confirmed_time"] = self.confirmed_time.isoformat()
        return d


def detect_support_resistance_zones(
    df: pd.DataFrame,
    swing_window: int = 3,
    clustering_tolerance_pct: float = 0.0012,  # 0.12% clustering threshold (~$3 on $2500 gold)
    as_of_time: datetime | None = None,
    time_col: str = "open_time",
    close_time_col: str = "close_time",
) -> list[SupportResistanceZone]:
    """
    Cluster confirmed swing points into horizontal Support and Resistance zones.
    Point-in-time causal: only evaluates swings and price action available up to as_of_time.

    Parameters:
        df: Input DataFrame containing open, high, low, close, and timestamp columns.
        swing_window: Shoulder radius k for swing detection.
        clustering_tolerance_pct: Relative price tolerance for clustering touches into zones.
        as_of_time: Evaluation timestamp cutoff. If None, uses the last bar's timestamp.
        time_col: Open timestamp column.
        close_time_col: Close timestamp column.
    """
    records = ae_detect_sr(
        df=df,
        swing_window=swing_window,
        clustering_tolerance_pct=clustering_tolerance_pct,
        as_of_time=as_of_time,
        time_col=time_col,
        close_time_col=close_time_col,
    )

    zones: list[SupportResistanceZone] = []
    for r in records:
        zones.append(
            SupportResistanceZone(
                zone_type=r.zone_type,
                level_center=r.level_center,
                level_min=r.level_min,
                level_max=r.level_max,
                touches_count=r.touch_count,
                first_touch_time=r.first_touch_time,
                last_touch_time=r.last_touch_time,
                confirmed_time=r.confirmed_time,
                strength=r.strength_score,
                is_active=r.is_active,
            )
        )
    return zones
