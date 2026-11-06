"""
Unit tests for CandleResampler.
Validates:
1. Multi-timeframe aggregation, boundary alignment, and incomplete candle rejection.
2. Input validation for missing required OHLCV columns.
3. Dynamic handling when optional exchange metadata columns are omitted.
4. Handling of duplicate open_time timestamps.
5. Incomplete intervals and confirmation flags.
6. Gap recovery and reconciliation against native exchange candles.
"""

from datetime import UTC, datetime

import pandas as pd
import pytest

from backend.data.resampler import CandleResampler


def generate_mock_1m_data(count: int = 60, start_time: str = "2026-10-30 00:00:00") -> pd.DataFrame:
    """Generate deterministic 1m candles for testing resampling."""
    times = pd.date_range(start_time, periods=count, freq="1min", tz="UTC")
    data = []
    base_price = 4000.0
    for i, t in enumerate(times):
        open_val = base_price + i
        high_val = open_val + 2.0
        low_val = open_val - 1.0
        close_val = open_val + 1.0
        vol_val = 10.0
        qv = vol_val * close_val
        tbv = 6.0
        data.append(
            {
                "open_time": t,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "volume": vol_val,
                "quote_volume": qv,
                "trades_count": 50,
                "taker_buy_volume": tbv,
                "taker_buy_quote_volume": tbv * close_val,
            }
        )
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

    # When only_confirmed=False, incomplete bar is included but flagged with is_confirmed=False
    df_5m_all = CandleResampler.resample_ohlcv(df_1m, target_timeframe="5m", only_confirmed=False)
    assert len(df_5m_all) == 2
    assert df_5m_all.iloc[0]["is_confirmed"]
    assert not df_5m_all.iloc[1]["is_confirmed"]


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
    assert rec_result["max_price_diff"] == 0.0

    # Native mismatched candle
    df_native_bad = df_native.copy()
    df_native_bad["close"] = df_native_bad["close"] + 5.0
    rec_bad = CandleResampler.reconcile_with_native(df_1h_resampled, df_native_bad)
    assert rec_bad["is_reconciled"] is False
    assert rec_bad["max_price_diff"] >= 5.0


def test_resample_missing_required_columns_raises_error():
    """Verify that omitting required columns (e.g. 'close' or 'volume') raises ValueError."""
    bad_df = pd.DataFrame(
        {
            "open_time": [datetime(2026, 10, 30, 0, 0, tzinfo=UTC)],
            "open": [4000.0],
            # 'high', 'low', 'close', 'volume' are missing!
        }
    )
    with pytest.raises(ValueError, match="Missing required OHLCV columns"):
        CandleResampler.resample_ohlcv(bad_df, target_timeframe="5m")


def test_resample_optional_columns_omitted():
    """Verify that resampling succeeds even if quote_volume or trades_count are absent."""
    times = pd.date_range("2026-10-30 00:00:00", periods=5, freq="1min", tz="UTC")
    clean_df = pd.DataFrame(
        {
            "open_time": times,
            "open": [4000.0 + i for i in range(5)],
            "high": [4002.0 + i for i in range(5)],
            "low": [3999.0 + i for i in range(5)],
            "close": [4001.0 + i for i in range(5)],
            "volume": [10.0] * 5,
            # No quote_volume, trades_count, or taker_buy_volume
        }
    )
    df_5m = CandleResampler.resample_ohlcv(clean_df, target_timeframe="5m")
    assert len(df_5m) == 1
    assert "quote_volume" not in df_5m.columns
    assert df_5m.iloc[0]["volume"] == 50.0


def test_resample_duplicate_timestamps_deduplicated():
    """Verify that duplicate timestamps are automatically deduplicated."""
    times = pd.date_range("2026-10-30 00:00:00", periods=5, freq="1min", tz="UTC")
    df_1m = pd.DataFrame(
        {
            "open_time": list(times) + [times[0]],  # times[0] duplicated!
            "open": [4000.0] * 6,
            "high": [4002.0] * 6,
            "low": [3998.0] * 6,
            "close": [4001.0] * 6,
            "volume": [10.0] * 6,
        }
    )
    df_5m = CandleResampler.resample_ohlcv(df_1m, target_timeframe="5m")
    assert len(df_5m) == 1
    assert df_5m.iloc[0]["volume"] == 50.0  # deduplicated to 5 bars


def test_resample_empty_dataframe():
    """Verify that resampling an empty dataframe returns an empty dataframe safely."""
    empty_df = pd.DataFrame()
    res = CandleResampler.resample_ohlcv(empty_df, target_timeframe="5m")
    assert res.empty


def test_resample_cme_session_day_and_reconciliation():
    """
    Verify CME Session Day (18:00 ET to 17:00 ET) 1D aggregation and reconciliation:
    1. Aggregates Sunday 18:00 ET to Monday 17:00 ET into Monday session (1,380 active bars).
    2. Respects config flag ENABLE_CME_SESSION_DAILY_CANDLES.
    3. Reconciles against native Binance 1d klines and documents structural differences.
    """
    from unittest.mock import patch

    # Generate 1m bars from Sunday 18:00 EDT (22:00 UTC) to Monday 17:00 EDT (21:00 UTC)
    # Total = 23 hours = 1,380 minutes
    times = pd.date_range("2026-10-18 22:00", "2026-10-19 20:59", freq="1min", tz="UTC")
    assert len(times) == 1380

    df_1m = pd.DataFrame({
        "open_time": times,
        "open": [2650.0 + (i * 0.01) for i in range(1380)],
        "high": [2655.0 + (i * 0.01) for i in range(1380)],
        "low": [2645.0 + (i * 0.01) for i in range(1380)],
        "close": [2651.0 + (i * 0.01) for i in range(1380)],
        "volume": [10.0] * 1380,
    })

    # Resample to 1d_cme
    df_cme = CandleResampler.resample_ohlcv(df_1m, target_timeframe="1d_cme")
    assert len(df_cme) == 1
    row = df_cme.iloc[0]
    assert row["timeframe"] == "1d_cme"
    assert row["bars_count"] == 1380
    assert bool(row["is_confirmed"]) is True
    assert row["session_date"] == "2026-10-19"
    assert row["open"] == df_1m["open"].iloc[0]
    assert row["close"] == df_1m["close"].iloc[-1]
    assert row["volume"] == 13800.0

    # Config flag check: when disabled, returns empty DataFrame
    with patch("backend.config.settings.ENABLE_CME_SESSION_DAILY_CANDLES", False):
        disabled_res = CandleResampler.resample_cme_session_day(df_1m)
        assert disabled_res.empty

    # Reconcile against synthetic native Binance 1d candle (00:00 to 24:00 UTC)
    native_1d = pd.DataFrame({
        "open_time": [pd.Timestamp("2026-10-19 00:00:00+00:00")],
        "open": [2652.0],
        "high": [2670.0],
        "low": [2644.0],
        "close": [2664.0],
        "volume": [14400.0],
    })

    recon = CandleResampler.reconcile_cme_vs_binance_1d(df_cme, native_1d)
    assert recon["matched_sessions"] == 1
    assert "mean_open_diff" in recon
    assert "mean_close_diff" in recon
    assert "mean_volume_coverage_ratio" in recon
    assert "documentation" in recon
    assert "1d_cme" in recon["documentation"]
    assert "1,380" in recon["documentation"]

