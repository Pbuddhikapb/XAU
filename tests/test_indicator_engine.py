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
