"""
Unit tests for Volume-Weighted Average Price (VWAP) calculation engine.
Verifies:
1. TradFi Session-anchored VWAP (dynamic CME Globex 18:00 New York / static UTC hour)
2. UTC Calendar-day VWAP (00:00:00 UTC boundary)
3. Parity and clear distinction between Calendar-day vs TradFi session anchoring
4. Daylight Saving Time (EDT vs EST) reset behavior
5. Standard deviation bands (+/- 1 sigma, +/- 2 sigma) and zone classification
6. Edge case robustness (zero volume, empty DataFrame)
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from backend.analytics.vwap import (
    calculate_session_anchored_vwap,
    calculate_utc_daily_vwap,
    evaluate_vwap_position,
)


def test_session_anchored_vwap_calculation():
    # Construct 1-hour candles starting at 21:00 UTC (before session reset at 23:00)
    base_time = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
    times = [base_time + timedelta(hours=i) for i in range(6)]

    # 21:00, 22:00 -> session 1
    # 23:00, 00:00, 01:00, 02:00 -> session 2 (reset at 23:00)
    data = {
        "open_time": times,
        "high": [2652.0, 2654.0, 2650.0, 2655.0, 2660.0, 2658.0],
        "low": [2648.0, 2649.0, 2646.0, 2648.0, 2652.0, 2653.0],
        "close": [2650.0, 2653.0, 2648.0, 2653.0, 2657.0, 2655.0],
        "volume": [100.0, 200.0, 150.0, 150.0, 200.0, 100.0],
    }
    df = pd.DataFrame(data)

    vwap_df = calculate_session_anchored_vwap(df, session_reset_hour_utc=23)
    assert "vwap" in vwap_df.columns
    assert "vwap_upper_1" in vwap_df.columns
    assert "vwap_lower_1" in vwap_df.columns
    assert "vwap_upper_2" in vwap_df.columns
    assert "vwap_lower_2" in vwap_df.columns
    assert "anchor_type" in vwap_df.columns
    assert (vwap_df["anchor_type"] == "TRADIFI_SESSION").all()

    # Bar index 2 is at 23:00 UTC -> session resets!
    # At 23:00, Typical Price = (2650 + 2646 + 2648) / 3 = 2648.0
    # Since it's the first bar of the new session, VWAP must equal its typical price!
    tp_23 = (2650.0 + 2646.0 + 2648.0) / 3.0
    assert np.isclose(vwap_df.loc[2, "vwap"], tp_23)


def test_utc_daily_vwap_vs_session_anchored_vwap():
    """
    Demonstrate that UTC Daily VWAP and TradFi Session VWAP have distinct,
    independent reset times and produce distinct series when evaluated across midnight.
    """
    # Create 1h candles from 20:00 UTC Day 1 to 04:00 UTC Day 2
    base_time = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)
    times = [base_time + timedelta(hours=i) for i in range(9)]
    # Hours: 20, 21, 22, 23 (Day 1), 00, 01, 02, 03, 04 (Day 2)

    df = pd.DataFrame({
        "open_time": times,
        "high": [2650.0 + i * 2.0 for i in range(9)],
        "low": [2640.0 + i * 2.0 for i in range(9)],
        "close": [2645.0 + i * 2.0 for i in range(9)],
        "volume": [100.0] * 9,
    })

    utc_daily = calculate_utc_daily_vwap(df)
    tradfi_session = calculate_session_anchored_vwap(df, session_reset_hour_utc=23)

    assert utc_daily["anchor_type"].iloc[0] == "UTC_CALENDAR_DAY"
    assert tradfi_session["anchor_type"].iloc[0] == "TRADIFI_SESSION"

    # Index 3 is 23:00 UTC (Day 1)
    # TradFi session resets at 23:00, so TradFi VWAP resets to typical price of bar 3
    tp_3 = (df.loc[3, "high"] + df.loc[3, "low"] + df.loc[3, "close"]) / 3.0
    assert np.isclose(tradfi_session.loc[3, "vwap"], tp_3)
    # But UTC Daily VWAP has NOT reset yet (it accumulated bars 0, 1, 2, 3)
    assert not np.isclose(utc_daily.loc[3, "vwap"], tp_3)

    # Index 4 is 00:00 UTC (Day 2)
    # UTC Daily resets at 00:00, so UTC VWAP resets to typical price of bar 4
    tp_4 = (df.loc[4, "high"] + df.loc[4, "low"] + df.loc[4, "close"]) / 3.0
    assert np.isclose(utc_daily.loc[4, "vwap"], tp_4)
    # But TradFi session did NOT reset at 00:00 (it is at bar 2 of its session)
    assert not np.isclose(tradfi_session.loc[4, "vwap"], tp_4)


def test_vwap_dst_transition():
    """
    Test dynamic timezone-aware CME Globex session reset (18:00 America/New_York):
    - In Summer (EDT, UTC-4), 18:00 ET is 22:00:00 UTC.
    - In Winter (EST, UTC-5), 18:00 ET is 23:00:00 UTC.
    """
    # 1. Summer (July 15, EDT):
    summer_base = datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
    summer_times = [summer_base + timedelta(hours=i) for i in range(5)]  # 20, 21, 22, 23, 24
    summer_df = pd.DataFrame({
        "open_time": summer_times,
        "high": [2600.0, 2605.0, 2610.0, 2615.0, 2620.0],
        "low": [2590.0, 2595.0, 2600.0, 2605.0, 2610.0],
        "close": [2595.0, 2600.0, 2605.0, 2610.0, 2615.0],
        "volume": [100.0] * 5,
    })
    res_summer = calculate_session_anchored_vwap(summer_df, session_reset_hour_utc=None)
    # In EDT, 22:00 UTC is bar index 2. Bar index 2 must be the start of a new session!
    tp_summer_22 = (summer_df.loc[2, "high"] + summer_df.loc[2, "low"] + summer_df.loc[2, "close"]) / 3.0
    assert np.isclose(res_summer.loc[2, "vwap"], tp_summer_22)

    # 2. Winter (December 15, EST):
    winter_base = datetime(2026, 12, 15, 21, 0, tzinfo=UTC)
    winter_times = [winter_base + timedelta(hours=i) for i in range(5)]  # 21, 22, 23, 00, 01
    winter_df = pd.DataFrame({
        "open_time": winter_times,
        "high": [2600.0, 2605.0, 2610.0, 2615.0, 2620.0],
        "low": [2590.0, 2595.0, 2600.0, 2605.0, 2610.0],
        "close": [2595.0, 2600.0, 2605.0, 2610.0, 2615.0],
        "volume": [100.0] * 5,
    })
    res_winter = calculate_session_anchored_vwap(winter_df, session_reset_hour_utc=None)
    # In EST, 23:00 UTC is bar index 2. Bar index 2 must be the start of a new session!
    tp_winter_23 = (winter_df.loc[2, "high"] + winter_df.loc[2, "low"] + winter_df.loc[2, "close"]) / 3.0
    assert np.isclose(res_winter.loc[2, "vwap"], tp_winter_23)


def test_evaluate_vwap_position():
    base_time = datetime(2026, 10, 20, 23, 0, tzinfo=UTC)
    times = [base_time + timedelta(hours=i) for i in range(5)]
    df = pd.DataFrame(
        {
            "open_time": times,
            "high": [2655.0] * 5,
            "low": [2645.0] * 5,
            "close": [2650.0] * 5,
            "volume": [100.0] * 5,
        }
    )

    pos = evaluate_vwap_position(df, session_reset_hour_utc=23)
    assert pos["vwap"] == 2650.0
    assert pos["zone"] == "AT_VWAP"
    assert pos["vwap_upper_1"] == 2650.0
    assert pos["vwap_lower_1"] == 2650.0


def test_evaluate_vwap_zones():
    base_time = datetime(2026, 10, 20, 23, 0, tzinfo=UTC)
    times = [base_time + timedelta(hours=i) for i in range(4)]
    # Construct bars with varying typical price to create nonzero standard deviation
    df = pd.DataFrame({
        "open_time": times,
        "high": [2660.0, 2640.0, 2670.0, 2720.0],
        "low": [2640.0, 2620.0, 2650.0, 2700.0],
        "close": [2650.0, 2630.0, 2660.0, 2715.0],
        "volume": [100.0, 100.0, 100.0, 100.0],
    })

    pos = evaluate_vwap_position(df, session_reset_hour_utc=23)
    # Last candle close is 2715.0, which is significantly above VWAP
    assert pos["zone"] in ("MODERATELY_ABOVE", "EXTREME_OVERBOUGHT")
    assert pos["vwap"] < 2715.0


def test_vwap_empty_and_zero_volume():
    empty_df = pd.DataFrame(columns=["open_time", "high", "low", "close", "volume"])
    empty_res = calculate_session_anchored_vwap(empty_df)
    assert empty_res.empty

    eval_empty = evaluate_vwap_position(empty_df)
    assert eval_empty["vwap"] == 0.0

    # Zero volume handling: VWAP defaults gracefully to typical price without ZeroDivisionError
    df_zero = pd.DataFrame({
        "open_time": [datetime(2026, 10, 20, 23, 0, tzinfo=UTC)],
        "high": [2650.0],
        "low": [2640.0],
        "close": [2645.0],
        "volume": [0.0],
    })
    res_zero = calculate_session_anchored_vwap(df_zero, session_reset_hour_utc=23)
    assert np.isclose(res_zero.loc[0, "vwap"], 2645.0)
