"""
Unit tests for Volatility Analysis Module (ATR, Bollinger Bands, Percentile, Squeeze).
"""

import numpy as np
import pandas as pd

from backend.analytics.volatility import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_historical_volatility_percentile,
    evaluate_volatility_regime,
)


def test_calculate_atr_constant_range():
    # If High - Low is always 10 and previous Close equals open, ATR must converge to 10
    n = 40
    highs = pd.Series([2650.0 + i * 2.0 + 5.0 for i in range(n)])
    lows = pd.Series([2650.0 + i * 2.0 - 5.0 for i in range(n)])
    closes = pd.Series([2650.0 + i * 2.0 for i in range(n)])

    atr_s = calculate_atr(highs, lows, closes, period=14)
    assert np.isclose(atr_s.iloc[-1], 10.0, atol=0.2)


def test_calculate_bollinger_bands_invariants():
    np.random.seed(42)
    prices = pd.Series(2650.0 + np.random.normal(0, 5, 60))
    bb = calculate_bollinger_bands(prices, period=20, num_std=2.0)

    # Invariants: upper >= middle >= lower
    valid_bb = bb.dropna()
    assert (valid_bb["upper"] >= valid_bb["middle"]).all()
    assert (valid_bb["middle"] >= valid_bb["lower"]).all()
    assert (valid_bb["bandwidth"] >= 0).all()


def test_historical_volatility_percentile():
    # ATR sequence where last value is the maximum
    atr_vals = pd.Series(np.linspace(5.0, 25.0, 50))
    pct = calculate_historical_volatility_percentile(atr_vals, lookback=50)
    assert pct.iloc[-1] == 100.0


def test_evaluate_volatility_regime():
    n = 60
    closes = pd.Series([2650.0 + np.sin(i / 5.0) * 3.0 for i in range(n)])
    highs = closes + 5.0
    lows = closes - 5.0

    eval_v = evaluate_volatility_regime(highs, lows, closes)
    assert eval_v["atr_14"] > 0
    assert eval_v["bb_upper"] > eval_v["bb_lower"]
    assert eval_v["regime"] in (
        "NORMAL",
        "COMPRESSED_SQUEEZE",
        "SUBDUED",
        "HIGH_VOLATILITY_EXPANSION",
        "ELEVATED",
    )
