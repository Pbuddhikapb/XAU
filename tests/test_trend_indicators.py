"""
Unit tests for Trend Analysis Module (EMA, ADX, DMI, Trend Strength).
"""

import numpy as np
import pandas as pd

from backend.analytics.trend import (
    calculate_adx_dmi,
    calculate_ema,
    calculate_trend_emas,
    evaluate_trend_direction_and_strength,
)


def test_calculate_ema_math():
    prices = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    ema_3 = calculate_ema(prices, period=3)
    assert len(ema_3) == len(prices)
    # Standard financial EMA: seeded with SMA of first 3 bars at index 2
    # ema[0] = nan, ema[1] = nan
    # ema[2] = SMA(10, 11, 12) = 11.0
    # ema[3] = 0.5 * 13 + 0.5 * 11.0 = 12.0
    # ema[4] = 0.5 * 14 + 0.5 * 12.0 = 13.0
    assert np.isnan(ema_3.iloc[0])
    assert np.isnan(ema_3.iloc[1])
    assert np.isclose(ema_3.iloc[2], 11.0)
    assert np.isclose(ema_3.iloc[3], 12.0)
    assert np.isclose(ema_3.iloc[4], 13.0)
    assert np.isclose(ema_3.iloc[5], 14.0)


def test_calculate_trend_emas_keys():
    prices = pd.Series(np.linspace(2600.0, 2700.0, 250))
    emas = calculate_trend_emas(prices, periods=(20, 50, 100, 200))
    assert set(emas.keys()) == {"ema_20", "ema_50", "ema_100", "ema_200"}
    assert emas["ema_20"].iloc[-1] > emas["ema_50"].iloc[-1]
    assert emas["ema_50"].iloc[-1] > emas["ema_100"].iloc[-1]
    assert emas["ema_100"].iloc[-1] > emas["ema_200"].iloc[-1]


def test_calculate_adx_dmi_trending():
    # Construct steady uptrend
    n = 60
    highs = pd.Series([2600.0 + i * 2.0 + 1.0 for i in range(n)])
    lows = pd.Series([2600.0 + i * 2.0 - 1.0 for i in range(n)])
    closes = pd.Series([2600.0 + i * 2.0 for i in range(n)])

    dmi_df = calculate_adx_dmi(highs, lows, closes, period=14)
    assert "plus_di" in dmi_df.columns
    assert "minus_di" in dmi_df.columns
    assert "adx" in dmi_df.columns

    # In a strong uptrend, +DI must dominate -DI and ADX should be strong
    last_row = dmi_df.iloc[-1]
    assert last_row["plus_di"] > last_row["minus_di"]
    assert last_row["adx"] > 25.0


def test_evaluate_trend_direction_bullish():
    # Strong upward stack
    n = 250
    highs = pd.Series([2500.0 + i * 1.5 + 2.0 for i in range(n)])
    lows = pd.Series([2500.0 + i * 1.5 - 2.0 for i in range(n)])
    closes = pd.Series([2500.0 + i * 1.5 for i in range(n)])

    eval_result = evaluate_trend_direction_and_strength(closes, highs, lows)
    assert eval_result["direction"] == "BULLISH"
    assert eval_result["strength"] > 30.0
    assert eval_result["emas"]["ema_20"] > eval_result["emas"]["ema_50"]
