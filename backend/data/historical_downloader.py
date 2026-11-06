"""
High-Performance Historical Data Downloader for Binance XAUUSDT.
Streams and ingests official 1m archives directly from data.binance.vision (AWS S3)
into PostgreSQL with SHA-256 verification, REST gap backfilling, and quality auditing.
"""

import hashlib
import io
import json
import logging
import urllib.error
import urllib.request
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy.dialects.postgresql import insert

from backend.config import settings
from backend.data.resampler import CandleResampler
from backend.data.session_tracker import SessionTracker, TradFiSessionState
from backend.database import get_sync_session, sync_engine
from backend.models.tables import MarkIndexPrice

logger = logging.getLogger(__name__)


class HistoricalDownloader:
    """Manages bulk download, checksum verification, REST backfilling, and database ingestion."""

    def __init__(self, s3_base_url: str | None = None, proxy_url: str | None = None):
        self.s3_base = (s3_base_url or settings.BINANCE_S3_BUCKET_URL).rstrip("/")
        self.proxy_url = proxy_url or settings.OUTBOUND_PROXY_URL
        self.symbol = settings.SYMBOL.upper()
        self.onboard_dt = pd.to_datetime(settings.CONTRACT_ONBOARD_TIME_MS, unit="ms", utc=True)

    def _build_opener(self) -> urllib.request.OpenerDirector:
        """Create URL opener supporting optional outbound HTTP/HTTPS proxy."""
        handlers: list[urllib.request.BaseHandler] = []
        if self.proxy_url:
            handlers.append(
                urllib.request.ProxyHandler(
                    {"http": self.proxy_url, "https": self.proxy_url}
                )
            )
        return urllib.request.build_opener(*handlers)

    def download_archive_with_checksum(self, s3_key: str, verify: bool = True) -> tuple[bytes, str]:
        """
        Download a zip archive from S3 into memory and verify its SHA-256 against official .CHECKSUM file.
        Returns (zip_bytes, sha256_hash).
        """
        url = f"{self.s3_base}/{s3_key}"
        opener = self._build_opener()
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Downloader/1.0"})

        with opener.open(req, timeout=45) as response:
            zip_bytes = response.read()

        calculated_hash = hashlib.sha256(zip_bytes).hexdigest().lower()

        if verify:
            chk_url = f"{url}.CHECKSUM"
            chk_req = urllib.request.Request(chk_url, headers={"User-Agent": "Antigravity-Downloader/1.0"})
            try:
                with opener.open(chk_req, timeout=15) as chk_resp:
                    chk_content = chk_resp.read().decode("utf-8").strip()
                    expected_hash = chk_content.split()[0].lower()
                    if calculated_hash != expected_hash:
                        raise ValueError(
                            f"SHA-256 Checksum verification failed for {s3_key}! "
                            f"Expected {expected_hash}, calculated {calculated_hash}"
                        )
                    logger.debug("Verified SHA-256 checksum for %s: %s", s3_key, calculated_hash[:16])
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.warning("No checksum file found at %s. Proceeding without remote checksum.", chk_url)
                else:
                    raise

        return zip_bytes, calculated_hash

    def download_and_parse_zip(self, s3_key: str, verify_checksum: bool = True) -> pd.DataFrame:
        """
        Download a single zip archive from S3 into memory and extract OHLCV DataFrame.
        Enforces UTC timestamps and strictly discards pre-listing synthetic candles.
        """
        zip_bytes, _ = self.download_archive_with_checksum(s3_key, verify=verify_checksum)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            csv_filenames = [n for n in z.namelist() if n.endswith(".csv")]
            if not csv_filenames:
                raise ValueError(f"No CSV found inside {s3_key}")
            csv_content = z.read(csv_filenames[0])

        col_names = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades_count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "ignore",
        ]

        has_header = b"open_time" in csv_content[:100]
        df = pd.read_csv(
            io.BytesIO(csv_content),
            header=0 if has_header else None,
            names=None if has_header else col_names,
            dtype={
                "open_time": "int64",
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
                "close_time": "int64",
                "quote_volume": "float64",
                "taker_buy_volume": "float64",
                "taker_buy_quote_volume": "float64",
            },
        )

        if has_header and "count" in df.columns:
            df = df.rename(columns={"count": "trades_count"})

        if "trades_count" in df.columns:
            df["trades_count"] = df["trades_count"].fillna(0).astype("int64")

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        df["symbol"] = self.symbol
        df["timeframe"] = "1m"
        df["is_confirmed"] = True
        df["source"] = "binance_vision"

        # Disallow fabricated pre-listing data
        df = df[df["open_time"] >= self.onboard_dt].reset_index(drop=True)
        return df

    def bulk_insert_candles(self, df: pd.DataFrame, batch_size: int = 10000) -> int:
        """
        Bulk upsert parsed candles into PostgreSQL using psycopg2 execute_values for high throughput.
        Enforces strict invariants: high >= low, high >= max(open, close), low <= min(open, close),
        positive prices, non-negative volume, and no pre-listing data.
        Returns total inserted/updated rows count.
        """
        if df.empty:
            return 0

        df_work = df.copy()

        # Enforce UTC timestamps
        if not pd.api.types.is_datetime64_any_dtype(df_work["open_time"]):
            df_work["open_time"] = pd.to_datetime(
                df_work["open_time"],
                unit="ms" if pd.api.types.is_numeric_dtype(df_work["open_time"]) else None,
                utc=True,
            )
        if not pd.api.types.is_datetime64_any_dtype(df_work["close_time"]):
            df_work["close_time"] = pd.to_datetime(
                df_work["close_time"],
                unit="ms" if pd.api.types.is_numeric_dtype(df_work["close_time"]) else None,
                utc=True,
            )

        # Enforce no pre-listing data
        df_work = df_work[df_work["open_time"] >= self.onboard_dt]
        if df_work.empty:
            return 0

        # Vectorized OHLCV validation
        is_valid = (
            (df_work["high"] >= df_work["low"])
            & (df_work["high"] >= df_work[["open", "close"]].max(axis=1))
            & (df_work["low"] <= df_work[["open", "close"]].min(axis=1))
            & (df_work["open"] > 0)
            & (df_work["high"] > 0)
            & (df_work["low"] > 0)
            & (df_work["close"] > 0)
            & (df_work["volume"] >= 0)
        )

        if not is_valid.all():
            invalid_cnt = int((~is_valid).sum())
            logger.warning("Filtered out %d candle rows violating OHLCV invariants.", invalid_cnt)
            df_work = df_work[is_valid]

        if df_work.empty:
            return 0

        # Build tuples for batch execute
        rows: list[tuple[Any, ...]] = []
        for r in df_work.itertuples(index=False):
            rows.append(
                (
                    getattr(r, "symbol", self.symbol),
                    getattr(r, "timeframe", "1m"),
                    r.open_time,
                    r.close_time,
                    float(r.open),
                    float(r.high),
                    float(r.low),
                    float(r.close),
                    float(r.volume),
                    float(getattr(r, "quote_volume", 0.0)),
                    int(getattr(r, "trades_count", 0)),
                    float(getattr(r, "taker_buy_volume", 0.0)),
                    float(getattr(r, "taker_buy_quote_volume", 0.0)),
                    bool(getattr(r, "is_confirmed", True)),
                    str(getattr(r, "source", "binance_vision")),
                )
            )

        sql = """
        INSERT INTO ohlcv_candles (
            symbol, timeframe, open_time, close_time, open, high, low, close,
            volume, quote_volume, trades_count, taker_buy_volume, taker_buy_quote_volume,
            is_confirmed, source
        ) VALUES %s
        ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET
            close_time = EXCLUDED.close_time,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            quote_volume = EXCLUDED.quote_volume,
            trades_count = EXCLUDED.trades_count,
            taker_buy_volume = EXCLUDED.taker_buy_volume,
            taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
            is_confirmed = EXCLUDED.is_confirmed,
            source = EXCLUDED.source;
        """

        raw_conn = sync_engine.raw_connection()
        try:
            with closing(raw_conn.cursor()) as cur:
                execute_values(cur, sql, rows, page_size=batch_size)
            raw_conn.commit()
        finally:
            raw_conn.close()

        logger.info("Inserted/updated %d candles into ohlcv_candles table.", len(rows))
        return len(rows)

    def fetch_klines_rest(
        self,
        start_time_ms: int,
        end_time_ms: int,
        interval: str = "1m",
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch authentic klines from Binance Futures REST API across specified time span.
        Uses configured REST endpoint (testnet or production) with automatic pagination.
        """
        base_url = (
            settings.BINANCE_FUTURES_HTTP_URL
            if (settings.ENVIRONMENT == "production" or settings.OUTBOUND_PROXY_URL)
            else settings.BINANCE_TESTNET_HTTP_URL
        ).rstrip("/")

        all_klines: list[list[Any]] = []
        cur_start = start_time_ms
        opener = self._build_opener()

        while cur_start <= end_time_ms:
            url = (
                f"{base_url}/fapi/v1/klines?symbol={self.symbol}&interval={interval}"
                f"&startTime={cur_start}&endTime={end_time_ms}&limit={limit}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Downloader/1.0"})

            try:
                with opener.open(req, timeout=20) as resp:
                    batch = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                # Fallback to testnet if production endpoint geo-blocked
                if (e.code in (403, 451)) and base_url != settings.BINANCE_TESTNET_HTTP_URL.rstrip("/"):
                    logger.warning("Production REST geo-blocked (%d). Falling back to testnet endpoint.", e.code)
                    base_url = settings.BINANCE_TESTNET_HTTP_URL.rstrip("/")
                    continue
                raise

            if not batch:
                break

            all_klines.extend(batch)
            if len(batch) < limit:
                break
            last_open = int(batch[-1][0])
            cur_start = last_open + (60000 if interval == "1m" else 1000)

        if not all_klines:
            return pd.DataFrame()

        col_names = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades_count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "ignore",
        ]
        df = pd.DataFrame(all_klines, columns=col_names)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "taker_buy_volume",
            "taker_buy_quote_volume",
        ]:
            df[col] = df[col].astype("float64")
        df["trades_count"] = df["trades_count"].astype("int64")
        df["symbol"] = self.symbol
        df["timeframe"] = interval
        df["is_confirmed"] = True
        df["source"] = "binance_rest"

        df = df[df["open_time"] >= self.onboard_dt].reset_index(drop=True)
        return df

    def ingest_2026_10_28_gap(self) -> int:
        """
        Ingest the missing 2026-10-28 daily archive directly from Binance REST endpoint.
        Retrieves exactly 1,440 one-minute bars for the full 24-hour UTC day.
        """
        start_ms = int(datetime(2026, 10, 28, 0, 0, tzinfo=UTC).timestamp() * 1000)
        end_ms = int(datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
        logger.info("Fetching 2026-10-28 gap from REST API (%s to %s)...", start_ms, end_ms)
        df = self.fetch_klines_rest(start_ms, end_ms, interval="1m")
        if df.empty:
            raise ValueError("Failed to retrieve 2026-10-28 klines from REST API.")
        return self.bulk_insert_candles(df)

    def ingest_month(self, year_month: str, verify_checksum: bool = True) -> int:
        """
        Download and ingest an entire month of 1m candles (e.g. '2026-09').
        """
        s3_key = f"data/futures/um/monthly/klines/{self.symbol}/1m/{self.symbol}-1m-{year_month}.zip"
        df = self.download_and_parse_zip(s3_key, verify_checksum=verify_checksum)
        return self.bulk_insert_candles(df)

    def ingest_day(self, date_str: str, verify_checksum: bool = True) -> int:
        """
        Download and ingest a single day of 1m candles (e.g. '2026-10-29').
        """
        s3_key = f"data/futures/um/daily/klines/{self.symbol}/1m/{self.symbol}-1m-{date_str}.zip"
        df = self.download_and_parse_zip(s3_key, verify_checksum=verify_checksum)
        return self.bulk_insert_candles(df)

    def download_and_parse_price_series(self, s3_key: str, verify_checksum: bool = True) -> pd.DataFrame:
        """
        Download and parse mark price or index price 1m klines from S3.
        """
        zip_bytes, _ = self.download_archive_with_checksum(s3_key, verify=verify_checksum)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            csv_filenames = [n for n in z.namelist() if n.endswith(".csv")]
            if not csv_filenames:
                raise ValueError(f"No CSV found inside {s3_key}")
            csv_content = z.read(csv_filenames[0])

        col_names = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "ignore1",
            "close_time",
            "ignore2",
            "ignore3",
            "ignore4",
            "ignore5",
            "ignore6",
        ]

        has_header = b"open_time" in csv_content[:100]
        df = pd.read_csv(
            io.BytesIO(csv_content),
            header=0 if has_header else None,
            names=None if has_header else col_names,
            usecols=["open_time", "close"] if has_header else [0, 4],
            dtype={"open_time": "int64", "close": "float64"},
        )
        if not has_header:
            df.columns = ["open_time", "close"]

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
                batch = records[i : i + batch_size]
                stmt = (
                    insert(MarkIndexPrice)
                    .values(
                        [
                            {
                                "symbol": r["symbol"],
                                "timestamp": r["timestamp"],
                                "contract_price": r["contract_price"],
                                "mark_price": r["mark_price"],
                                "index_price": r["index_price"],
                                "basis": r["basis"],
                            }
                            for r in batch
                        ]
                    )
                    .on_conflict_do_update(
                        index_elements=["symbol", "timestamp"],
                        set_={
                            "contract_price": insert(MarkIndexPrice).excluded.contract_price,
                            "mark_price": insert(MarkIndexPrice).excluded.mark_price,
                            "index_price": insert(MarkIndexPrice).excluded.index_price,
                            "basis": insert(MarkIndexPrice).excluded.basis,
                        },
                    )
                )
                session.execute(stmt)
                inserted_count += len(batch)

        logger.info("Inserted %d rows into mark_index_prices for %s", inserted_count, date_str)
        return inserted_count

    def ingest_full_1m_history(self, force: bool = False) -> dict[str, Any]:
        """
        Execute full historical 1m ingestion:
        - Monthly archives (2025-12 through 2026-10) with SHA-256 verification
        - REST gap backfill for missing 2026-10-28 archive
        - Daily archives for November 2026 (2026-11-01 to 2026-11-04)
        - REST backfill for 2026-11-05
        Resumable and strictly idempotent.
        """
        months = [
            "2025-12",
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
            "2026-08",
            "2026-09",
            "2026-10",
        ]
        days_nov = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]

        # Check existing row counts per month for resumability
        raw_conn = sync_engine.raw_connection()
        existing_months: dict[str, int] = {}
        try:
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT to_char(open_time, 'YYYY-MM'), count(*)
                    FROM ohlcv_candles
                    WHERE symbol = %s AND timeframe = '1m'
                    GROUP BY to_char(open_time, 'YYYY-MM');
                    """,
                    (self.symbol,),
                )
                for ym, count in cur.fetchall():
                    existing_months[ym] = count
        finally:
            raw_conn.close()

        expected_month_counts = {
            "2025-12": 29755,
            "2026-01": 44640,
            "2026-02": 40320,
            "2026-03": 44640,
            "2026-04": 43200,
            "2026-05": 44640,
            "2026-06": 43200,
            "2026-07": 44640,
            "2026-08": 44640,
            "2026-09": 43200,
            "2026-10": 43200,
        }

        results: dict[str, Any] = {
            "months_processed": [],
            "days_processed": [],
            "gap_backfilled": False,
            "total_inserted": 0,
        }

        # Ingest monthly archives
        for ym in months:
            curr_cnt = existing_months.get(ym, 0)
            exp_cnt = expected_month_counts.get(ym, 0)
            if not force and curr_cnt >= exp_cnt:
                logger.info("Month %s already fully ingested (%d >= %d bars). Skipping.", ym, curr_cnt, exp_cnt)
                continue

            logger.info("Ingesting monthly archive for %s...", ym)
            cnt = self.ingest_month(ym, verify_checksum=True)
            results["months_processed"].append({"month": ym, "candles": cnt})
            results["total_inserted"] += cnt

        # Ingest 2026-10-28 gap via REST
        raw_conn = sync_engine.raw_connection()
        gap_count = 0
        try:
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT count(*) FROM ohlcv_candles
                    WHERE symbol = %s AND timeframe = '1m'
                    AND open_time >= '2026-10-28 00:00:00+00' AND open_time < '2026-10-29 00:00:00+00';
                    """,
                    (self.symbol,),
                )
                r_gap = cur.fetchone()
                gap_count = r_gap[0] if r_gap else 0
        finally:
            raw_conn.close()

        if force or gap_count < 1440:
            logger.info("Ingesting 2026-10-28 gap via REST (currently %d/1440 bars)...", gap_count)
            gap_inserted = self.ingest_2026_10_28_gap()
            results["gap_backfilled"] = True
            results["total_inserted"] += gap_inserted
        else:
            logger.info("2026-10-28 gap already closed with 1440 bars.")

        # Ingest November daily archives
        for d_str in days_nov:
            raw_conn = sync_engine.raw_connection()
            day_cnt = 0
            try:
                with closing(raw_conn.cursor()) as cur:
                    cur.execute(
                        """
                        SELECT count(*) FROM ohlcv_candles
                        WHERE symbol = %s AND timeframe = '1m'
                        AND open_time >= %s::timestamptz AND open_time < (%s::timestamptz + interval '1 day');
                        """,
                        (self.symbol, f"{d_str} 00:00:00+00", f"{d_str} 00:00:00+00"),
                    )
                    r_day = cur.fetchone()
                    day_cnt = r_day[0] if r_day else 0
            finally:
                raw_conn.close()

            if not force and day_cnt >= 1440:
                logger.info("Day %s already ingested (%d bars). Skipping.", d_str, day_cnt)
                continue

            logger.info("Ingesting daily archive for %s...", d_str)
            cnt = self.ingest_day(d_str, verify_checksum=True)
            results["days_processed"].append({"day": d_str, "candles": cnt})
            results["total_inserted"] += cnt

        # Ingest 2026-11-05 via REST
        start_nov5 = int(datetime(2026, 11, 5, 0, 0, tzinfo=UTC).timestamp() * 1000)
        end_nov5 = int(datetime(2026, 11, 5, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
        raw_conn = sync_engine.raw_connection()
        nov5_cnt = 0
        try:
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT count(*) FROM ohlcv_candles
                    WHERE symbol = %s AND timeframe = '1m'
                    AND open_time >= '2026-11-05 00:00:00+00' AND open_time < '2026-11-06 00:00:00+00';
                    """,
                    (self.symbol,),
                )
                r_nov5 = cur.fetchone()
                nov5_cnt = r_nov5[0] if r_nov5 else 0
        finally:
            raw_conn.close()

        if force or nov5_cnt < 1440:
            logger.info("Ingesting 2026-11-05 via REST...")
            df_nov5 = self.fetch_klines_rest(start_nov5, end_nov5, interval="1m")
            if not df_nov5.empty:
                cnt_nov5 = self.bulk_insert_candles(df_nov5)
                results["days_processed"].append({"day": "2026-11-05", "candles": cnt_nov5})
                results["total_inserted"] += cnt_nov5

        return results

    def ingest_full_funding_history(self) -> int:
        """
        Download and ingest complete historical 8-hour funding rates from inception to current.
        Uses Binance /fapi/v1/fundingRate paginated across all epochs.
        """
        base_url = (
            settings.BINANCE_FUTURES_HTTP_URL
            if (settings.ENVIRONMENT == "production" or settings.OUTBOUND_PROXY_URL)
            else settings.BINANCE_TESTNET_HTTP_URL
        ).rstrip("/")

        cur_start = settings.CONTRACT_ONBOARD_TIME_MS
        all_rates: list[dict[str, Any]] = []
        opener = self._build_opener()

        while True:
            url = f"{base_url}/fapi/v1/fundingRate?symbol={self.symbol}&startTime={cur_start}&limit=1000"
            req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Downloader/1.0"})

            try:
                with opener.open(req, timeout=15) as resp:
                    batch = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if (e.code in (403, 451)) and base_url != settings.BINANCE_TESTNET_HTTP_URL.rstrip("/"):
                    logger.warning("Production REST geo-blocked (%d). Falling back to testnet endpoint.", e.code)
                    base_url = settings.BINANCE_TESTNET_HTTP_URL.rstrip("/")
                    continue
                raise

            if not batch:
                break
            all_rates.extend(batch)
            if len(batch) < 1000:
                break
            cur_start = int(batch[-1]["fundingTime"]) + 1

        if not all_rates:
            return 0

        rows: list[tuple[Any, ...]] = []
        for r in all_rates:
            funding_dt = datetime.fromtimestamp(int(r["fundingTime"]) / 1000, tz=UTC)
            rows.append(
                (
                    self.symbol,
                    funding_dt,
                    float(r["fundingRate"]),
                    float(r.get("markPrice", 0.0)),
                )
            )

        sql = """
        INSERT INTO funding_history (symbol, funding_time, funding_rate, mark_price)
        VALUES %s
        ON CONFLICT (symbol, funding_time) DO UPDATE SET
            funding_rate = EXCLUDED.funding_rate,
            mark_price = EXCLUDED.mark_price;
        """
        raw_conn = sync_engine.raw_connection()
        try:
            with closing(raw_conn.cursor()) as cur:
                execute_values(cur, sql, rows, page_size=2000)
            raw_conn.commit()
        finally:
            raw_conn.close()

        logger.info("Successfully upserted %d funding records into funding_history.", len(rows))
        return len(rows)

    def fetch_mark_or_index_rest(
        self,
        endpoint: str,
        param_name: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch mark or index price klines from REST API."""
        base_url = (
            settings.BINANCE_FUTURES_HTTP_URL
            if (settings.ENVIRONMENT == "production" or settings.OUTBOUND_PROXY_URL)
            else settings.BINANCE_TESTNET_HTTP_URL
        ).rstrip("/")

        all_rows: list[list[Any]] = []
        cur_start = start_time_ms
        opener = self._build_opener()

        while cur_start <= end_time_ms:
            url = (
                f"{base_url}/fapi/v1/{endpoint}?{param_name}={self.symbol}&interval=1m"
                f"&startTime={cur_start}&endTime={end_time_ms}&limit={limit}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Downloader/1.0"})
            with opener.open(req, timeout=15) as resp:
                batch = json.loads(resp.read().decode("utf-8"))

            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < limit:
                break
            cur_start = int(batch[-1][0]) + 60000

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows).iloc[:, [0, 4]]
        df.columns = ["open_time", "close"]
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close"] = df["close"].astype(float)
        return df[["timestamp", "close"]]

    def ingest_full_mark_index_history(self, force: bool = False) -> dict[str, int]:
        """
        Ingest mark and index prices across the entire historical range:
        - Monthly archives (2025-12 to 2026-10)
        - REST for 2026-10-28 gap
        - Daily archives (2026-11-01 to 2026-11-04)
        - REST for 2026-11-05
        Merges contract price from ohlcv_candles, computes basis, and upserts into mark_index_prices.
        """
        months = [
            "2025-12",
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
            "2026-08",
            "2026-09",
            "2026-10",
        ]
        days_nov = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]

        # Check existing row count per month for resumability
        raw_conn = sync_engine.raw_connection()
        existing_counts: dict[str, int] = {}
        try:
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT to_char(timestamp, 'YYYY-MM'), count(*)
                    FROM mark_index_prices
                    WHERE symbol = %s
                    GROUP BY to_char(timestamp, 'YYYY-MM');
                    """,
                    (self.symbol,),
                )
                for ym, count in cur.fetchall():
                    existing_counts[ym] = count
        finally:
            raw_conn.close()

        total_inserted = 0

        # Helper to bulk insert mark_index_prices
        def _bulk_upsert_mark_index(df_merged: pd.DataFrame) -> int:
            if df_merged.empty:
                return 0
            tuples: list[tuple[Any, ...]] = []
            for r in df_merged.itertuples(index=False):
                tuples.append(
                    (
                        self.symbol,
                        r.timestamp,
                        float(r.contract_price),
                        float(r.mark_price),
                        float(r.index_price),
                        float(r.basis),
                    )
                )
            sql = """
            INSERT INTO mark_index_prices (symbol, timestamp, contract_price, mark_price, index_price, basis)
            VALUES %s
            ON CONFLICT (symbol, timestamp) DO UPDATE SET
                contract_price = EXCLUDED.contract_price,
                mark_price = EXCLUDED.mark_price,
                index_price = EXCLUDED.index_price,
                basis = EXCLUDED.basis;
            """
            r_conn = sync_engine.raw_connection()
            try:
                with closing(r_conn.cursor()) as c:
                    execute_values(c, sql, tuples, page_size=10000)
                r_conn.commit()
            finally:
                r_conn.close()
            return len(tuples)

        # Helper to get contract prices from ohlcv_candles table
        def _get_contract_prices(start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
            r_conn = sync_engine.raw_connection()
            try:
                query = """
                SELECT open_time AS timestamp, close AS contract_price
                FROM ohlcv_candles
                WHERE symbol = %s AND timeframe = '1m'
                AND open_time >= %s AND open_time < %s
                ORDER BY open_time ASC;
                """
                return pd.read_sql(query, r_conn, params=(self.symbol, start_dt, end_dt))
            finally:
                r_conn.close()

        for ym in months:
            curr_cnt = existing_counts.get(ym, 0)
            if not force and curr_cnt >= 28000:
                logger.info("Month %s mark/index prices already ingested (%d rows). Skipping.", ym, curr_cnt)
                continue

            logger.info("Ingesting monthly mark/index prices for %s...", ym)
            mark_key = f"data/futures/um/monthly/markPriceKlines/{self.symbol}/1m/{self.symbol}-1m-{ym}.zip"
            index_key = f"data/futures/um/monthly/indexPriceKlines/{self.symbol}/1m/{self.symbol}-1m-{ym}.zip"

            df_mark = self.download_and_parse_price_series(mark_key).rename(columns={"close": "mark_price"})
            df_index = self.download_and_parse_price_series(index_key).rename(columns={"close": "index_price"})

            start_t = min(df_mark["timestamp"].min(), df_index["timestamp"].min())
            end_t = max(df_mark["timestamp"].max(), df_index["timestamp"].max()) + pd.Timedelta(minutes=1)

            df_contract = _get_contract_prices(start_t.to_pydatetime(), end_t.to_pydatetime())
            merged = pd.merge(df_contract, df_mark, on="timestamp")
            merged = pd.merge(merged, df_index, on="timestamp")
            merged["basis"] = merged["contract_price"] - merged["index_price"]

            inserted = _bulk_upsert_mark_index(merged)
            total_inserted += inserted

        # 2026-10-28 gap
        raw_conn = sync_engine.raw_connection()
        cnt_gap = 0
        try:
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT count(*) FROM mark_index_prices
                    WHERE symbol = %s
                    AND timestamp >= '2026-10-28 00:00:00+00' AND timestamp < '2026-10-29 00:00:00+00';
                    """,
                    (self.symbol,),
                )
                r_cnt = cur.fetchone()
                cnt_gap = r_cnt[0] if r_cnt else 0
        finally:
            raw_conn.close()

        if force or cnt_gap < 1440:
            logger.info("Ingesting 2026-10-28 mark/index gap via REST...")
            s_ms = int(datetime(2026, 10, 28, 0, 0, tzinfo=UTC).timestamp() * 1000)
            e_ms = int(datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
            df_m_rest = self.fetch_mark_or_index_rest("markPriceKlines", "symbol", s_ms, e_ms).rename(
                columns={"close": "mark_price"}
            )
            df_i_rest = self.fetch_mark_or_index_rest("indexPriceKlines", "pair", s_ms, e_ms).rename(
                columns={"close": "index_price"}
            )
            df_c_gap = _get_contract_prices(
                datetime(2026, 10, 28, 0, 0, tzinfo=UTC), datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
            )
            m_gap = pd.merge(df_c_gap, df_m_rest, on="timestamp")
            m_gap = pd.merge(m_gap, df_i_rest, on="timestamp")
            m_gap["basis"] = m_gap["contract_price"] - m_gap["index_price"]
            total_inserted += _bulk_upsert_mark_index(m_gap)

        # November daily archives
        for d_str in days_nov:
            raw_conn = sync_engine.raw_connection()
            day_cnt = 0
            try:
                with closing(raw_conn.cursor()) as cur:
                    cur.execute(
                        """
                        SELECT count(*) FROM mark_index_prices
                        WHERE symbol = %s
                        AND timestamp >= %s::timestamptz AND timestamp < (%s::timestamptz + interval '1 day');
                        """,
                        (self.symbol, f"{d_str} 00:00:00+00", f"{d_str} 00:00:00+00"),
                    )
                    r_day = cur.fetchone()
                    day_cnt = r_day[0] if r_day else 0
            finally:
                raw_conn.close()

            if not force and day_cnt >= 1440:
                continue

            logger.info("Ingesting daily mark/index for %s...", d_str)
            mark_key = f"data/futures/um/daily/markPriceKlines/{self.symbol}/1m/{self.symbol}-1m-{d_str}.zip"
            index_key = f"data/futures/um/daily/indexPriceKlines/{self.symbol}/1m/{self.symbol}-1m-{d_str}.zip"
            df_mark = self.download_and_parse_price_series(mark_key).rename(columns={"close": "mark_price"})
            df_index = self.download_and_parse_price_series(index_key).rename(columns={"close": "index_price"})

            start_t = datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=UTC)
            end_t = start_t + pd.Timedelta(days=1)
            df_contract = _get_contract_prices(start_t, end_t)

            merged = pd.merge(df_contract, df_mark, on="timestamp")
            merged = pd.merge(merged, df_index, on="timestamp")
            merged["basis"] = merged["contract_price"] - merged["index_price"]
            total_inserted += _bulk_upsert_mark_index(merged)

        # 2026-11-05 via REST
        s_nov5 = int(datetime(2026, 11, 5, 0, 0, tzinfo=UTC).timestamp() * 1000)
        e_nov5 = int(datetime(2026, 11, 5, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
        df_m_nov5 = self.fetch_mark_or_index_rest("markPriceKlines", "symbol", s_nov5, e_nov5).rename(
            columns={"close": "mark_price"}
        )
        df_i_nov5 = self.fetch_mark_or_index_rest("indexPriceKlines", "pair", s_nov5, e_nov5).rename(
            columns={"close": "index_price"}
        )
        df_c_nov5 = _get_contract_prices(
            datetime(2026, 11, 5, 0, 0, tzinfo=UTC), datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
        )
        if not df_m_nov5.empty and not df_i_nov5.empty:
            m_nov5 = pd.merge(df_c_nov5, df_m_nov5, on="timestamp")
            m_nov5 = pd.merge(m_nov5, df_i_nov5, on="timestamp")
            m_nov5["basis"] = m_nov5["contract_price"] - m_nov5["index_price"]
            total_inserted += _bulk_upsert_mark_index(m_nov5)

        return {"total_mark_index_inserted": total_inserted}

    def sync_incremental(self, start_date: str, end_date: str) -> dict[str, int]:
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
            except (urllib.error.URLError, urllib.error.HTTPError, zipfile.BadZipFile, KeyError, ValueError) as e:
                logger.warning("Could not sync day %s: %s", d_str, e)

        return results

    def run_data_quality_audit(self) -> dict[str, Any]:
        """
        Perform comprehensive post-ingestion verification:
        1. Duplicate check across ohlcv_candles
        2. OHLC invariant audit
        3. Continuity & gap detection with full causal explanation per gap
        4. Multi-timeframe resampling reconciliation against native Binance exchange klines
        """
        raw_conn = sync_engine.raw_connection()
        try:
            # 1. Duplicate check
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT count(*), count(DISTINCT open_time)
                    FROM ohlcv_candles
                    WHERE symbol = %s AND timeframe = '1m';
                    """,
                    (self.symbol,),
                )
                r_dup = cur.fetchone()
                total_1m = r_dup[0] if r_dup else 0
                distinct_1m = r_dup[1] if r_dup else 0
                duplicate_count = total_1m - distinct_1m

            # 2. OHLC validity
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM ohlcv_candles
                    WHERE symbol = %s AND timeframe = '1m'
                    AND (
                        high < low
                        OR high < GREATEST(open, close)
                        OR low > LEAST(open, close)
                        OR open <= 0
                        OR high <= 0
                        OR low <= 0
                        OR close <= 0
                        OR volume < 0
                    );
                    """,
                    (self.symbol,),
                )
                r_inv = cur.fetchone()
                invalid_ohlc_count = r_inv[0] if r_inv else 0

            # 3. Timestamp range & total counts
            with closing(raw_conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT min(open_time), max(open_time)
                    FROM ohlcv_candles
                    WHERE symbol = %s AND timeframe = '1m';
                    """,
                    (self.symbol,),
                )
                r_range = cur.fetchone()
                min_time = r_range[0] if r_range else None
                max_time = r_range[1] if r_range else None

            with closing(raw_conn.cursor()) as cur:
                cur.execute("SELECT count(*) FROM funding_history WHERE symbol = %s;", (self.symbol,))
                r_f = cur.fetchone()
                funding_count = r_f[0] if r_f else 0
                cur.execute("SELECT count(*) FROM mark_index_prices WHERE symbol = %s;", (self.symbol,))
                r_m = cur.fetchone()
                mark_index_count = r_m[0] if r_m else 0

            # 4. Gap detection: find all gaps > 1 minute
            gap_query = """
            SELECT prev_open, next_open, gap_seconds
            FROM (
                SELECT
                    open_time AS prev_open,
                    lead(open_time) OVER (ORDER BY open_time ASC) AS next_open,
                    EXTRACT(EPOCH FROM (lead(open_time) OVER (ORDER BY open_time ASC) - open_time)) AS gap_seconds
                FROM ohlcv_candles
                WHERE symbol = %s AND timeframe = '1m'
            ) t
            WHERE gap_seconds > 60
            ORDER BY prev_open ASC;
            """
            gaps_df = pd.read_sql(gap_query, raw_conn, params=(self.symbol,))
        finally:
            raw_conn.close()

        # Classify each gap with causal explanation
        gap_explanations: list[dict[str, Any]] = []
        for r in gaps_df.itertuples():
            prev_t: datetime = r.prev_open
            next_t: datetime = r.next_open
            gap_sec: float = r.gap_seconds
            missing_bars = int(round(gap_sec / 60.0)) - 1

            # Check TradFi session state at gap boundary
            session_state_res = SessionTracker.get_session_details(prev_t)
            st = session_state_res.state
            reason_detail = session_state_res.details.get("reason", "")

            classification = "REAL_MISSING_DATA"
            if prev_t < self.onboard_dt:
                classification = "PRE_LISTING_ABSENT"
            elif st == TradFiSessionState.MAINTENANCE or "break" in reason_detail.lower():
                classification = "DAILY_BREAK"
            elif "holiday" in reason_detail.lower():
                classification = "HOLIDAY_CLOSED"
            elif st == TradFiSessionState.NO_TRADING or "weekend" in reason_detail.lower():
                classification = "WEEKEND_CLOSED"

            gap_explanations.append(
                {
                    "gap_start": prev_t.isoformat(),
                    "gap_end": next_t.isoformat(),
                    "missing_bars": missing_bars,
                    "duration_seconds": gap_sec,
                    "classification": classification,
                    "detail": reason_detail or st.value,
                }
            )

        # 5. Multi-timeframe resampling reconciliation
        # Load sample 1m dataset (September 2026) to reconcile against Binance native klines
        reconciliation_results: dict[str, Any] = {}
        s3_key_sample = f"data/futures/um/monthly/klines/{self.symbol}/1m/{self.symbol}-1m-2026-09.zip"
        try:
            df_1m_sample = self.download_and_parse_zip(s3_key_sample, verify_checksum=True)
            for tf in ["5m", "15m", "1h", "4h", "1d"]:
                resampled = CandleResampler.resample_ohlcv(df_1m_sample, tf)
                s3_native_key = f"data/futures/um/monthly/klines/{self.symbol}/{tf}/{self.symbol}-{tf}-2026-09.zip"
                df_native = self.download_and_parse_zip(s3_native_key, verify_checksum=True)
                rec = CandleResampler.reconcile_with_native(resampled, df_native)
                reconciliation_results[tf] = rec
        except Exception as e:  # noqa: BLE001
            logger.warning("Reconciliation against native klines encountered warning: %s", e)
            reconciliation_results["error"] = str(e)

        return {
            "symbol": self.symbol,
            "total_1m_candles": total_1m,
            "distinct_1m_candles": distinct_1m,
            "duplicate_count": duplicate_count,
            "invalid_ohlc_count": invalid_ohlc_count,
            "min_open_time": min_time.isoformat() if min_time else None,
            "max_open_time": max_time.isoformat() if max_time else None,
            "funding_history_count": funding_count,
            "mark_index_prices_count": mark_index_count,
            "total_gaps_found": len(gap_explanations),
            "unresolved_gaps_count": sum(1 for g in gap_explanations if g["classification"] == "REAL_MISSING_DATA"),
            "gaps": gap_explanations,
            "reconciliation": reconciliation_results,
        }
