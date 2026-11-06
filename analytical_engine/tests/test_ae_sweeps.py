"""
Unit and edge-case tests for analytical_engine.structure.liquidity_sweeps.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from analytical_engine.structure.liquidity_sweeps import (
    detect_liquidity_sweeps,
)


def test_ae_liquidity_sweep_detection():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 20
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing High at index 3: Peak High = 2670.0 (confirmed at bar 5 with window=2)
    highs[3] = 2670.0
    opens[3] = 2662.0
    closes[3] = 2665.0

    # Candle at index 8 sweeps index 3: High pierces to 2673.0, but Close rejects down to 2664.0
    highs[8] = 2673.0
    closes[8] = 2664.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    sweeps = detect_liquidity_sweeps(df, timeframe="1h", swing_window=2)
    assert len(sweeps) == 1
    assert sweeps[0].sweep_type == "SWEEP_HIGH"
    assert sweeps[0].swept_level == 2670.0
    assert sweeps[0].penetration_price == 2673.0
    assert sweeps[0].close_price == 2664.0
    assert sweeps[0].sweep_distance == 3.0
    assert sweeps[0].is_wick_reversal is True


def test_ae_liquidity_sweep_single_consumption():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 20
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[3] = 2670.0  # Swing high at 3

    # Candle 8 sweeps
    highs[8] = 2672.0
    closes[8] = 2660.0

    # Candle 9 pierces again (should NOT produce a second sweep on the same level)
    highs[9] = 2674.0
    closes[9] = 2662.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    sweeps = detect_liquidity_sweeps(df, timeframe="1h", swing_window=2)
    # Exactly one sweep recorded because the level is consumed upon the first sweep
    assert len(sweeps) == 1


def test_ae_liquidity_sweep_duplicate_levels_per_candle():
    """Verify that multiple co-located swing levels generate at most one sweep event per candle."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 20
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Equal highs at bar 3 and bar 7
    highs[3] = 2670.0
    highs[7] = 2670.0

    # Candle 12 sweeps 2670.0
    highs[12] = 2675.0
    closes[12] = 2665.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    sweeps = detect_liquidity_sweeps(df, timeframe="1h", swing_window=2)
    assert len(sweeps) == 1
    assert sweeps[0].swept_level == 2670.0
    assert sweeps[0].penetration_price == 2675.0


def test_ae_liquidity_sweep_adversarial_lookahead():
    """Adversarial test: Appending future data does not alter past detected liquidity sweeps."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[4] = 2672.0
    highs[10] = 2676.0
    closes[10] = 2668.0

    df_base = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    sweeps_base = detect_liquidity_sweeps(df_base, timeframe="1h", swing_window=2)
    assert len(sweeps_base) == 1

    # Append future shock
    future_times = [times[-1] + timedelta(hours=i + 1) for i in range(15)]
    df_future = pd.DataFrame({
        "open_time": future_times,
        "open": [3100.0] * 15,
        "high": [3150.0] * 15,
        "low": [3080.0] * 15,
        "close": [3120.0] * 15,
        "volume": [500.0] * 15,
    })
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    sweeps_shocked = detect_liquidity_sweeps(df_shocked, timeframe="1h", swing_window=2)
    assert len(sweeps_shocked) >= 1
    matched = [s for s in sweeps_shocked if s.confirmed_candle_time == sweeps_base[0].confirmed_candle_time][0]
    assert matched.swept_level == sweeps_base[0].swept_level
    assert matched.penetration_price == sweeps_base[0].penetration_price
    assert matched.close_price == sweeps_base[0].close_price

