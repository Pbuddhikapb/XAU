"""
Integration tests for StructureEngine (Timeframe Analysis, DB Persistence, MTF Synthesis).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from backend.database import async_engine, get_async_session
from backend.models.tables import StructureEvent
from backend.structure.market_structure import MarketStructureEvent
from backend.structure.structure_engine import StructureEngine


def generate_synthetic_candles(n: int = 40) -> pd.DataFrame:
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time + timedelta(hours=i) for i in range(n)]

    prices = [2640.0 + (i * 1.5) if i < 20 else 2670.0 - ((i - 20) * 1.8) for i in range(n)]
    highs = [p + 2.0 for p in prices]
    lows = [p - 2.0 for p in prices]

    return pd.DataFrame(
        {
            "open_time": times,
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": [100.0] * n,
        }
    )


def test_structure_engine_analyze_timeframe():
    df = generate_synthetic_candles(40)
    analysis = StructureEngine.analyze_timeframe(df, timeframe="1h")

    assert "timeframe" in analysis
    assert "current_trend" in analysis
    assert "structure_events" in analysis
    assert "liquidity_sweeps" in analysis
    assert "price_action_patterns" in analysis
    assert "sr_zones" in analysis


@pytest.mark.asyncio
async def test_structure_engine_persist_events():
    now = datetime.now(UTC)
    sample_event = MarketStructureEvent(
        event_type="BOS_BULL",
        price=2685.50,
        event_time=now,
        confirmed_candle_time=now + timedelta(minutes=5),
        invalidated_level=2670.00,
        timeframe="15m",
        metadata={"test": True},
    )

    try:
        count = await StructureEngine.persist_structure_events([sample_event], symbol="XAUUSDT")
        assert count == 1

        # Query back from database
        async with get_async_session() as session:
            stmt = select(StructureEvent).where(
                StructureEvent.symbol == "XAUUSDT",
                StructureEvent.event_type == "BOS_BULL",
                StructureEvent.timeframe == "15m",
            )
            res = await session.execute(stmt)
            record = res.scalars().first()
            assert record is not None
            assert float(record.price) == 2685.50
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_structure_engine_compute_mtf_alignment():
    try:
        mtf_result = await StructureEngine.compute_mtf_alignment(symbol="XAUUSDT")
        assert mtf_result is not None
        assert hasattr(mtf_result, "alignment_state")
        assert hasattr(mtf_result, "compound_score")
        assert len(mtf_result.timeframes) == 5
    finally:
        await async_engine.dispose()
