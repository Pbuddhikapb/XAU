"""
Unit and edge-case tests for analytical_engine.structure.breakout_retest.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from analytical_engine.structure.breakout_retest import (
    detect_breakout_retests,
)


def test_ae_bullish_breakout_successful_retest():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 16
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing High at index 3: Peak High = 2670.0 (confirmed at bar 5)
    opens[3] = 2662.0
    highs[3] = 2670.0
    lows[3] = 2660.0
    closes[3] = 2668.0

    # Breakout at index 8: Close above 2670.0
    opens[8] = 2668.0
    highs[8] = 2682.0
    lows[8] = 2666.0
    closes[8] = 2680.0

    # Bars 9 and 10 stay above
    for k in (9, 10):
        opens[k] = 2680.0
        highs[k] = 2685.0
        lows[k] = 2676.0
        closes[k] = 2682.0

    # Retest at index 11: Low pulls back to 2670.5, Close rejects up to 2676.0
    opens[11] = 2682.0
    highs[11] = 2683.0
    lows[11] = 2670.5
    closes[11] = 2676.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2)
    assert len(events) >= 1
    assert events[0].direction == "BULLISH"
    assert events[0].level_price == 2670.0
    assert events[0].status == "SUCCESSFUL"
    assert events[0].retest_price == 2670.5


def test_ae_bearish_breakdown_successful_retest():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing Low at index 3: 2630.0 (confirmed at bar 5)
    opens[3] = 2635.0
    highs[3] = 2638.0
    lows[3] = 2630.0
    closes[3] = 2632.0

    # Breakdown at index 8: Close below 2630.0
    opens[8] = 2631.0
    highs[8] = 2632.0
    lows[8] = 2618.0
    closes[8] = 2620.0

    # Bar 9 stays below 2630
    opens[9] = 2620.0
    highs[9] = 2624.0
    lows[9] = 2615.0
    closes[9] = 2618.0

    # Retest at index 10: High pulls back to 2629.8, Close rejects down to 2624.0
    opens[10] = 2618.0
    highs[10] = 2629.8
    lows[10] = 2621.0
    closes[10] = 2624.0

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2)
    assert len(events) >= 1
    assert events[0].direction == "BEARISH"
    assert events[0].level_price == 2630.0
    assert events[0].status == "SUCCESSFUL"
    assert events[0].retest_price == 2629.8


def test_ae_breakout_retest_adversarial_lookahead():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 16
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[3] = 2670.0
    closes[3] = 2668.0

    highs[8] = 2682.0
    closes[8] = 2680.0

    for k in (9, 10):
        opens[k] = 2680.0
        highs[k] = 2685.0
        lows[k] = 2676.0
        closes[k] = 2682.0

    lows[11] = 2670.5
    closes[11] = 2676.0

    df_base = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })

    base_events = detect_breakout_retests(df_base, timeframe="1h", swing_window=2)
    assert len(base_events) >= 1

    # Append future shock
    future_times = [times[-1] + timedelta(hours=i + 1) for i in range(20)]
    df_future = pd.DataFrame({
        "open_time": future_times,
        "open": [3200.0] * 20,
        "high": [3250.0] * 20,
        "low": [3180.0] * 20,
        "close": [3220.0] * 20,
        "volume": [500.0] * 20,
    })
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    shocked_events = detect_breakout_retests(df_shocked, timeframe="1h", swing_window=2)
    assert len(shocked_events) >= 1

    matched = [e for e in shocked_events if e.level_pivot_time == base_events[0].level_pivot_time][0]
    assert matched.direction == base_events[0].direction
    assert matched.status == base_events[0].status
    assert matched.breakout_price == base_events[0].breakout_price
    assert matched.retest_price == base_events[0].retest_price
    assert matched.confirmed_time == base_events[0].confirmed_time

