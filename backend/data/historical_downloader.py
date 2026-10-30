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
from backend.models.tables import MarkIndexPrice, OHLCVCandle
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

    def download_and_parse_price_series(self, s3_key: str) -> pd.DataFrame:
        """
        Download and parse mark price or index price 1m klines from S3.
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

        col_names = [
            "open_time", "open", "high", "low", "close", "ignore1",
            "close_time", "ignore2", "ignore3", "ignore4", "ignore5", "ignore6"
        ]

        df = pd.read_csv(
            io.BytesIO(csv_content),
            header=0 if b"open_time" in csv_content[:100] else None,
            names=col_names,
            usecols=["open_time", "close"],
            dtype={"open_time": "int64", "close": "float64"}
        )
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        return df[["timestamp", "close"]]

    def ingest_mark_index_day(self, date_str: str, batch_size: int = 5000) -> int:
        """
        Download and synchronize mark and index prices for a given day into mark_index_prices.
        """
        mark_key = f"data/futures/um/daily/markPriceKlines/{self.symbol}/1m/{self.symbol}-1m-{date_str}.zip"
        index_key = f"data/futures/um/daily/indexPriceKlines/{self.symbol}/1m/{self.symbol}-1m-{date_str}.zip"
        contract_key = f"data/futures/um/daily/klines/{self.symbol}/1m/{self.symbol}-1m-{date_str}.zip"

        df_mark = self.download_and_parse_price_series(mark_key).rename(columns={"close": "mark_price"})
        df_index = self.download_and_parse_price_series(index_key).rename(columns={"close": "index_price"})
        df_contract = self.download_and_parse_zip(contract_key)[["open_time", "close"]].rename(
            columns={"open_time": "timestamp", "close": "contract_price"}
        )

        merged = pd.merge(df_contract, df_mark, on="timestamp")
        merged = pd.merge(merged, df_index, on="timestamp")
        merged["basis"] = merged["contract_price"] - merged["index_price"]
        merged["symbol"] = self.symbol

        records = merged.to_dict(orient="records")
        if not records:
            return 0

        inserted_count = 0
        with get_sync_session() as session:
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                stmt = insert(MarkIndexPrice).values([
                    {
                        "symbol": r["symbol"],
                        "timestamp": r["timestamp"],
                        "contract_price": r["contract_price"],
                        "mark_price": r["mark_price"],
                        "index_price": r["index_price"],
                        "basis": r["basis"],
                    }
                    for r in batch
                ]).on_conflict_do_update(
                    index_elements=["symbol", "timestamp"],
                    set_={
                        "contract_price": insert(MarkIndexPrice).excluded.contract_price,
                        "mark_price": insert(MarkIndexPrice).excluded.mark_price,
                        "index_price": insert(MarkIndexPrice).excluded.index_price,
                        "basis": insert(MarkIndexPrice).excluded.basis,
                    }
                )
                session.execute(stmt)
                inserted_count += len(batch)

        logger.info("Inserted %d rows into mark_index_prices for %s", inserted_count, date_str)
        return inserted_count

    def sync_incremental(self, start_date: str, end_date: str) -> Dict[str, int]:
        """
        Synchronize all missing daily archives between start_date and end_date (inclusive).
        Dates formatted as 'YYYY-MM-DD'.
        """
        date_range = pd.date_range(start=start_date, end=end_date, freq="1D")
        results = {"candles_inserted": 0, "days_processed": 0}

        for dt in date_range:
            d_str = dt.strftime("%Y-%m-%d")
            try:
                count = self.ingest_day(d_str)
                results["candles_inserted"] += count
                results["days_processed"] += 1
            except Exception as e:
                logger.warning("Could not sync day %s: %s", d_str, e)

        return results

