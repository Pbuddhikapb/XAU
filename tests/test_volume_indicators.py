"""
Unit tests for Volume Analysis Module (RVOL, Taker Buy Ratio, Volume Delta, Pressures).
"""

import numpy as np
import pandas as pd

from backend.analytics.volume import (
    calculate_rvol,
    calculate_taker_buy_ratio,
    calculate_volume_delta,
    evaluate_volume_profile,
)


def test_calculate_rvol():
    vol = pd.Series([100.0] * 20 + [250.0])
    rvol = calculate_rvol(vol, period=20)
    # 250 / 100 = 2.5
    assert np.isclose(rvol.iloc[-1], 2.5, atol=0.1)


def test_calculate_taker_buy_ratio():
    vol = pd.Series([100.0, 200.0, 50.0])
    taker_buy = pd.Series([60.0, 150.0, 25.0])
    ratio = calculate_taker_buy_ratio(vol, taker_buy)
    assert np.isclose(ratio.iloc[0], 0.6)
    assert np.isclose(ratio.iloc[1], 0.75)
    assert np.isclose(ratio.iloc[2], 0.5)


def test_calculate_volume_delta():
    vol = pd.Series([100.0, 100.0])
    taker_buy = pd.Series([70.0, 40.0])
    delta_df = calculate_volume_delta(vol, taker_buy)
    # row 0: taker_buy=70, taker_sell=30 -> net_delta = 40
    # row 1: taker_buy=40, taker_sell=60 -> net_delta = -20
    assert delta_df["net_delta"].iloc[0] == 40.0
    assert delta_df["net_delta"].iloc[1] == -20.0
    assert delta_df["cum_delta"].iloc[1] == 20.0


def test_evaluate_volume_profile():
    n = 30
    opens = pd.Series([2650.0] * n)
    highs = pd.Series([2660.0] * n)
    lows = pd.Series([2645.0] * n)
    closes = pd.Series([2658.0] * n)
    volume = pd.Series([100.0] * n)
    taker_buy = pd.Series([70.0] * n)

    prof = evaluate_volume_profile(opens, highs, lows, closes, volume, taker_buy)
    assert prof["taker_buy_ratio"] == 0.7
    assert prof["net_volume_delta"] == 40.0
    assert prof["volume_bias"] == "MODERATE_BUYING"
