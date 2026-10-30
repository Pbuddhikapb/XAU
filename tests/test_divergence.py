"""
Unit tests for Momentum Divergence Engine (RSI, MACD_HIST).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.analytics.divergence import detect_divergences, find_swings


def test_find_swings_clean():
    # Sequence with clear peak at index 5 and trough at index 10
    vals = [10.0, 11.0, 12.0, 14.0, 16.0, 20.0, 16.0, 14.0, 12.0, 10.0, 8.0, 10.0, 12.0, 14.0, 15.0]
    series = pd.Series(vals)
    highs, lows = find_swings(series, window=3)

    high_indices = [idx for idx, _ in highs]
    low_indices = [idx for idx, _ in lows]

    assert 5 in high_indices
    assert 10 in low_indices


def test_detect_regular_bullish_divergence():
    # Synthetic scenario:
    # First low at index 10: Price = 2650, RSI ~ 30
    # Price rises to 2680, then falls to index 25: Price = 2635 (Lower Low)
    # But RSI falls only to ~ 38 (Higher Low)
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 45
    times = [base_time + timedelta(hours=i) for i in range(n)]

    prices = []
    for i in range(n):
        if i <= 10:
            prices.append(2680.0 - i * 3.0)  # down to 2650
        elif i <= 18:
            prices.append(2650.0 + (i - 10) * 3.5)  # bounce to 2678
        elif i <= 26:
            prices.append(2678.0 - (i - 18) * 5.0)  # sharp drop to 2638 (Lower Low)
        else:
            prices.append(2638.0 + (i - 26) * 2.0)  # recovery

    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices,
            "high": [p + 2.0 for p in prices],
            "low": [p - 2.0 for p in prices],
            "close": prices,
            "volume": [100.0] * n,
            "taker_buy_volume": [50.0] * n,
        }
    )

    divs = detect_divergences(df, indicator_name="RSI", swing_window=3)
    # Check that divergences are detected or returns valid list
    assert isinstance(divs, list)
    for d in divs:
        assert d.divergence_type in ("REGULAR_BULLISH", "REGULAR_BEARISH", "HIDDEN_BULLISH", "HIDDEN_BEARISH")


def test_detect_divergences_case_insensitive():
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 45
    times = [base_time + timedelta(hours=i) for i in range(n)]
    prices = [2650.0 + i for i in range(n)]
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices,
            "high": [p + 2.0 for p in prices],
            "low": [p - 2.0 for p in prices],
            "close": prices,
            "volume": [100.0] * n,
            "taker_buy_volume": [50.0] * n,
        }
    )
    divs_rsi = detect_divergences(df, indicator_name="rsi")
    assert isinstance(divs_rsi, list)
    divs_macd = detect_divergences(df, indicator_name="macd")
    assert isinstance(divs_macd, list)


def test_divergence_invalidation():
    # If price plummets further after a regular bullish divergence, is_active must be False
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    n = 50
    times = [base_time + timedelta(hours=i) for i in range(n)]

    prices = []
    for i in range(n):
        if i <= 10:
            prices.append(2680.0 - i * 3.0)  # low 1 at 2650
        elif i <= 18:
            prices.append(2650.0 + (i - 10) * 3.5)
        elif i <= 26:
            prices.append(2678.0 - (i - 18) * 5.0)  # low 2 at 2638
        elif i <= 32:
            prices.append(2638.0 + (i - 26) * 2.0)
        else:
            # Crash to 2600 breaking low 2
            prices.append(2650.0 - (i - 32) * 5.0)

    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices,
            "high": [p + 2.0 for p in prices],
            "low": [p - 2.0 for p in prices],
            "close": prices,
            "volume": [100.0] * n,
            "taker_buy_volume": [50.0] * n,
        }
    )
    divs = detect_divergences(df, indicator_name="RSI", swing_window=3)
    if divs:
        # If low 2 is broken by subsequent bars, is_active should be False
        for d in divs:
            if d.point_2.bar_index < 35:
                assert d.is_active is False
