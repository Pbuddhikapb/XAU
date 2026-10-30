"""
Unit tests for CandleValidator.
Tests OHLC invariant enforcement, volume checks, duplicate detection, and gap detection.
"""

import pandas as pd

from backend.data.candle_validator import CandleValidator


def test_valid_candle():
    candle = {
        "open": 4000.0,
        "high": 4010.0,
        "low": 3995.0,
        "close": 4005.0,
        "volume": 100.0,
        "taker_buy_volume": 60.0,
    }
    is_valid, err = CandleValidator.validate_single_candle(candle)
    assert is_valid is True
    assert err is None


def test_invalid_high():
    candle = {
        "open": 4000.0,
        "high": 3999.0,  # High less than open
        "low": 3990.0,
        "close": 3995.0,
        "volume": 100.0,
        "taker_buy_volume": 50.0,
    }
    is_valid, err = CandleValidator.validate_single_candle(candle)
    assert is_valid is False
    assert "High price" in err


def test_invalid_low():
    candle = {
        "open": 4000.0,
        "high": 4010.0,
        "low": 4005.0,  # Low higher than open
        "close": 4008.0,
        "volume": 100.0,
        "taker_buy_volume": 50.0,
    }
    is_valid, err = CandleValidator.validate_single_candle(candle)
    assert is_valid is False
    assert "Low price" in err


def test_negative_price():
    candle = {
        "open": -4000.0,
        "high": 4010.0,
        "low": 3990.0,
        "close": 4005.0,
        "volume": 100.0,
    }
    is_valid, err = CandleValidator.validate_single_candle(candle)
    assert is_valid is False
    assert "Non-positive price" in err


def test_taker_volume_exceeds_total():
    candle = {
        "open": 4000.0,
        "high": 4010.0,
        "low": 3990.0,
        "close": 4005.0,
        "volume": 100.0,
        "taker_buy_volume": 150.0,  # Impossible
    }
    is_valid, err = CandleValidator.validate_single_candle(candle)
    assert is_valid is False
    assert "Taker buy volume" in err


def test_gap_and_duplicate_detection():
    # 5 contiguous 1m bars
    times = pd.date_range("2026-10-30 10:00:00", periods=5, freq="1min", tz="UTC")
    df = pd.DataFrame({"open_time": times})

    res = CandleValidator.find_gaps_and_duplicates(df, timeframe="1m")
    assert res["is_clean"] is True
    assert res["duplicates_count"] == 0
    assert res["gaps_count"] == 0

    # Introduce a duplicate
    df_dup = pd.concat([df, df.iloc[[2]]], ignore_index=True)
    res_dup = CandleValidator.find_gaps_and_duplicates(df_dup, timeframe="1m")
    assert res_dup["is_clean"] is False
    assert res_dup["duplicates_count"] == 1

    # Introduce a 3-minute gap
    gap_times = [
        pd.Timestamp("2026-10-30 10:00:00", tz="UTC"),
        pd.Timestamp("2026-10-30 10:01:00", tz="UTC"),
        pd.Timestamp("2026-10-30 10:05:00", tz="UTC"),  # 3 missing bars
    ]
    df_gap = pd.DataFrame({"open_time": gap_times})
    res_gap = CandleValidator.find_gaps_and_duplicates(df_gap, timeframe="1m")
    assert res_gap["is_clean"] is False
    assert res_gap["gaps_count"] == 1
    assert res_gap["gap_intervals"][0]["missing_candles"] == 3
