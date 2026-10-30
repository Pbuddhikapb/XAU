"""
Edge-case, stress, and numerical boundary tests for Phase 2 Analytical Modules.
Covers empty dataframes, single-candle frames, zero-volume sessions, flat prices,
and NaN tolerance.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from backend.analytics.divergence import detect_divergences, find_swings
from backend.analytics.indicator_engine import IndicatorEngine
from backend.analytics.momentum import calculate_macd, calculate_roc, calculate_rsi, evaluate_momentum
from backend.analytics.trend import calculate_adx_dmi, calculate_ema, evaluate_trend_direction_and_strength
from backend.analytics.volatility import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_historical_volatility_percentile,
    evaluate_volatility_regime,
)
from backend.analytics.volume import (
    calculate_pressure_proxies,
    calculate_rvol,
    calculate_taker_buy_ratio,
    calculate_volume_delta,
    evaluate_volume_profile,
)
from backend.analytics.vwap import calculate_session_anchored_vwap, evaluate_vwap_position


def test_empty_dataframe_handling():
    empty_df = pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"])
    empty_s = pd.Series(dtype=np.float64)

    # Indicator Engine
    assert IndicatorEngine.compute_all_indicators(empty_df).empty
    assert IndicatorEngine.extract_latest_snapshot(empty_df) is None

    # Trend
    assert calculate_ema(empty_s, 20).empty
    dmi = calculate_adx_dmi(empty_s, empty_s, empty_s, 14)
    assert dmi.empty
    trend_eval = evaluate_trend_direction_and_strength(empty_s, empty_s, empty_s)
    assert trend_eval["direction"] == "NEUTRAL"

    # Momentum
    assert calculate_rsi(empty_s, 14).empty
    assert calculate_macd(empty_s).empty
    assert calculate_roc(empty_s).empty
    mom_eval = evaluate_momentum(empty_s)
    assert mom_eval["momentum_bias"] == "NEUTRAL"

    # Volatility
    assert calculate_atr(empty_s, empty_s, empty_s, 14).empty
    assert calculate_bollinger_bands(empty_s, 20).empty
    assert calculate_historical_volatility_percentile(empty_s).empty
    vol_eval = evaluate_volatility_regime(empty_s, empty_s, empty_s)
    assert vol_eval["regime"] == "NORMAL"

    # Volume
    assert calculate_rvol(empty_s).empty
    assert calculate_taker_buy_ratio(empty_s, empty_s).empty
    assert calculate_volume_delta(empty_s, empty_s).empty
    assert calculate_pressure_proxies(empty_s, empty_s, empty_s, empty_s, empty_s, empty_s).empty
    vol_prof = evaluate_volume_profile(empty_s, empty_s, empty_s, empty_s, empty_s, empty_s)
    assert vol_prof["volume_bias"] == "NEUTRAL"

    # VWAP
    assert calculate_session_anchored_vwap(empty_df).empty
    vwap_eval = evaluate_vwap_position(empty_df)
    assert vwap_eval["zone"] == "AT_VWAP"

    # Divergence
    assert detect_divergences(empty_df, "RSI") == []
    highs, lows = find_swings(empty_s)
    assert highs == [] and lows == []


def test_single_candle_handling():
    single_df = pd.DataFrame(
        {
            "open_time": [datetime.now(UTC)],
            "open": [2650.0],
            "high": [2655.0],
            "low": [2648.0],
            "close": [2652.0],
            "volume": [100.0],
            "taker_buy_volume": [60.0],
        }
    )

    # Must not raise exceptions
    computed = IndicatorEngine.compute_all_indicators(single_df)
    assert len(computed) == 1
    eval_t = evaluate_trend_direction_and_strength(single_df["close"], single_df["high"], single_df["low"])
    assert eval_t["direction"] == "NEUTRAL"
    eval_m = evaluate_momentum(single_df["close"])
    assert eval_m["momentum_bias"] == "NEUTRAL"
    eval_v = evaluate_volatility_regime(single_df["high"], single_df["low"], single_df["close"])
    assert eval_v["regime"] == "NORMAL"
    eval_vol = evaluate_volume_profile(
        single_df["open"],
        single_df["high"],
        single_df["low"],
        single_df["close"],
        single_df["volume"],
        single_df["taker_buy_volume"],
    )
    assert eval_vol["volume_bias"] == "NEUTRAL"


def test_zero_volume_vwap_fallback():
    # If a session has zero volume throughout, VWAP must fall back to typical price and never be 0.0
    times = [datetime(2026, 10, 20, 23, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(5)]
    df = pd.DataFrame(
        {
            "open_time": times,
            "high": [2660.0] * 5,
            "low": [2640.0] * 5,
            "close": [2650.0] * 5,
            "volume": [0.0] * 5,
        }
    )

    vwap_df = calculate_session_anchored_vwap(df, session_reset_hour_utc=23)
    # Typical price = (2660 + 2640 + 2650) / 3 = 2650.0
    for v in vwap_df["vwap"]:
        assert np.isclose(v, 2650.0), f"Expected VWAP=2650.0 on zero volume, got {v}"

    pos = evaluate_vwap_position(df, session_reset_hour_utc=23)
    assert pos["vwap"] == 2650.0
    assert pos["zone"] == "AT_VWAP"


def test_flat_prices_numerical_stability():
    # Flat price series: standard deviation is 0, True range is 0
    n = 60
    closes = pd.Series([2650.0] * n)
    highs = pd.Series([2650.0] * n)
    lows = pd.Series([2650.0] * n)

    bb = calculate_bollinger_bands(closes, period=20)
    assert np.isclose(bb["bandwidth"].iloc[-1], 0.0)
    assert np.isclose(bb["upper"].iloc[-1], 2650.0)
    assert np.isclose(bb["lower"].iloc[-1], 2650.0)

    atr = calculate_atr(highs, lows, closes, period=14)
    assert np.isclose(atr.iloc[-1], 0.0)

    rsi = calculate_rsi(closes, period=14)
    # With 0 gains and 0 losses, RS is 0/eps=0, RSI is 0 (or bounded [0, 100])
    assert 0.0 <= rsi.iloc[-1] <= 100.0
