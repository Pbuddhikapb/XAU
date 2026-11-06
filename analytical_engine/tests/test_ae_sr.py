"""
Unit and edge-case tests for analytical_engine.structure.support_resistance.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from analytical_engine.structure.support_resistance import (
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


def test_ae_support_resistance_atr_scaled():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2652.0] * n
    lows = [2648.0] * n
    closes = [2650.0] * n

    # Swings with $3.0 distance: 2670.0 and 2673.0
    highs[3] = 2670.0
    highs[10] = 2673.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    # Range is 4.0, ATR ~ 4.0.
    # With atr_multiplier=0.2, tol_abs = 0.8 (< 3.0) -> not clustered
    zones_tight = detect_support_resistance_zones(df, swing_window=2, atr_multiplier=0.2)
    res_tight = [z for z in zones_tight if z.zone_type == "RESISTANCE"]
    assert all(z.touch_count == 1 for z in res_tight)

    # With atr_multiplier=1.0, tol_abs = 4.0 (> 3.0) -> clustered
    zones_wide = detect_support_resistance_zones(df, swing_window=2, atr_multiplier=1.0)
    res_wide = [z for z in zones_wide if z.zone_type == "RESISTANCE"]
    assert any(z.touch_count >= 2 for z in res_wide)


def test_ae_support_resistance_adversarial_lookahead():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 20
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[3] = 2670.0
    highs[10] = 2671.0

    df_base = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })
    t_eval = times[14]

    zones_base = detect_support_resistance_zones(df_base, swing_window=2, as_of_time=t_eval)

    # Append future shock
    future_times = [times[-1] + timedelta(hours=i + 1) for i in range(15)]
    future_p = [3100.0 + i for i in range(15)]
    df_future = pd.DataFrame({
        "open_time": future_times,
        "open": future_p,
        "high": [p + 5 for p in future_p],
        "low": [p - 5 for p in future_p],
        "close": future_p,
        "volume": [500.0] * 15,
    })
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    zones_shocked = detect_support_resistance_zones(df_shocked, swing_window=2, as_of_time=t_eval)

    assert len(zones_base) == len(zones_shocked)
    for zb, zs in zip(zones_base, zones_shocked, strict=False):
        assert zb.zone_type == zs.zone_type
        assert zb.level_center == zs.level_center
        assert zb.level_min == zs.level_min
        assert zb.level_max == zs.level_max
        assert zb.touch_count == zs.touch_count
        assert zb.is_active == zs.is_active

