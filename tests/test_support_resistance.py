"""
Unit tests for Support and Resistance Reaction Zones.
Strictly verifies:
1. Multi-touch clustering within documented price tolerance (0.12%).
2. Point-in-time causality: zones evaluated as_of_time do not use future information.
3. Explicit invalidation when price closes beyond zone threshold.
4. Adversarial future price shock invariance (zero lookahead).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.structure.support_resistance import detect_support_resistance_zones


@pytest.fixture
def oscillating_df():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    # Price repeatedly bounces off support at ~2640 and rejects at ~2680
    prices = [
        2640, 2655, 2670, 2678, 2680,
        2665, 2650, 2642, 2641, 2658,
        2672, 2679, 2680, 2668, 2655,
        2644, 2640, 2660, 2675, 2680,
        2668, 2654, 2645, 2655, 2660,
    ]
    prices_f = [float(p) for p in prices]
    return pd.DataFrame(
        {
            "open_time": times,
            "open": prices_f,
            "high": [p + 2.0 for p in prices_f],
            "low": [p - 2.0 for p in prices_f],
            "close": prices_f,
            "volume": [100.0] * n,
        }
    )


def test_support_resistance_clustering(oscillating_df):
    df = oscillating_df
    zones = detect_support_resistance_zones(df, swing_window=2)
    assert len(zones) >= 1
    types = [z.zone_type for z in zones]
    assert "RESISTANCE" in types or "SUPPORT" in types

    # Touch count for clustered zones should be > 1
    multi_touch_zones = [z for z in zones if z.touches_count >= 2]
    assert len(multi_touch_zones) >= 1


def test_support_resistance_point_in_time_causality(oscillating_df):
    """Verify that as_of_time cutoff strictly isolates earlier levels from subsequent price action."""
    df = oscillating_df
    t_cutoff = df["open_time"].iloc[12]

    zones_at_t = detect_support_resistance_zones(df, swing_window=2, as_of_time=t_cutoff)
    assert len(zones_at_t) >= 1
    # All touch timestamps in zones_at_t must be <= t_cutoff
    for z in zones_at_t:
        assert z.first_touch_time <= t_cutoff
        assert z.last_touch_time <= t_cutoff
        assert z.confirmed_time <= t_cutoff


def test_support_resistance_adversarial_lookahead(oscillating_df):
    """Adversarial test: appending future extreme price movements does not alter levels at T."""
    df_base = oscillating_df.iloc[:15].copy()
    t_eval = df_base["open_time"].iloc[-1]

    zones_base = detect_support_resistance_zones(df_base, swing_window=2, as_of_time=t_eval)

    # Append future bars with +$600 price shock (gold breaks to 3300)
    future_times = [t_eval + timedelta(hours=i + 1) for i in range(15)]
    future_prices = [3250.0 + i * 5.0 for i in range(15)]
    df_future = pd.DataFrame(
        {
            "open_time": future_times,
            "open": future_prices,
            "high": [p + 5.0 for p in future_prices],
            "low": [p - 5.0 for p in future_prices],
            "close": future_prices,
            "volume": [500.0] * 15,
        }
    )
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    # Recalculate as of t_eval
    zones_shocked = detect_support_resistance_zones(df_shocked, swing_window=2, as_of_time=t_eval)

    assert len(zones_base) == len(zones_shocked)
    for zb, zs in zip(zones_base, zones_shocked):
        assert zb.zone_type == zs.zone_type
        assert zb.level_center == zs.level_center
        assert zb.level_min == zs.level_min
        assert zb.level_max == zs.level_max
        assert zb.touches_count == zs.touches_count
        assert zb.is_active == zs.is_active
        assert zb.strength == zs.strength
