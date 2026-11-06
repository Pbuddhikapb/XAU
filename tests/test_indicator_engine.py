"""
Unit and integration tests for IndicatorEngine (Full Calculation, Snapshot Extraction, DB Upsert, Parity).
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.analytics.indicator_engine import IndicatorEngine
from backend.database import async_engine, get_async_session
from backend.models.tables import IndicatorSnapshot


def generate_synthetic_candles(n: int = 250) -> pd.DataFrame:
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time + timedelta(minutes=i * 5) for i in range(n)]

    np.random.seed(42)
    closes = 2650.0 + np.cumsum(np.random.normal(0, 0.5, n))
    highs = closes + np.random.uniform(0.2, 1.5, n)
    lows = closes - np.random.uniform(0.2, 1.5, n)
    opens = closes + np.random.normal(0, 0.2, n)
    volumes = np.random.uniform(50.0, 500.0, n)
    taker_vols = volumes * np.random.uniform(0.3, 0.7, n)

    return pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "taker_buy_volume": taker_vols,
        }
    )


def test_indicator_engine_compute_all():
    df = generate_synthetic_candles(250)
    res = IndicatorEngine.compute_all_indicators(df, symbol="XAUUSDT", timeframe="5m")

    required_cols = [
        "ema_20",
        "ema_50",
        "ema_100",
        "ema_200",
        "adx",
        "plus_di",
        "minus_di",
        "trend_strength",
        "rsi_14",
        "macd_val",
        "macd_signal",
        "macd_hist",
        "atr_14",
        "bb_upper",
        "bb_middle",
        "bb_lower",
        "volatility_percentile",
        "relative_volume",
        "taker_buy_ratio",
        "vwap",
    ]
    for col in required_cols:
        assert col in res.columns, f"Missing required indicator column: {col}"

    assert not np.isnan(res["ema_200"].iloc[-1])
    assert not np.isnan(res["rsi_14"].iloc[-1])
    assert not np.isnan(res["atr_14"].iloc[-1])


def test_indicator_engine_extract_snapshot():
    df = generate_synthetic_candles(250)
    res = IndicatorEngine.compute_all_indicators(df, symbol="XAUUSDT", timeframe="1h")
    snapshot = IndicatorEngine.extract_latest_snapshot(res, symbol="XAUUSDT", timeframe="1h")

    assert snapshot is not None
    assert snapshot["symbol"] == "XAUUSDT"
    assert snapshot["timeframe"] == "1h"
    assert isinstance(snapshot["candle_time"], datetime)
    assert snapshot["ema_20"] is not None
    assert snapshot["rsi_14"] is not None
    assert snapshot["vwap"] is not None


@pytest.mark.asyncio
async def test_indicator_engine_persist_snapshot():
    df = generate_synthetic_candles(250)
    res = IndicatorEngine.compute_all_indicators(df, symbol="XAUUSDT", timeframe="15m")
    snapshot = IndicatorEngine.extract_latest_snapshot(res, symbol="XAUUSDT", timeframe="15m")

    try:
        assert snapshot is not None
        await IndicatorEngine.persist_indicator_snapshot(snapshot)

        # Query back from database to verify persistence
        async with get_async_session() as session:
            db_record = await session.get(
                IndicatorSnapshot,
                (snapshot["symbol"], snapshot["timeframe"], snapshot["candle_time"]),
            )
            assert db_record is not None
            assert db_record.symbol == "XAUUSDT"
            assert db_record.timeframe == "15m"
            assert float(db_record.rsi_14) == snapshot["rsi_14"]
    finally:
        await async_engine.dispose()


def test_incremental_vs_historical_batch_parity():
    """
    Enforces Principle 7 & 9:
    Incremental calculation slice produces identical indicator values to full historical batch.
    """
    full_df = generate_synthetic_candles(300)
    batch_res = IndicatorEngine.compute_all_indicators(full_df)

    # Slice latest 220 bars (sufficient for EMA 200 and warmup)
    slice_df = full_df.iloc[-220:].copy()
    slice_res = IndicatorEngine.compute_all_indicators(slice_df)

    # Compare latest bar values between full batch and slice
    batch_last = batch_res.iloc[-1]
    slice_last = slice_res.iloc[-1]

    # RSI 14 (Wilder smooth) and EMA 20/50 should be identical within floating point tolerance
    assert np.isclose(batch_last["rsi_14"], slice_last["rsi_14"], atol=1e-3)
    assert np.isclose(batch_last["ema_20"], slice_last["ema_20"], atol=1e-3)
    assert np.isclose(batch_last["ema_50"], slice_last["ema_50"], atol=1e-3)
    assert np.isclose(batch_last["atr_14"], slice_last["atr_14"], atol=1e-3)
    assert np.isclose(batch_last["bb_middle"], slice_last["bb_middle"], atol=1e-3)


@pytest.mark.asyncio
async def test_process_and_persist_candle_close():
    candle = {
        "symbol": "XAUUSDT",
        "timeframe": "1m",
        "open_time": datetime.now(UTC),
        "close_time": datetime.now(UTC) + timedelta(minutes=1),
        "open": 2650.0,
        "high": 2655.0,
        "low": 2648.0,
        "close": 2653.0,
        "volume": 120.0,
        "taker_buy_volume": 65.0,
        "is_confirmed": True,
    }
    # Test with candle
    snap = await IndicatorEngine.process_and_persist_candle_close(candle, symbol="XAUUSDT", timeframe="1m")
    # Even if DB has few rows, it handles gracefully without crashing
    assert snap is None or isinstance(snap, dict)


def test_indicator_engine_session_marking_and_filtering():
    """Verify that compute_all_indicators marks candle session states and supports active filtering."""
    base_time = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)  # Wednesday 16:00 EDT
    # Create 10 bars spanning active trading, daily break (21:00 UTC = 17:00 EDT), and re-opening
    times = [base_time + timedelta(minutes=30 * i) for i in range(10)]
    df = pd.DataFrame({
        "open_time": times,
        "open": [2650.0 + i for i in range(10)],
        "high": [2655.0 + i for i in range(10)],
        "low": [2645.0 + i for i in range(10)],
        "close": [2652.0 + i for i in range(10)],
        "volume": [100.0] * 10,
        "taker_buy_volume": [50.0] * 10,
    })

    # 1. Default: enrich with session state columns
    res_default = IndicatorEngine.compute_all_indicators(df)
    assert "tradfi_session_state" in res_default.columns
    assert "is_tradfi_active" in res_default.columns
    assert "analysis_weight" in res_default.columns
    assert "exclusion_reason" in res_default.columns
    assert len(res_default) == 10

    # Bars during 21:00-22:00 UTC (17:00-18:00 EDT) should be marked as MAINTENANCE (DAILY_BREAK)
    break_bars = res_default[res_default["open_time"] == datetime(2026, 10, 28, 21, 30, tzinfo=UTC)]
    assert len(break_bars) == 1
    assert break_bars.iloc[0]["tradfi_session_state"] == "MAINTENANCE"
    assert bool(break_bars.iloc[0]["is_tradfi_active"]) is False
    assert float(break_bars.iloc[0]["analysis_weight"]) == 0.1
    assert break_bars.iloc[0]["exclusion_reason"] == "DAILY_BREAK"

    # 2. Filter inactive: should exclude maintenance break bars
    res_filtered = IndicatorEngine.compute_all_indicators(df, filter_inactive_sessions=True)
    assert len(res_filtered) < 10
    assert not (res_filtered["tradfi_session_state"] == "MAINTENANCE").any()

