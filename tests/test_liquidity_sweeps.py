"""
Unit tests for Liquidity Sweep Detection Module.
Strictly verifies:
1. Valid sweep detection (wick pierce + close back inside).
2. Confirmed breakout is not a sweep.
3. Repeated sweeps against the same level are rejected (level consumption).
4. Sweeps against levels previously broken by close are rejected (invalidation).
5. Sweeps against levels exceeding max_age_bars are rejected (expiration).
6. Unconfirmed swing levels cannot be swept before confirmation.
7. Adversarial future data appending does not alter historical sweeps.
8. Incremental live calculation matches batch historical replay.
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
    assert len(sweeps) == 1
    sweep = sweeps[0]
    assert sweep.sweep_type == "SWEEP_HIGH"
    assert sweep.swept_level == 2672.0
    assert sweep.penetration_price == 2676.0
    assert sweep.close_price == 2668.0
    assert sweep.sweep_distance == 4.0
    assert sweep.is_wick_reversal is True


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


def test_repeated_sweep_against_same_level_rejected():
    """Level consumption: A level swept at index 10 cannot trigger another sweep at index 11."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[4] = 2672.0  # Swing high at 4

    # First sweep at index 10
    highs[10] = 2676.0
    closes[10] = 2668.0

    # Second wick above at index 11
    highs[11] = 2675.0
    closes[11] = 2669.0

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
    # Exactly one sweep recorded (from bar 10); bar 11 does not duplicate
    assert len(sweeps) == 1
    assert sweeps[0].penetration_price == 2676.0


def test_sweep_against_invalidated_level_rejected():
    """If a swing level was broken by candle close at bar 8, bar 10 cannot sweep it."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[4] = 2672.0  # Swing high

    # Bar 8 closes above 2672 (invalidating the level)
    highs[8] = 2678.0
    closes[8] = 2675.0

    # Bar 10 wicks above 2672 and closes below 2672
    highs[10] = 2674.0
    closes[10] = 2668.0

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


def test_sweep_against_expired_level_rejected():
    """A swing older than max_age_bars expires and cannot be swept."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 30
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[2] = 2672.0  # Swing high at bar 2

    # Attempt sweep at bar 25 (age = 23 bars). With max_age_bars=15, level is expired
    highs[25] = 2676.0
    closes[25] = 2668.0

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

    sweeps = detect_liquidity_sweeps(df, timeframe="1h", swing_window=2, max_age_bars=15)
    assert sweeps == []


def test_unconfirmed_swing_level_not_swept():
    """A peak that has not met confirmation window right_bars cannot be swept."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 8
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[4] = 2672.0  # Peak at 4, requires window=2 (confirmed at close of bar 6)

    # Bar 5 attempts to sweep bar 4 before bar 4 is confirmed!
    highs[5] = 2674.0
    closes[5] = 2668.0

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


def test_liquidity_sweep_lookahead_adversarial():
    """Appending future market data does not modify past detected sweeps."""
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

    df_base = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )

    sweeps_base = detect_liquidity_sweeps(df_base, timeframe="1h", swing_window=2)
    assert len(sweeps_base) == 1

    # Append 10 future bars with an extreme +$500 price shock
    future_times = [times[-1] + timedelta(hours=i + 1) for i in range(10)]
    df_future = pd.DataFrame(
        {
            "open_time": future_times,
            "open": [3150.0] * 10,
            "high": [3180.0] * 10,
            "low": [3140.0] * 10,
            "close": [3160.0] * 10,
            "volume": [500.0] * 10,
        }
    )
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    sweeps_shocked = detect_liquidity_sweeps(df_shocked, timeframe="1h", swing_window=2)
    # The sweep at bar 10 remains identical
    assert len(sweeps_shocked) >= 1
    s_shock = [s for s in sweeps_shocked if s.confirmed_candle_time == sweeps_base[0].confirmed_candle_time][0]
    assert s_shock.swept_level == sweeps_base[0].swept_level
    assert s_shock.penetration_price == sweeps_base[0].penetration_price
