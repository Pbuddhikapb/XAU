"""
Unit and edge-case tests for analytical_engine.structure.support_resistance.
"""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from analytical_engine.structure.support_resistance import (
    SRZoneDetector,
    detect_support_resistance_zones,
)


def test_ae_support_resistance_clustering():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing High 1 at index 3: High = 2670.0
    highs[3] = 2670.0
    # Swing High 2 at index 10: High = 2671.5 (within 0.12% clustering tolerance of 2670)
    highs[10] = 2671.5
    # Swing Low 1 at index 16: Low = 2630.0
    lows[16] = 2630.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    zones = detect_support_resistance_zones(df, swing_window=2, clustering_tolerance_pct=0.0012)
    res_zones = [z for z in zones if z.zone_type == "RESISTANCE"]
    sup_zones = [z for z in zones if z.zone_type == "SUPPORT"]

    assert len(res_zones) >= 1
    # Clustered zone should encompass both high touches
    best_res = res_zones[0]
    assert best_res.touch_count >= 2
    assert best_res.level_min <= 2670.0
    assert best_res.level_max >= 2671.5

    assert len(sup_zones) >= 1
    assert sup_zones[0].touch_count >= 1
