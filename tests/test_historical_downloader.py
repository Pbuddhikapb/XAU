"""
Integration tests for HistoricalDownloader.
Tests downloading real archive from data.binance.vision, parsing, and bulk inserting into PostgreSQL.
"""

import pytest
from sqlalchemy import func, select

from backend.data.historical_downloader import HistoricalDownloader
from backend.database import get_sync_session
from backend.models.tables import OHLCVCandle


def test_historical_downloader_daily_archive():
    downloader = HistoricalDownloader()

    # Download daily archive for 2026-10-29 (Thursday)
    date_str = "2026-10-29"
    s3_key = f"data/futures/um/daily/klines/XAUUSDT/1m/XAUUSDT-1m-{date_str}.zip"
    df = downloader.download_and_parse_zip(s3_key)

    assert not df.empty
    assert len(df) == 1440  # 1440 minutes in a full day
    assert df.iloc[0]["symbol"] == "XAUUSDT"
    assert df.iloc[0]["timeframe"] == "1m"
    assert df.iloc[0]["open"] > 0
    assert df.iloc[0]["high"] >= max(df.iloc[0]["open"], df.iloc[0]["close"])

    # Bulk insert into PostgreSQL
    count = downloader.bulk_insert_candles(df)
    assert count == 1440

    # Verify rows in PostgreSQL
    with get_sync_session() as session:
        db_count = session.execute(
            select(func.count()).select_from(OHLCVCandle).where(
                OHLCVCandle.symbol == "XAUUSDT",
                OHLCVCandle.timeframe == "1m"
            )
        ).scalar()
        assert db_count >= 1440

    # Idempotency check: Re-inserting the same data must succeed without duplicate error
    reinsert_count = downloader.bulk_insert_candles(df)
    assert reinsert_count == 1440
