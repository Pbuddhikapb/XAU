"""
Unit tests for Support and Resistance Reaction Zones.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.support_resistance import detect_support_resistance_zones


def test_support_resistance_clustering():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    # Price repeatedly bounces off support at ~2640 and rejects at ~2680
    prices = [
        2640,
        2655,
        2670,
        2678,
        2680,
        2665,
        2650,
        2642,
        2641,
        2658,
        2672,
        2679,
        2680,
        2668,
        2655,
        2644,
        2640,
        2660,
        2675,
        2680,
        2668,
        2654,
        2645,
        2655,
        2660,
    ]
    prices_f = [float(p) for p in prices]
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices_f,
            "high": [p + 2.0 for p in prices_f],
            "low": [p - 2.0 for p in prices_f],
            "close": prices_f,
            "volume": [100.0] * n,
        }
    )

    zones = detect_support_resistance_zones(df, swing_window=2)
    assert len(zones) >= 1
    types = [z.zone_type for z in zones]
    assert "RESISTANCE" in types or "SUPPORT" in types

    # Touch count for clustered zones should be > 1
    multi_touch_zones = [z for z in zones if z.touches_count >= 2]
    assert len(multi_touch_zones) >= 1
