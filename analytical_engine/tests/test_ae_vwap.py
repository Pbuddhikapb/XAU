"""
Tests for Volume-Weighted Average Price (VWAP) calculation engine.
"""

from datetime import UTC, datetime

import pandas as pd
import pytest

from analytical_engine.indicators.vwap import calculate_daily_vwap


def test_vwap_intraday_accumulation():
    """Verify VWAP mathematical formula: sum(TypicalPrice * Volume) / sum(Volume)."""
    # Create 3 candles on the same UTC day
    # Candle 0: H=10, L=8, C=9 -> TP = 9.0, Vol = 100 -> CumVP = 900, CumVol = 100 -> VWAP = 9.0
    # Candle 1: H=12, L=10, C=11 -> TP = 11.0, Vol = 200 -> CumVP = 3100, CumVol = 300 -> VWAP = 3100/300 = 10.333
    records = [
        {
            "open_time": datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
            "high": 10.0,
            "low": 8.0,
            "close": 9.0,
            "volume": 100.0,
        },
        {
            "open_time": datetime(2026, 10, 30, 8, 1, tzinfo=UTC),
            "high": 12.0,
            "low": 10.0,
            "close": 11.0,
            "volume": 200.0,
        },
    ]
    df = pd.DataFrame(records)
    res = calculate_daily_vwap(df)

    assert pytest.approx(res["vwap"][0], 1e-9) == 9.0
    assert pytest.approx(res["vwap"][1], 1e-6) == (3100.0 / 300.0)
    assert res["cum_volume"][1] == 300.0


def test_vwap_daily_reset():
    """Verify VWAP accumulator resets at 00:00:00 UTC day boundary."""
    records = [
        # Day 1: 2026-10-29 23:59 UTC
        {
            "open_time": datetime(2026, 10, 29, 23, 59, tzinfo=UTC),
            "high": 20.0,
            "low": 20.0,
            "close": 20.0,
            "volume": 1000.0,
        },
        # Day 2: 2026-10-30 00:00 UTC -> Must reset
        {
            "open_time": datetime(2026, 10, 30, 0, 0, tzinfo=UTC),
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 50.0,
        },
    ]
    df = pd.DataFrame(records)
    res = calculate_daily_vwap(df)

    # Day 1 end: VWAP = 20.0, CumVol = 1000
    assert res["vwap"][0] == 20.0
    assert res["cum_volume"][0] == 1000.0

    # Day 2 start: accumulator reset -> VWAP = 10.0, CumVol = 50.0
    assert res["vwap"][1] == 10.0
    assert res["cum_volume"][1] == 50.0
    assert res["anchor_time"][1] == datetime(2026, 10, 30, 0, 0, 0, tzinfo=UTC)
