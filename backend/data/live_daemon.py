"""
Dedicated Live Ingestion Daemon for Binance Futures XAUUSDT.
Runs as a standalone systemd daemon (xau-ingestion.service).
Continuously ingests live klines and order book frames via Binance WebSocket,
persists live market state, aggregates multi-timeframe candles (5M, 15M, 1H, 4H, 1D, 1D_CME),
and executes periodic REST gap checks to guarantee <180s freshness.
"""

import asyncio
import logging
import signal
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.data.historical_downloader import HistoricalDownloader
from backend.data.resampler import CandleResampler
from backend.data.websocket_client import BinanceWebSocketClient
from backend.database import async_engine, get_async_session
from backend.models.tables import OHLCVCandle

logger = logging.getLogger("xau.ingestion_daemon")


class LiveIngestionDaemon:
    """Standalone live market data supervisor maintaining continuous data flow into PostgreSQL."""

    def __init__(self) -> None:
        ws_url = (
            settings.BINANCE_FUTURES_WS_URL
            if (settings.ENVIRONMENT == "production" or settings.OUTBOUND_PROXY_URL)
            else settings.BINANCE_TESTNET_WS_URL
        )
        self.client = BinanceWebSocketClient(
            base_ws_url=ws_url,
            on_candle_close=self.handle_candle_close,
            on_state_update=self.handle_state_update,
        )
        self.downloader = HistoricalDownloader()
        self.is_running = False
        self._stop_event = asyncio.Event()
        self._gap_task: asyncio.Task[None] | None = None

    async def handle_state_update(self, state: dict[str, Any]) -> None:
        """Handle real-time price state updates from Binance stream."""
        logger.debug(f"State update: Last ${state.get('last_price')} Mark ${state.get('mark_price')}")

    async def handle_candle_close(self, candle_data: dict[str, Any]) -> None:
        """
        Invoked when a 1-minute candle completes.
        Persists 1m candle into PostgreSQL and resamples higher timeframes.
        """
        try:
            ot = candle_data["open_time"]
            if isinstance(ot, datetime):
                open_dt = ot if ot.tzinfo else ot.replace(tzinfo=UTC)
            else:
                open_dt = datetime.fromtimestamp(float(ot) / 1000, tz=UTC)

            ct = candle_data["close_time"]
            if isinstance(ct, datetime):
                close_dt = ct if ct.tzinfo else ct.replace(tzinfo=UTC)
            else:
                close_dt = datetime.fromtimestamp(float(ct) / 1000, tz=UTC)

            # 1. Upsert 1m candle
            async with get_async_session() as session:
                stmt = insert(OHLCVCandle).values(
                    symbol=settings.SYMBOL,
                    timeframe="1m",
                    open_time=open_dt,
                    open=candle_data["open"],
                    high=candle_data["high"],
                    low=candle_data["low"],
                    close=candle_data["close"],
                    volume=candle_data["volume"],
                    quote_volume=candle_data.get("quote_volume", 0.0),
                    trades_count=candle_data.get("trades_count", 0),
                    taker_buy_volume=candle_data.get("taker_buy_volume", 0.0),
                    taker_buy_quote_volume=candle_data.get("taker_buy_quote_volume", 0.0),
                    close_time=close_dt,
                    is_confirmed=True,
                    source=candle_data.get("source", "binance_websocket"),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "timeframe", "open_time"],
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                        "quote_volume": stmt.excluded.quote_volume,
                        "trades_count": stmt.excluded.trades_count,
                        "taker_buy_volume": stmt.excluded.taker_buy_volume,
                        "taker_buy_quote_volume": stmt.excluded.taker_buy_quote_volume,
                        "close_time": stmt.excluded.close_time,
                        "is_confirmed": True,
                        "source": stmt.excluded.source,
                    },
                )
                await session.execute(stmt)
                await session.commit()

            logger.info(f"Committed 1m candle for {open_dt.isoformat()} @ Close ${candle_data['close']}")

            # 2. Resample higher timeframes if on boundary
            await self._resample_higher_timeframes(open_dt)

        except Exception as e:
            logger.error(f"Error handling 1m candle close: {e}", exc_info=True)

    async def _resample_higher_timeframes(self, latest_1m_open: datetime) -> None:
        """Aggregate recently completed higher timeframe bars from recent 1m candles."""
        # Query past 24 hours of 1m candles to compute higher timeframe bars
        async with get_async_session() as session:
            stmt = (
                select(OHLCVCandle)
                .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == "1m")
                .order_by(desc(OHLCVCandle.open_time))
                .limit(1500)
            )
            res = await session.execute(stmt)
            candles = list(reversed(res.scalars().all()))

        if len(candles) < 60:
            return

        df_1m = pd.DataFrame(
            [
                {
                    "open_time": c.open_time,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                    "quote_volume": float(c.quote_volume),
                    "trades_count": int(c.trades_count),
                    "taker_buy_volume": float(c.taker_buy_volume),
                    "close_time": c.close_time,
                }
                for c in candles
            ]
        )

        # Collect statements to upsert across all timeframes in a single batched transaction
        upsert_stmts = []
        for tf in ["5m", "15m", "1h", "4h", "1d", "1d_cme"]:
            try:
                resampled = CandleResampler.resample_ohlcv(df_1m, target_timeframe=tf, symbol=settings.SYMBOL)
                if not resampled.empty:
                    latest_bar = resampled.iloc[-1]
                    up_stmt = insert(OHLCVCandle).values(
                        symbol=settings.SYMBOL,
                        timeframe=tf,
                        open_time=latest_bar["open_time"],
                        open=latest_bar["open"],
                        high=latest_bar["high"],
                        low=latest_bar["low"],
                        close=latest_bar["close"],
                        volume=latest_bar["volume"],
                        quote_volume=latest_bar.get("quote_volume", 0.0),
                        trades_count=int(latest_bar.get("trades_count", 0)),
                        taker_buy_volume=latest_bar.get("taker_buy_volume", 0.0),
                        taker_buy_quote_volume=latest_bar.get("taker_buy_quote_volume", 0.0),
                        close_time=latest_bar["close_time"],
                        is_confirmed=True,
                    )
                    up_stmt = up_stmt.on_conflict_do_update(
                        index_elements=["symbol", "timeframe", "open_time"],
                        set_={
                            "open": up_stmt.excluded.open,
                            "high": up_stmt.excluded.high,
                            "low": up_stmt.excluded.low,
                            "close": up_stmt.excluded.close,
                            "volume": up_stmt.excluded.volume,
                            "quote_volume": up_stmt.excluded.quote_volume,
                            "trades_count": up_stmt.excluded.trades_count,
                            "taker_buy_volume": up_stmt.excluded.taker_buy_volume,
                            "taker_buy_quote_volume": up_stmt.excluded.taker_buy_quote_volume,
                            "close_time": up_stmt.excluded.close_time,
                            "is_confirmed": True,
                        },
                    )
                    upsert_stmts.append(up_stmt)
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f"Error updating resampled timeframe {tf}: {e}")

        if upsert_stmts:
            try:
                async with get_async_session() as session:
                    for up_s in upsert_stmts:
                        await session.execute(up_s)
                    await session.commit()
            except SQLAlchemyError as e:
                logger.error(f"Error persisting resampled timeframe batch: {e}")

    async def _gap_checker_loop(self, interval_seconds: float = 300.0) -> None:
        """Periodic background reconciler checking for missed bars via REST API."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(interval_seconds)
                logger.info("Executing periodic 5-minute REST gap reconciliation...")
                # Download recent 1m candles from REST to reconcile any WebSocket drops
                now_ms = int(datetime.now(UTC).timestamp() * 1000)
                start_ms = now_ms - (60 * 60 * 1000)
                df_recent = await asyncio.to_thread(
                    self.downloader.fetch_klines_rest,
                    start_time_ms=start_ms,
                    end_time_ms=now_ms,
                    interval="1m",
                    limit=100,
                )
                if not df_recent.empty:
                    inserted = await asyncio.to_thread(
                        self.downloader.bulk_insert_candles,
                        df_recent
                    )
                    logger.info(f"Reconciled {inserted} recent 1m bars via REST gap check.")
            except asyncio.CancelledError:
                break
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.error(f"Error in gap checker loop: {e}")

    async def start(self) -> None:
        """Start the ingestion daemon and supervise tasks."""
        self.is_running = True
        logger.info("Starting Live Ingestion Daemon for XAUUSDT...")

        # Start periodic gap reconciler
        self._gap_task = asyncio.create_task(self._gap_checker_loop())

        # Start WebSocket stream
        try:
            await self.client.run()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully stop WebSocket and background tasks."""
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()

        if self._gap_task:
            self._gap_task.cancel()
            try:
                await self._gap_task
            except asyncio.CancelledError:
                pass
            self._gap_task = None

        self.client.stop()
        await async_engine.dispose()
        logger.info("Live Ingestion Daemon stopped.")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    daemon = LiveIngestionDaemon()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(daemon.stop()))
        except NotImplementedError:
            pass

    await daemon.start()


if __name__ == "__main__":
    asyncio.run(main())
