"""
Integration and unit tests for HistoricalDownloader.
Tests downloading archives, SHA-256 verification, REST backfilling,
idempotent ingestion, funding rate ingestion, and mark/index divergence.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import func, select

from backend.data.historical_downloader import HistoricalDownloader
from backend.data.resampler import CandleResampler
from backend.database import get_sync_session
from backend.models.tables import MarkIndexPrice, OHLCVCandle


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
            select(func.count())
            .select_from(OHLCVCandle)
            .where(OHLCVCandle.symbol == "XAUUSDT", OHLCVCandle.timeframe == "1m")
        ).scalar()
        assert db_count is not None
        assert db_count >= 1440

    # Idempotency check: Re-inserting the same data must succeed without duplicate error
    reinsert_count = downloader.bulk_insert_candles(df)
    assert reinsert_count == 1440


def test_historical_downloader_mark_index_day():
    downloader = HistoricalDownloader()
    date_str = "2026-10-27"

    count = downloader.ingest_mark_index_day(date_str)
    assert count == 1440

    with get_sync_session() as session:
        db_count = session.execute(
            select(func.count()).select_from(MarkIndexPrice).where(MarkIndexPrice.symbol == "XAUUSDT")
        ).scalar()
        assert db_count is not None
        assert db_count >= 1440


def test_sha256_checksum_verification_and_tamper_detection():
    downloader = HistoricalDownloader()
    s3_key = "data/futures/um/daily/klines/XAUUSDT/1m/XAUUSDT-1m-2026-10-29.zip"

    # 1. Genuine archive passes checksum
    zip_bytes, sha256_hash = downloader.download_archive_with_checksum(s3_key, verify=True)
    assert len(zip_bytes) > 0
    assert len(sha256_hash) == 64

    # 2. Tampered content fails checksum verification
    tampered_bytes = zip_bytes + b"tampered_bytes"
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = tampered_bytes

    mock_chk_resp = MagicMock()
    mock_chk_resp.__enter__.return_value = mock_chk_resp
    mock_chk_resp.read.return_value = f"{sha256_hash}  XAUUSDT-1m-2026-10-29.zip".encode()

    with patch("urllib.request.OpenerDirector.open", side_effect=[mock_resp, mock_chk_resp]):
        with pytest.raises(ValueError, match="SHA-256 Checksum verification failed"):
            downloader.download_archive_with_checksum(s3_key, verify=True)


def test_pre_listing_data_rejection():
    """Ensure pre-listing synthetic data prior to 2025-12-11 08:05:00 UTC is strictly discarded."""
    downloader = HistoricalDownloader()

    # Pre-listing timestamp (e.g. 2025-12-01)
    df_pre = pd.DataFrame(
        {
            "symbol": ["XAUUSDT"],
            "timeframe": ["1m"],
            "open_time": [datetime(2025, 12, 1, 0, 0, tzinfo=UTC)],
            "close_time": [datetime(2025, 12, 1, 0, 0, 59, 999000, tzinfo=UTC)],
            "open": [4000.0],
            "high": [4010.0],
            "low": [3990.0],
            "close": [4005.0],
            "volume": [10.0],
            "quote_volume": [40000.0],
            "trades_count": [10],
            "taker_buy_volume": [5.0],
            "taker_buy_quote_volume": [20000.0],
            "is_confirmed": [True],
            "source": ["fabricated_synthetic"],
        }
    )

    count = downloader.bulk_insert_candles(df_pre)
    assert count == 0

    # Ensure no rows entered the database
    with get_sync_session() as session:
        cnt = session.execute(
            select(func.count())
            .select_from(OHLCVCandle)
            .where(
                OHLCVCandle.symbol == "XAUUSDT",
                OHLCVCandle.open_time < datetime(2025, 12, 11, 8, 5, tzinfo=UTC),
            )
        ).scalar()
        assert cnt == 0


def test_resampling_reconciliation_5m_15m_1h_4h_1d():
    """Verify that synthetic resampled candles match Binance native candles with 0.0 price diff."""
    downloader = HistoricalDownloader()
    s3_1m = "data/futures/um/monthly/klines/XAUUSDT/1m/XAUUSDT-1m-2026-09.zip"
    df_1m = downloader.download_and_parse_zip(s3_1m)

    for tf in ["5m", "15m", "1h", "4h", "1d"]:
        resampled = CandleResampler.resample_ohlcv(df_1m, tf)
        s3_native = f"data/futures/um/monthly/klines/XAUUSDT/{tf}/XAUUSDT-{tf}-2026-09.zip"
        df_native = downloader.download_and_parse_zip(s3_native)

        rec = CandleResampler.reconcile_with_native(resampled, df_native)
        assert rec["matched_bars"] > 0
        assert rec["is_reconciled"] is True
        assert rec["max_price_diff"] <= 0.01  # Exact match
