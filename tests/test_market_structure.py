"""
Unit tests for Market Structure Module (HH, HL, LH, LL, BOS, CHoCH).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.structure.market_structure import analyze_market_structure


def test_uptrend_hh_hl_and_bos():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    # First swing high at index 4 (price 2660), swing low at index 8 (price 2645)
    # Second swing high at index 14 (price 2680), swing low at index 18 (price 2665)
    # Breakout close at index 22 (price 2695)
    prices = [
        2640,
        2648,
        2655,
        2658,
        2660,
        2653,
        2649,
        2646,
        2645,
        2652,
        2662,
        2670,
        2676,
        2679,
        2680,
        2674,
        2669,
        2666,
        2665,
        2675,
        2685,
        2690,
        2695,
        2692,
        2688,
    ]
    prices_f = [float(p) for p in prices]
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices_f,
            "high": [p + 2.0 for p in prices_f],
            "low": [p - 2.0 for p in prices_f],
            "close": prices_f,
            "volume": [100.0] * n,
        }
    )

    events, trend = analyze_market_structure(df, timeframe="1h", swing_window=2)
    assert trend == "BULLISH"
    event_types = [e.event_type for e in events]
    assert "HH" in event_types or "HL" in event_types
    assert "BOS_BULL" in event_types


def test_trend_reversal_choch():
    # Sequence starting bullish, then breaking below the Higher Low (Bearish CHoCH)
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 25
    times = [base_time + timedelta(hours=i) for i in range(n)]

    # Peak 1 at index 4 (2670), Low at index 8 (2650), Peak 2 at index 12 (2680)
    # Then steep drop breaking 2650 at index 16 (close 2635)
    prices = [
        2650,
        2658,
        2665,
        2668,
        2670,
        2662,
        2655,
        2651,
        2650,
        2660,
        2672,
        2678,
        2680,
        2665,
        2652,
        2642,
        2635,
        2630,
        2634,
        2638,
        2632,
        2628,
        2625,
        2622,
        2620,
    ]
    prices_f = [float(p) for p in prices]
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices_f,
            "high": [p + 2.0 for p in prices_f],
            "low": [p - 2.0 for p in prices_f],
            "close": prices_f,
            "volume": [100.0] * n,
        }
    )

    events, trend = analyze_market_structure(df, timeframe="1h", swing_window=2)
    event_types = [e.event_type for e in events]
    assert "CHOCH_BEAR" in event_types
    assert trend == "BEARISH"
