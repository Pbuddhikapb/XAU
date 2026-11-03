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
