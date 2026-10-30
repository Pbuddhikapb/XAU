"""
Resilient Async WebSocket Client for Binance USD-M Futures XAUUSDT.
Multiplexes real-time klines, mark price, best book ticker, and depth streams.
Features automatic exponential backoff reconnection, ping/pong heartbeat,
and live state tracking in PostgreSQL live_market_state.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, List, Optional
import websockets
from websockets.exceptions import ConnectionClosed

from sqlalchemy.dialects.postgresql import insert

from backend.config import settings
from backend.database import get_async_session
from backend.models.tables import LiveMarketState, OrderbookSnapshot, SystemHealth
from backend.data.session_tracker import SessionTracker

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """Async WebSocket manager for live Binance XAUUSDT futures streams."""

    def __init__(
        self,
        base_ws_url: Optional[str] = None,
        on_candle_close: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_state_update: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.base_url = (base_ws_url or settings.BINANCE_TESTNET_WS_URL).rstrip("/")
        self.symbol = settings.SYMBOL.lower()
        self.on_candle_close = on_candle_close
        self.on_state_update = on_state_update
        self.is_running = False
        self._stop_event = asyncio.Event()

        # Order book downsampling tracking
        self._last_orderbook_snapshot_time = 0.0
        self.snapshot_interval_sec = 5.0
        self.current_depth = {
            "bids": [],
            "asks": [],
            "imbalance_ratio": 0.5,
            "spread": 0.0,
            "top_cluster_bid": 0.0,
            "top_cluster_ask": 0.0,
        }

        # In-memory latest state buffer
        self.current_state = {
            "symbol": settings.SYMBOL.upper(),
            "last_price": 0.0,
            "mark_price": 0.0,
            "index_price": 0.0,
            "basis": 0.0,
            "funding_rate": 0.0,
            "next_funding_time": datetime.now(timezone.utc),
            "best_bid": 0.0,
            "best_ask": 0.0,
            "spread": 0.0,
            "tradfi_session_state": "OPEN",
            "last_update": datetime.now(timezone.utc),
        }

    def get_stream_url(self) -> str:
        """Construct multiplexed combined streams endpoint URL."""
        streams = [
            f"{self.symbol}@kline_1m",
            f"{self.symbol}@markPrice@1s",
            f"{self.symbol}@bookTicker",
            f"{self.symbol}@depth20@100ms",
        ]
        return f"{self.base_url}/stream?streams={'/'.join(streams)}"

    async def _handle_message(self, message: str) -> None:
        """Process incoming combined stream JSON payload."""
        try:
            payload = json.loads(message)
            stream_name = payload.get("stream", "")
            data = payload.get("data", {})

            now = datetime.now(timezone.utc)
            self.current_state["last_update"] = now
            self.current_state["tradfi_session_state"] = SessionTracker.get_session_state(now).value

            if "kline_1m" in stream_name:
                k = data.get("k", {})
                close_price = float(k.get("c", 0.0))
                self.current_state["last_price"] = close_price
                if self.current_state["index_price"] > 0:
                    self.current_state["basis"] = close_price - self.current_state["index_price"]

                # Check if 1m candle closed
                is_closed = k.get("x", False)
                if is_closed and self.on_candle_close:
                    await self._notify_candle_close(k)

            elif "markPrice" in stream_name:
                mark = float(data.get("p", 0.0))
                index = float(data.get("i", 0.0))
                funding = float(data.get("r", 0.0))
                next_funding_ms = int(data.get("T", 0))

                self.current_state["mark_price"] = mark
                self.current_state["index_price"] = index
                self.current_state["funding_rate"] = funding
                if next_funding_ms > 0:
                    self.current_state["next_funding_time"] = datetime.fromtimestamp(
                        next_funding_ms / 1000, tz=timezone.utc
                    )
                if self.current_state["last_price"] > 0 and index > 0:
                    self.current_state["basis"] = self.current_state["last_price"] - index

            elif "bookTicker" in stream_name:
                bid = float(data.get("b", 0.0))
                ask = float(data.get("a", 0.0))
                self.current_state["best_bid"] = bid
                self.current_state["best_ask"] = ask
                self.current_state["spread"] = round(ask - bid, 4)

            elif "depth" in stream_name:
                bids = data.get("b", [])
                asks = data.get("a", [])
                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    spread = round(max(0.0, best_ask - best_bid), 4)

                    total_bid_qty = sum(float(q) for _, q in bids)
                    total_ask_qty = sum(float(q) for _, q in asks)
                    total_qty = total_bid_qty + total_ask_qty
                    imbalance = round(total_bid_qty / total_qty, 4) if total_qty > 0 else 0.5

                    top_cluster_bid = max(float(q) for _, q in bids)
                    top_cluster_ask = max(float(q) for _, q in asks)

                    self.current_depth = {
                        "bids": bids,
                        "asks": asks,
                        "imbalance_ratio": imbalance,
                        "spread": spread,
                        "top_cluster_bid": top_cluster_bid,
                        "top_cluster_ask": top_cluster_ask,
                    }

                    # Periodic downsampled persistence (every 5 seconds)
                    current_epoch = now.timestamp()
                    if current_epoch - self._last_orderbook_snapshot_time >= self.snapshot_interval_sec:
                        self._last_orderbook_snapshot_time = current_epoch
                        asyncio.create_task(
                            self._persist_orderbook_snapshot(
                                now, bids, asks, imbalance, spread, top_cluster_bid, top_cluster_ask
                            )
                        )

            if self.on_state_update:
                res = self.on_state_update(self.current_state)
                if asyncio.iscoroutine(res):
                    await res

        except Exception as e:
            logger.error("Error processing stream message: %s", e)

    async def _notify_candle_close(self, k: Dict[str, Any]) -> None:
        """Notify registered listener on confirmed 1m candle close."""
        try:
            candle_dict = {
                "symbol": settings.SYMBOL.upper(),
                "timeframe": "1m",
                "open_time": datetime.fromtimestamp(int(k["t"]) / 1000, tz=timezone.utc),
                "close_time": datetime.fromtimestamp(int(k["T"]) / 1000, tz=timezone.utc),
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "quote_volume": float(k["q"]),
                "trades_count": int(k["n"]),
                "taker_buy_volume": float(k["V"]),
                "taker_buy_quote_volume": float(k["Q"]),
                "is_confirmed": True,
                "source": "binance_websocket",
            }
            if self.on_candle_close:
                res = self.on_candle_close(candle_dict)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as e:
            logger.error("Error dispatching on_candle_close: %s", e)

    async def persist_state_snapshot(self) -> None:
        """Upsert current market state snapshot to PostgreSQL live_market_state."""
        if self.current_state["last_price"] <= 0:
            return

        try:
            stmt = insert(LiveMarketState).values(
                symbol=self.current_state["symbol"],
                last_price=self.current_state["last_price"],
                mark_price=self.current_state["mark_price"],
                index_price=self.current_state["index_price"],
                basis=self.current_state["basis"],
                funding_rate=self.current_state["funding_rate"],
                next_funding_time=self.current_state["next_funding_time"],
                best_bid=self.current_state["best_bid"],
                best_ask=self.current_state["best_ask"],
                spread=self.current_state["spread"],
                tradfi_session_state=self.current_state["tradfi_session_state"],
                last_update=self.current_state["last_update"],
            ).on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "last_price": self.current_state["last_price"],
                    "mark_price": self.current_state["mark_price"],
                    "index_price": self.current_state["index_price"],
                    "basis": self.current_state["basis"],
                    "funding_rate": self.current_state["funding_rate"],
                    "next_funding_time": self.current_state["next_funding_time"],
                    "best_bid": self.current_state["best_bid"],
                    "best_ask": self.current_state["best_ask"],
                    "spread": self.current_state["spread"],
                    "tradfi_session_state": self.current_state["tradfi_session_state"],
                    "last_update": self.current_state["last_update"],
                }
            )

            async with get_async_session() as session:
                await session.execute(stmt)
        except Exception as e:
            logger.error("Failed to persist live market state: %s", e)

    async def _persist_orderbook_snapshot(
        self,
        timestamp: datetime,
        bids: List[List[str]],
        asks: List[List[str]],
        imbalance: float,
        spread: float,
        top_cluster_bid: float,
        top_cluster_ask: float,
    ) -> None:
        """Persist a downsampled order-book depth snapshot to orderbook_snapshots table."""
        try:
            stmt = insert(OrderbookSnapshot).values(
                symbol=self.symbol.upper(),
                timestamp=timestamp,
                bid_depth_json=bids,
                ask_depth_json=asks,
                imbalance_ratio=imbalance,
                spread=spread,
                top_cluster_bid=top_cluster_bid,
                top_cluster_ask=top_cluster_ask,
            ).on_conflict_do_nothing(
                index_elements=["symbol", "timestamp"]
            )
            async with get_async_session() as session:
                await session.execute(stmt)
        except Exception as e:
            logger.debug("Orderbook snapshot insert suppressed: %s", e)

    async def run(self) -> None:
        """Main connection and auto-reconnection loop."""
        self.is_running = True
        self._stop_event.clear()
        reconnect_delay = 1
        max_reconnect_delay = 60

        while self.is_running and not self._stop_event.is_set():
            url = self.get_stream_url()
            logger.info("Connecting to WebSocket: %s", url)

            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    logger.info("WebSocket connected successfully to %s", self.symbol)
                    reconnect_delay = 1

                    while self.is_running and not self._stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            await self._handle_message(msg)
                        except asyncio.TimeoutError:
                            continue

                    try:
                        await asyncio.wait_for(ws.close(), timeout=1.5)
                    except Exception:
                        pass

            except ConnectionClosed as e:
                logger.warning("WebSocket connection closed: %s. Reconnecting in %ss...", e, reconnect_delay)
            except Exception as e:
                logger.error("WebSocket unexpected error: %s. Reconnecting in %ss...", e, reconnect_delay)

            if self.is_running and not self._stop_event.is_set():
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

        logger.info("WebSocket client stopped.")

    def stop(self) -> None:
        """Signal client to stop gracefully."""
        self.is_running = False
        self._stop_event.set()
