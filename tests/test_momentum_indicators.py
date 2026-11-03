"""
Unit tests for Momentum Analysis Module (RSI, MACD, ROC).
"""

import numpy as np
import pandas as pd

from backend.analytics.momentum import (
    calculate_macd,
    calculate_roc,
    calculate_rsi,
    evaluate_momentum,
)


def test_calculate_rsi_bounds_and_trends():
    # Consecutive gains must push RSI above 70
    gains = pd.Series([2600.0 + i * 5.0 for i in range(40)])
    rsi_up = calculate_rsi(gains, period=14)
    assert rsi_up.iloc[-1] > 70.0
    assert 0.0 <= rsi_up.dropna().min() <= 100.0
    assert 0.0 <= rsi_up.dropna().max() <= 100.0

    # Consecutive losses must push RSI below 30
    losses = pd.Series([2800.0 - i * 5.0 for i in range(40)])
    rsi_down = calculate_rsi(losses, period=14)
    assert rsi_down.iloc[-1] < 30.0


def test_calculate_macd_crossover():
    # Price dropping then reversing upward sharply
    prices = [2700.0 - i * 2.0 for i in range(40)] + [2620.0 + i * 4.0 for i in range(30)]
    series = pd.Series(prices)
    macd_df = calculate_macd(series, 12, 26, 9)

    assert set(macd_df.columns) == {"macd", "signal", "hist"}
    # After strong upward reversal, histogram should be positive
    assert macd_df["hist"].iloc[-1] > 0.0
    assert macd_df["macd"].iloc[-1] > macd_df["signal"].iloc[-1]


def test_calculate_roc():
    prices = pd.Series([100.0] * 14 + [110.0])
    roc = calculate_roc(prices, period=14)
    assert np.isclose(roc.iloc[-1], 10.0)


def test_evaluate_momentum():
    # Accelerating upward series to trigger positive MACD histogram
    series = pd.Series([2650.0 + i * 1.5 + (i * 0.1) ** 2 for i in range(50)])
    eval_m = evaluate_momentum(series)
    assert eval_m["rsi_14"] > 60.0
    assert eval_m["macd_hist"] > 0
    assert eval_m["momentum_bias"] in ("BULLISH", "POTENTIAL_BULLISH")
