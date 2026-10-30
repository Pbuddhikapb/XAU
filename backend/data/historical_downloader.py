"""
High-Performance Historical Data Downloader for Binance XAUUSDT.
Streams and ingests official 1m archives directly from data.binance.vision (AWS S3)
into the PostgreSQL ohlcv_candles table with full validation and duplicate prevention.
"""

from datetime import datetime, timezone
import io
import logging
from typing import Dict, Generator, List, Optional
import urllib.request
import zipfile

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from backend.config import settings
from backend.database import get_sync_session
from backend.models.tables import OHLCVCandle
from backend.data.candle_validator import CandleValidator

logger = logging.getLogger(__name__)


class HistoricalDownloader:
    """Manages bulk download and database ingestion of XAUUSDT historical data."""

    def __init__(self, s3_base_url: Optional[str] = None):
        self.s3_base = (s3_base_url or settings.BINANCE_S3_BUCKET_URL).rstrip("/")
        self.symbol = settings.SYMBOL.upper()

    def download_and_parse_zip(self, s3_key: str) -> pd.DataFrame:
        """
        Download a single zip archive from S3 into memory and extract OHLCV DataFrame.
        """
        url = f"{self.s3_base}/{s3_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Downloader/1.0"})

        with urllib.request.urlopen(req, timeout=30) as response:
            zip_bytes = io.BytesIO(response.read())

        with zipfile.ZipFile(zip_bytes) as z:
            csv_filenames = [n for n in z.namelist() if n.endswith(".csv")]
            if not csv_filenames:
                raise ValueError(f"No CSV found inside {s3_key}")
            csv_content = z.read(csv_filenames[0])

        # Binance Futures Kline CSV columns
        # open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore
        col_names = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades_count", "taker_buy_volume",
            "taker_buy_quote_volume", "ignore"
        ]

        # Read CSV handling optional headers
        df = pd.read_csv(
            io.BytesIO(csv_content),
            header=0 if b"open_time" in csv_content[:100] else None,
            names=col_names,
            dtype={
                "open_time": "int64",
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
                "close_time": "int64",
                "quote_volume": "float64",
                "trades_count": "int64",
                "taker_buy_volume": "float64",
                "taker_buy_quote_volume": "float64",
            }
        )

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        df["symbol"] = self.symbol
        df["timeframe"] = "1m"
        df["is_confirmed"] = True
        df["source"] = "binance_vision"

        return df

    def bulk_insert_candles(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        Bulk upsert parsed candles into PostgreSQL using PostgreSQL ON CONFLICT DO UPDATE.
        Returns total inserted/updated rows count.
        """
        if df.empty:
            return 0

        # Validate rows
        valid_rows = []
        for row in df.to_dict(orient="records"):
            is_valid, err = CandleValidator.validate_single_candle(row)
            if is_valid:
                valid_rows.append(row)
            else:
                logger.warning("Rejected invalid candle: %s, Reason: %s", row.get("open_time"), err)

        if not valid_rows:
            return 0

        inserted_count = 0
        with get_sync_session() as session:
            for i in range(0, len(valid_rows), batch_size):
                batch = valid_rows[i:i + batch_size]
                stmt = insert(OHLCVCandle).values([
                    {
                        "symbol": r["symbol"],
                        "timeframe": r["timeframe"],
                        "open_time": r["open_time"],
                        "close_time": r["close_time"],
                        "open": r["open"],
                        "high": r["high"],
                        "low": r["low"],
                        "close": r["close"],
                        "volume": r["volume"],
                        "quote_volume": r["quote_volume"],
                        "trades_count": r["trades_count"],
                        "taker_buy_volume": r["taker_buy_volume"],
                        "taker_buy_quote_volume": r["taker_buy_quote_volume"],
                        "is_confirmed": r["is_confirmed"],
                        "source": r["source"],
                    }
                    for r in batch
                ]).on_conflict_do_update(
                    index_elements=["symbol", "timeframe", "open_time"],
                    set_={
                        "open": insert(OHLCVCandle).excluded.open,
                        "high": insert(OHLCVCandle).excluded.high,
                        "low": insert(OHLCVCandle).excluded.low,
                        "close": insert(OHLCVCandle).excluded.close,
                        "volume": insert(OHLCVCandle).excluded.volume,
                        "quote_volume": insert(OHLCVCandle).excluded.quote_volume,
                        "trades_count": insert(OHLCVCandle).excluded.trades_count,
                        "taker_buy_volume": insert(OHLCVCandle).excluded.taker_buy_volume,
                        "taker_buy_quote_volume": insert(OHLCVCandle).excluded.taker_buy_quote_volume,
                        "is_confirmed": True,
                    }
                )
                session.execute(stmt)
                inserted_count += len(batch)

        logger.info("Inserted %d candles into ohlcv_candles table.", inserted_count)
        return inserted_count

    def ingest_month(self, year_month: str) -> int:
        """
        Download and ingest an entire month of 1m candles (e.g. '2026-09').
        """
        s3_key = f"data/futures/um/monthly/klines/{self.symbol}/1m/{self.symbol}-1m-{year_month}.zip"
        df = self.download_and_parse_zip(s3_key)
        return self.bulk_insert_candles(df)

    def ingest_day(self, date_str: str) -> int:
        """
        Download and ingest a single day of 1m candles (e.g. '2026-10-29').
        """
        s3_key = f"data/futures/um/daily/klines/{self.symbol}/1m/{self.symbol}-1m-{date_str}.zip"
        df = self.download_and_parse_zip(s3_key)
        return self.bulk_insert_candles(df)
