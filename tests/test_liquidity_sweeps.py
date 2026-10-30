"""
Unit tests for Liquidity Sweep Detection Module.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.liquidity_sweeps import detect_liquidity_sweeps


def test_detect_sweep_high():
    # Swing high at index 4 (High = 2672, Close = 2670)
    # At index 10, candle wicks to 2676 (piercing 2672), but closes at 2668 (inside level)
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Index 4: Swing High
    opens[4] = 2665.0
    highs[4] = 2672.0
    lows[4] = 2660.0
    closes[4] = 2670.0

    # Index 10: Sweep High
    opens[10] = 2665.0
    highs[10] = 2676.0  # pierces 2672
    lows[10] = 2662.0
    closes[10] = 2668.0  # closes <= 2672

    df = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )

    sweeps = detect_liquidity_sweeps(df, timeframe="1h", swing_window=2)
    assert len(sweeps) >= 1
    sweep = sweeps[0]
    assert sweep.sweep_type == "SWEEP_HIGH"
    assert sweep.swept_level == 2672.0
    assert sweep.penetration_price == 2676.0
    assert sweep.close_price == 2668.0
    assert sweep.sweep_distance == 4.0


def test_confirmed_breakout_not_a_sweep():
    # If the candle wicks to 2676 AND closes at 2675 (above 2672), it is NOT a sweep!
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Index 4: Swing High
    highs[4] = 2672.0
    closes[4] = 2670.0

    # Index 10: Breakout Close above
    highs[10] = 2676.0
    closes[10] = 2675.0  # > 2672

    df = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )

    sweeps = detect_liquidity_sweeps(df, timeframe="1h", swing_window=2)
    assert sweeps == []
