"""
Unit and edge-case tests for analytical_engine.structure.liquidity_sweeps.
"""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from analytical_engine.structure.liquidity_sweeps import (
    LiquiditySweepDetector,
    detect_liquidity_sweeps,
)
from analytical_engine.structure.pivots import PivotDetector


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
