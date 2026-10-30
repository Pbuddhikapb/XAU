"""
Unit tests for Volume-Weighted Average Price (VWAP) and Session Reset.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from backend.analytics.vwap import calculate_session_anchored_vwap, evaluate_vwap_position


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

    # Bar index 2 is at 23:00 UTC -> session resets!
    # At 23:00, Typical Price = (2650 + 2646 + 2648) / 3 = 2648.0
    # Since it's the first bar of the new session, VWAP must equal its typical price!
    tp_23 = (2650.0 + 2646.0 + 2648.0) / 3.0
    assert np.isclose(vwap_df.loc[2, "vwap"], tp_23)


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
