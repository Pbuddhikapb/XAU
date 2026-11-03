"""
Unit tests for Breakout and Retest Analytical Event Detection.
Strictly verifies:
1. Bullish breakout with successful retest rejection.
2. Bearish breakdown with successful retest rejection.
3. Failed breakout where retest candle closes back inside prior range.
4. Pending retest awaiting resolution within validity window.
5. Expired retest where lookback window elapses without touch.
6. Duplicate event prevention for broken levels.
7. Zero lookahead bias under adversarial future price movements.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.breakout_retest import detect_breakout_retests


def test_bullish_breakout_successful_retest():
    """Verify bullish breakout at bar 8 and successful retest rejection at bar 11."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 16
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing High at index 3: Peak High = 2670.0 (confirmed with window=2 at bar 5)
    opens[3] = 2662.0
    highs[3] = 2670.0
    lows[3] = 2660.0
    closes[3] = 2668.0

    # Breakout at index 8: Candle closes above 2670.0
    opens[8] = 2668.0
    highs[8] = 2682.0
    lows[8] = 2666.0
    closes[8] = 2680.0

    # Bars 9 and 10 stay above the breakout level (no touch yet)
    for k in (9, 10):
        opens[k] = 2680.0
        highs[k] = 2685.0
        lows[k] = 2676.0  # stays above 2670 + tolerance
        closes[k] = 2682.0

    # Retest at index 11: Low pulls back to touch 2670.0 zone (Low = 2670.5), but Close rejects up to 2676.0
    opens[11] = 2682.0
    highs[11] = 2683.0
    lows[11] = 2670.5  # touches 2670 zone
    closes[11] = 2676.0  # holds above 2670

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

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2)
    assert len(events) == 1
    evt = events[0]
    assert evt.direction == "BULLISH"
    assert evt.level_price == 2670.0
    assert evt.status == "SUCCESSFUL"
    assert evt.breakout_price == 2680.0
    assert evt.retest_price == 2670.5
    assert evt.details["breakout_bar_index"] == 8
    assert evt.details["retest_bar_index"] == 11


def test_bearish_breakdown_successful_retest():
    """Verify bearish breakdown at bar 8 and successful retest rejection at bar 10."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing Low at index 3: Trough Low = 2630.0 (confirmed at bar 5)
    opens[3] = 2635.0
    highs[3] = 2638.0
    lows[3] = 2630.0
    closes[3] = 2632.0

    # Breakdown at index 8: Candle closes below 2630.0
    opens[8] = 2631.0
    highs[8] = 2632.0
    lows[8] = 2618.0
    closes[8] = 2620.0

    # Bar 9 stays below 2630 without touching retest zone
    opens[9] = 2620.0
    highs[9] = 2624.0  # < 2630 - tolerance
    lows[9] = 2615.0
    closes[9] = 2618.0

    # Retest at index 10: High pulls back to 2629.8, Close rejects down to 2624.0
    opens[10] = 2618.0
    highs[10] = 2629.8  # touches 2630 zone
    lows[10] = 2621.0
    closes[10] = 2624.0  # holds below 2630

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

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2)
    assert len(events) == 1
    evt = events[0]
    assert evt.direction == "BEARISH"
    assert evt.level_price == 2630.0
    assert evt.status == "SUCCESSFUL"
    assert evt.breakout_price == 2620.0
    assert evt.retest_price == 2629.8
    assert evt.details["breakout_bar_index"] == 8
    assert evt.details["retest_bar_index"] == 10


def test_failed_breakout_retest():
    """Verify failed breakout where retest candle closes back inside prior range."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing High at index 3: 2670.0
    highs[3] = 2670.0
    closes[3] = 2668.0

    # Breakout at index 7: Close = 2678.0
    highs[7] = 2680.0
    closes[7] = 2678.0

    # Bar 8 holds above
    opens[8] = 2678.0
    highs[8] = 2682.0
    lows[8] = 2676.0
    closes[8] = 2680.0

    # Retest at index 9 closes back below 2670 (Close = 2662.0)
    opens[9] = 2680.0
    highs[9] = 2681.0
    lows[9] = 2660.0
    closes[9] = 2662.0  # < 2670 -> FAILED

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

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2)
    assert len(events) == 1
    evt = events[0]
    assert evt.status == "FAILED"
    assert evt.details["failure_bar_index"] == 9


def test_pending_breakout_retest():
    """Verify that a recent breakout with no subsequent touch is marked PENDING."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 10
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[3] = 2670.0

    # Breakout on the last candle (index 9)
    highs[9] = 2685.0
    closes[9] = 2682.0

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

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2)
    assert len(events) == 1
    assert events[0].status == "PENDING"
    assert events[0].retest_time is None


def test_expired_breakout_retest():
    """Verify that a breakout exceeding max_retest_bars without touch is marked EXPIRED."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[2] = 2670.0  # Swing high at 2

    # Breakout at index 5: shoots up and stays up (no pullback)
    for k in range(5, n):
        opens[k] = 2700.0
        highs[k] = 2720.0
        lows[k] = 2695.0
        closes[k] = 2710.0

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

    events = detect_breakout_retests(df, timeframe="1h", swing_window=2, max_retest_bars=10)
    assert len(events) == 1
    assert events[0].status == "EXPIRED"


def test_breakout_retest_adversarial_lookahead():
    """Adversarial test: Appending future data does not alter past completed retests."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    highs[3] = 2670.0
    highs[8] = 2682.0
    closes[8] = 2680.0  # Breakout

    for k in (9, 10):
        opens[k] = 2680.0
        highs[k] = 2685.0
        lows[k] = 2676.0
        closes[k] = 2682.0

    lows[11] = 2670.5
    closes[11] = 2676.0  # Retest

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

    base_events = detect_breakout_retests(df_base, timeframe="1h", swing_window=2)
    assert len(base_events) == 1
    assert base_events[0].status == "SUCCESSFUL"

    # Append 15 future bars with extreme volatility shock
    future_times = [times[-1] + timedelta(hours=i + 1) for i in range(15)]
    df_future = pd.DataFrame(
        {
            "open_time": future_times,
            "open": [3200.0] * 15,
            "high": [3250.0] * 15,
            "low": [3180.0] * 15,
            "close": [3220.0] * 15,
            "volume": [500.0] * 15,
        }
    )
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    shocked_events = detect_breakout_retests(df_shocked, timeframe="1h", swing_window=2)
    assert len(shocked_events) >= 1
    # Match the past event
    matched = [e for e in shocked_events if e.level_time == base_events[0].level_time][0]
    assert matched.status == base_events[0].status
    assert matched.breakout_price == base_events[0].breakout_price
    assert matched.retest_price == base_events[0].retest_price
    assert matched.confirmed_time == base_events[0].confirmed_time
