"""
MANDATORY TEMPORAL INTEGRITY AND LOOKAHEAD TESTS.
Verifies that no calculation leaks future information or repaints past values.
"""

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from analytical_engine.indicators.momentum import calculate_rsi
from analytical_engine.indicators.moving_averages import calculate_ema_series
from analytical_engine.indicators.volatility import calculate_atr, calculate_bollinger_bands
from analytical_engine.multi_timeframe.aggregation import CandleAggregator
from analytical_engine.multi_timeframe.alignment import MultiTimeframeAligner
from analytical_engine.structure.divergence import DivergenceDetector
from analytical_engine.structure.pivots import PivotDetector


def create_base_dataset(n: int = 100) -> pd.DataFrame:
    records = []
    base_epoch = 1765440000
    for i in range(n):
        records.append({
            "open_time": datetime.fromtimestamp(base_epoch + i * 60, tz=UTC),
            "close_time": datetime.fromtimestamp(base_epoch + (i + 1) * 60, tz=UTC),
            "open": 4000.0 + i * 0.5,
            "high": 4005.0 + i * 0.5,
            "low": 3995.0 + i * 0.5,
            "close": 4002.0 + i * 0.5,
            "volume": 100.0,
        })
    df = pd.DataFrame(records)
    df.attrs["timeframe"] = "1m"
    return df


def test_future_data_mutation_does_not_affect_past_indicators():
    """
    TEST 1: Mutating future candles must NOT alter any indicator values calculated in the past.
    """
    df1 = create_base_dataset(100)
    df2 = create_base_dataset(100)

    # In df2, drastically corrupt bars 80 to 99 (huge price shock to 10,000)
    for i in range(80, 100):
        df2.loc[i, "close"] = 10000.0 + i
        df2.loc[i, "high"] = 10010.0 + i
        df2.loc[i, "low"] = 9990.0 + i

    # Compute indicators on both datasets
    rsi1 = calculate_rsi(df1["close"], period=14)
    rsi2 = calculate_rsi(df2["close"], period=14)

    ema1 = calculate_ema_series(df1["close"], period=20)
    ema2 = calculate_ema_series(df2["close"], period=20)

    bb1 = calculate_bollinger_bands(df1["close"], period=20)
    bb2 = calculate_bollinger_bands(df2["close"], period=20)

    atr1 = calculate_atr(df1["high"], df1["low"], df1["close"], period=14)
    atr2 = calculate_atr(df2["high"], df2["low"], df2["close"], period=14)

    # All values for bars 0 to 79 MUST be strictly bit-identical
    assert np.allclose(rsi1[:80], rsi2[:80], equal_nan=True)
    assert np.allclose(ema1[:80], ema2[:80], equal_nan=True)
    assert np.allclose(bb1["middle"][:80], bb2["middle"][:80], equal_nan=True)
    assert np.allclose(bb1["upper"][:80], bb2["upper"][:80], equal_nan=True)
    assert np.allclose(atr1[:80], atr2[:80], equal_nan=True)


def test_incremental_streaming_matches_batch_calculation():
    """
    TEST 2: Incremental step-by-step indicator updates produce identical values to batch calculation.
    """
    df = create_base_dataset(50)
    close_vals = df["close"].values

    # Batch EMA(10)
    batch_ema = calculate_ema_series(close_vals, period=10)

    # Incremental EMA: calculate on growing slices
    inc_ema = []
    for length in range(1, len(close_vals) + 1):
        slice_ema = calculate_ema_series(close_vals[:length], period=10)
        inc_ema.append(slice_ema[-1])

    inc_arr = np.array(inc_ema)
    assert np.allclose(batch_ema, inc_arr, equal_nan=True)


def test_unconfirmed_pivot_never_exposed_prematurely():
    """
    TEST 3: An unconfirmed pivot is never exposed before its right shoulder has completed.
    """
    df = create_base_dataset(30)
    # Create potential swing high at Bar 15
    df.loc[15, "high"] = 5000.0

    detector = PivotDetector(left_bars=2, right_bars=2)

    # If we only have data up to bar 15, bar 15 CANNOT be confirmed
    pivots_at_15 = detector.find_pivots(df.iloc[:16])
    assert not any(p.pivot_price == 5000.0 for p in pivots_at_15)

    # Even with data up to bar 16 (1 right shoulder bar), still unconfirmed
    pivots_at_16 = detector.find_pivots(df.iloc[:17])
    assert not any(p.pivot_price == 5000.0 for p in pivots_at_16)

    # Only when bar 17 closes (2 right shoulder bars) does bar 15 become confirmed
    pivots_at_17 = detector.find_pivots(df.iloc[:18])
    confirmed_5000 = [p for p in pivots_at_17 if p.pivot_price == 5000.0]
    assert len(confirmed_5000) == 1
    # Check confirmation timestamp corresponds to bar 17's close time
    assert confirmed_5000[0].confirmation_time == df.loc[17, "close_time"]


def test_divergence_never_available_before_second_pivot_confirmed():
    """
    TEST 4: Divergence availability timestamp strictly equals second pivot confirmation time.
    """
    # Create synthetic divergence data
    df = create_base_dataset(40)
    df.loc[10, "low"] = 3900.0  # Pivot 1
    df.loc[25, "low"] = 3850.0  # Pivot 2 (Lower Low)

    rsi = np.full(40, 50.0)
    rsi[10] = 30.0
    rsi[25] = 40.0  # Higher Low -> Regular Bullish Div

    detector = DivergenceDetector(min_bars_separation=5, max_bars_separation=20)
    # Using right_bars=2, Pivot 2 (at idx 25) confirms at idx 27 close
    divs = detector.detect_divergences(df, rsi, indicator_name="RSI", left_bars=2, right_bars=2)

    assert len(divs) >= 1
    d = divs[0]
    # Confirmation time MUST be bar 27's close time
    expected_conf = df.loc[27, "close_time"]
    assert d.confirmation_time == expected_conf


def test_htf_candle_not_exposed_before_interval_close():
    """
    TEST 5: Higher-timeframe indicators are strictly unmapped until the higher bar closes.
    """
    df_1m = create_base_dataset(65)

    agg_1h = CandleAggregator(target_timeframe="1h", require_full_bars=True)
    df_1h = agg_1h.aggregate(df_1m)
    df_1h["mock_val"] = 999.0

    agg_5m = CandleAggregator(target_timeframe="5m", require_full_bars=True)
    df_5m = agg_5m.aggregate(df_1m)

    aligner = MultiTimeframeAligner(evaluation_point="BAR_CLOSE")
    aligned = aligner.align(df_5m, htf_data={"1h": df_1h})

    # The 1h candle closes at 60 minutes
    # All 5m candles closing before 60 minutes must have NaN for 1h_mock_val
    for i in range(len(aligned)):
        c_close = aligned.loc[i, "close_time"]
        if c_close < df_1h.loc[0, "close_time"]:
            assert pd.isna(aligned.loc[i, "1h_mock_val"])
        else:
            assert aligned.loc[i, "1h_mock_val"] == 999.0
