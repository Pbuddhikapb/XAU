"""
Unit tests for CandleResampler.
Validates multi-timeframe aggregation, boundary alignment, and incomplete candle rejection.
"""

from datetime import datetime, timezone
import pandas as pd
import pytest

from backend.data.resampler import CandleResampler


def generate_mock_1m_data(count: int = 60, start_time: str = "2026-10-30 00:00:00") -> pd.DataFrame:
    """Generate deterministic 1m candles for testing resampling."""
    times = pd.date_range(start_time, periods=count, freq="1min", tz="UTC")
    data = []
    base_price = 4000.0
    for i, t in enumerate(times):
        o = base_price + i
        h = o + 2.0
        l = o - 1.0
        c = o + 1.0
        v = 10.0
        qv = v * c
        tbv = 6.0
        data.append({
            "open_time": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "quote_volume": qv,
            "trades_count": 50,
            "taker_buy_volume": tbv,
            "taker_buy_quote_volume": tbv * c,
        })
    return pd.DataFrame(data)


def test_resample_5m_exact_math():
    df_1m = generate_mock_1m_data(count=15)  # exactly three 5m bars
    df_5m = CandleResampler.resample_ohlcv(df_1m, target_timeframe="5m", only_confirmed=True)

    assert len(df_5m) == 3
    # First 5m bar covers indices 0..4
    first_bar = df_5m.iloc[0]
    assert first_bar["open"] == df_1m.iloc[0]["open"]
    assert first_bar["close"] == df_1m.iloc[4]["close"]
    assert first_bar["high"] == df_1m.iloc[0:5]["high"].max()
    assert first_bar["low"] == df_1m.iloc[0:5]["low"].min()
    assert first_bar["volume"] == df_1m.iloc[0:5]["volume"].sum()
    assert first_bar["timeframe"] == "5m"


def test_incomplete_candle_rejection():
    # 7 minutes of data: one complete 5m bar (min 0..4) and one incomplete 5m bar (min 5..6, only 2 bars)
    df_1m = generate_mock_1m_data(count=7)
    df_5m_confirmed = CandleResampler.resample_ohlcv(df_1m, target_timeframe="5m", only_confirmed=True)

    # Incomplete bar MUST be dropped when only_confirmed=True (Principle 14)
    assert len(df_5m_confirmed) == 1
    assert df_5m_confirmed.iloc[0]["open_time"] == pd.Timestamp("2026-10-30 00:00:00", tz="UTC")

    # When only_confirmed=False, incomplete bar is included
    df_5m_all = CandleResampler.resample_ohlcv(df_1m, target_timeframe="5m", only_confirmed=False)
    assert len(df_5m_all) == 2


def test_4h_boundary_alignment():
    # 240 minutes = exactly one 4h bar starting at 00:00 UTC
    df_1m = generate_mock_1m_data(count=240, start_time="2026-10-30 00:00:00")
    df_4h = CandleResampler.resample_ohlcv(df_1m, target_timeframe="4h", only_confirmed=True)

    assert len(df_4h) == 1
    assert df_4h.iloc[0]["open_time"] == pd.Timestamp("2026-10-30 00:00:00", tz="UTC")
    assert df_4h.iloc[0]["volume"] == 240 * 10.0


def test_reconcile_with_native():
    df_1m = generate_mock_1m_data(count=60, start_time="2026-10-30 00:00:00")
    df_1h_resampled = CandleResampler.resample_ohlcv(df_1m, target_timeframe="1h")

    # Native identical candle
    df_native = df_1h_resampled.copy()
    rec_result = CandleResampler.reconcile_with_native(df_1h_resampled, df_native)
    assert rec_result["is_reconciled"] is True
    assert rec_result["price_match_rate"] == 1.0
    assert rec_result["max_price_diff"] == 0.0

    # Native mismatched candle
    df_native_bad = df_native.copy()
    df_native_bad["close"] = df_native_bad["close"] + 5.0
    rec_bad = CandleResampler.reconcile_with_native(df_1h_resampled, df_native_bad)
    assert rec_bad["is_reconciled"] is False
    assert rec_bad["max_price_diff"] >= 5.0


def test_resample_with_gap_recovery():
    # 10 minutes of data with a 1-minute gap at min 3 (indices 0, 1, 2, 4, 5, 6, 7, 8, 9)
    df_1m = generate_mock_1m_data(count=10)
    df_gap = df_1m.drop(index=[3]).reset_index(drop=True)

    # Without gap recovery: first 5m bar has only 4 candles, so it gets dropped
    df_5m_no_rec = CandleResampler.resample_ohlcv(df_gap, target_timeframe="5m", only_confirmed=True, recover_gaps=False)
    assert len(df_5m_no_rec) == 1  # Only second 5m bar survived

    # With gap recovery: missing 1m bar is imputed (0 vol), so both 5m bars survive
    df_5m_rec = CandleResampler.resample_ohlcv(df_gap, target_timeframe="5m", only_confirmed=True, recover_gaps=True)
    assert len(df_5m_rec) == 2

