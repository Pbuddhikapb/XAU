"""
Unit tests for Price Action Patterns (Rejections, Engulfing).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.price_action import (
    detect_breakout_retests,
    detect_price_action_patterns,
)


def test_rejection_pinbar():
    # Construct a strong bullish rejection pinbar (long lower wick)
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time, base_time + timedelta(hours=1)]

    # Candle 1: Open=2650, High=2652, Low=2635, Close=2651
    # Total range = 17. Lower wick = 2650 - 2635 = 15. Wick ratio = 15 / 17 = 88.2%
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": [2650.0, 2650.0],
            "high": [2655.0, 2652.0],
            "low": [2645.0, 2635.0],
            "close": [2650.0, 2651.0],
            "volume": [100.0, 100.0],
        }
    )

    patterns = detect_price_action_patterns(df)
    types = [p.pattern_type for p in patterns]
    assert "REJECTION_BULL" in types


def test_bullish_engulfing():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time, base_time + timedelta(hours=1)]

    # Candle 0: Bearish (Open=2655, Close=2645)
    # Candle 1: Bullish engulfing (Open=2644, High=2662, Low=2642, Close=2660)
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": [2655.0, 2644.0],
            "high": [2656.0, 2662.0],
            "low": [2644.0, 2642.0],
            "close": [2645.0, 2660.0],
            "volume": [100.0, 150.0],
        }
    )

    patterns = detect_price_action_patterns(df)
    types = [p.pattern_type for p in patterns]
    assert "ENGULFING_BULL" in types


def test_causal_breakout_and_retest_bullish():
    """Verify causal detection of a bullish breakout with successful retest rejection."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 16
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Confirmed Swing High at index 3: High = 2670.0 (confirmed at bar 5 with window=2)
    opens[3] = 2662.0
    highs[3] = 2670.0
    lows[3] = 2660.0
    closes[3] = 2668.0

    # Breakout candle at index 8: Closes beyond confirmed level 2670.0
    opens[8] = 2668.0
    highs[8] = 2682.0
    lows[8] = 2666.0
    closes[8] = 2680.0

    # Bars 9 and 10 stay above the breakout level
    for k in (9, 10):
        opens[k] = 2680.0
        highs[k] = 2685.0
        lows[k] = 2676.0
        closes[k] = 2682.0

    # Retest at index 11: Low pulls back into 2670 zone (2670.5), Close rejects up to 2676.0
    opens[11] = 2682.0
    highs[11] = 2683.0
    lows[11] = 2670.5
    closes[11] = 2676.0

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

    patterns = detect_price_action_patterns(df, swing_window=2)
    br_patterns = [p for p in patterns if p.pattern_type == "BREAKOUT_RETEST"]

    assert len(br_patterns) == 1
    p = br_patterns[0]
    assert p.pattern_type == "BREAKOUT_RETEST"
    assert p.price == 2670.5
    assert p.details["direction"] == "BULLISH"
    assert p.details["level_price"] == 2670.0
    assert p.details["breakout_price"] == 2680.0
    assert p.details["status"] == "SUCCESSFUL"
    # Confirmation time matches the close of retest candle 11
    assert p.candle_time == times[11] + timedelta(hours=1)


def test_causal_breakout_and_retest_bearish():
    """Verify causal detection of a bearish breakdown with successful retest rejection."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 15
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Confirmed Swing Low at index 3: Low = 2630.0 (confirmed at bar 5 with window=2)
    opens[3] = 2635.0
    highs[3] = 2638.0
    lows[3] = 2630.0
    closes[3] = 2632.0

    # Breakdown at index 8: Candle closes below 2630.0
    opens[8] = 2631.0
    highs[8] = 2632.0
    lows[8] = 2618.0
    closes[8] = 2620.0

    # Bar 9 stays below 2630
    opens[9] = 2620.0
    highs[9] = 2624.0
    lows[9] = 2615.0
    closes[9] = 2618.0

    # Retest at index 10: High pulls back into 2630 zone (2629.8), Close rejects down to 2624.0
    opens[10] = 2618.0
    highs[10] = 2629.8
    lows[10] = 2621.0
    closes[10] = 2624.0

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

    patterns = detect_breakout_retests(df, swing_window=2)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.pattern_type == "BREAKOUT_RETEST"
    assert p.details["direction"] == "BEARISH"
    assert p.details["level_price"] == 2630.0
    assert p.details["breakout_price"] == 2620.0
    assert p.price == 2629.8
    assert p.details["status"] == "SUCCESSFUL"


def test_price_action_adversarial_lookahead():
    """Adversarial test: Appending future data does not alter past detected price action patterns."""
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 16
    times = [base_time + timedelta(hours=i) for i in range(n)]

    opens = [2650.0] * n
    highs = [2655.0] * n
    lows = [2645.0] * n
    closes = [2650.0] * n

    # Swing High at index 3: Peak High = 2670.0
    highs[3] = 2670.0
    closes[3] = 2668.0

    # Breakout at index 8: Close = 2680.0
    highs[8] = 2682.0
    closes[8] = 2680.0

    # Bars 9 and 10 stay above the breakout level
    for k in (9, 10):
        opens[k] = 2680.0
        highs[k] = 2685.0
        lows[k] = 2676.0
        closes[k] = 2682.0

    # Retest at index 11: Low = 2670.5, Close = 2676.0
    opens[11] = 2682.0
    highs[11] = 2683.0
    lows[11] = 2670.5
    closes[11] = 2676.0

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

    base_patterns = detect_price_action_patterns(df_base, swing_window=2)
    assert any(p.pattern_type == "BREAKOUT_RETEST" for p in base_patterns)
    cutoff_time = times[-1] + timedelta(hours=1)

    # Append 25 future bars with extreme volatility and price shocks
    future_times = [times[-1] + timedelta(hours=i + 1) for i in range(25)]
    future_p = [3200.0 + (i * 10) for i in range(25)]
    df_future = pd.DataFrame(
        {
            "open_time": future_times,
            "open": future_p,
            "high": [p + 20.0 for p in future_p],
            "low": [p - 20.0 for p in future_p],
            "close": future_p,
            "volume": [1000.0] * 25,
        }
    )
    df_shocked = pd.concat([df_base, df_future], ignore_index=True)

    shocked_patterns = detect_price_action_patterns(df_shocked, swing_window=2)

    # Filter shocked patterns up to cutoff_time
    historical_shocked = [p for p in shocked_patterns if p.candle_time <= cutoff_time]

    assert len(base_patterns) == len(historical_shocked)
    for bp, sp in zip(base_patterns, historical_shocked, strict=False):
        assert bp.pattern_type == sp.pattern_type
        assert bp.candle_time == sp.candle_time
        assert bp.price == sp.price
        assert bp.strength == sp.strength
        assert bp.details == sp.details

