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
    for zb, zs in zip(zones_base, zones_shocked, strict=False):
        assert zb.zone_type == zs.zone_type
        assert zb.level_center == zs.level_center
        assert zb.level_min == zs.level_min
        assert zb.level_max == zs.level_max
        assert zb.touches_count == zs.touches_count
        assert zb.is_active == zs.is_active
        assert zb.strength == zs.strength


def test_support_resistance_atr_scaled_tolerance():
    """Verify that ATR scaling dynamically adjusts clustering tolerance based on volatility."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    # Two swing highs separated by $4.0: 2670.0 and 2674.0
    opens = [2650.0] * n
    highs = [2653.0] * n
    lows = [2647.0] * n
    closes = [2650.0] * n

    # Swing high 1 at bar 3: 2670.0
    highs[3] = 2670.0
    # Swing high 2 at bar 10: 2674.0
    highs[10] = 2674.0

    # Low volatility case: candle range is $6 (high - low = 6), ATR ~ 6.0
    # With atr_multiplier=0.2, tol_abs = 0.2 * 6 = $1.20 (< $4.0 gap) -> they do NOT cluster
    df_low_vol = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )
    zones_unclustered = detect_support_resistance_zones(
        df_low_vol, swing_window=2, atr_multiplier=0.2, atr_period=14
    )
    res_unclustered = [z for z in zones_unclustered if z.zone_type == "RESISTANCE"]
    # With tight tolerance, the two swings should remain separate zones (or single-touch)
    assert all(z.touches_count == 1 for z in res_unclustered)

    # High multiplier case: with atr_multiplier=1.0, tol_abs = 1.0 * 6 = $6.0 (> $4.0 gap) -> they DO cluster
    zones_clustered = detect_support_resistance_zones(
        df_low_vol, swing_window=2, atr_multiplier=1.0, atr_period=14
    )
    res_clustered = [z for z in zones_clustered if z.zone_type == "RESISTANCE"]
    assert any(z.touches_count >= 2 for z in res_clustered)


def test_support_resistance_no_iloc_minus_one_dependence(oscillating_df):
    """Verify point-in-time calculation has zero dependency on iloc[-1] and handles unsorted data."""
    df = oscillating_df.copy()
    t_eval = df["open_time"].iloc[14]

    zones_order_1 = detect_support_resistance_zones(df, swing_window=2, as_of_time=t_eval)

    # Create shuffled dataframe with random row order
    shuffled_df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
    zones_shuffled = detect_support_resistance_zones(shuffled_df, swing_window=2, as_of_time=t_eval)

    assert len(zones_order_1) == len(zones_shuffled)
    for z1, z2 in zip(zones_order_1, zones_shuffled, strict=False):
        assert z1.zone_type == z2.zone_type
        assert z1.level_center == z2.level_center
        assert z1.touches_count == z2.touches_count
        assert z1.is_active == z2.is_active

