"""
WebSocket Telemetry Hub for Binance XAUUSDT Market Intelligence System.
Multiplexes real-time market ticks, candle updates, Engine A analysis,
Engine B trade setup transitions, and system heartbeats to connected clients.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TelemetryHub:
    """Manages active client WebSocket connections and broadcasts real-time telemetry frames."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def register(self, websocket: WebSocket) -> None:
        """Accept and register a new client connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

        # Send initial connection acknowledgment & heartbeat
        await self.send_personal(
            websocket,
            topic="connection_ack",
            payload={
                "status": "connected",
                "server_time": datetime.now(UTC).isoformat(),
                "symbol": "XAUUSDT",
            },
        )

    async def unregister(self, websocket: WebSocket) -> None:
        """Unregister a client connection."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def send_personal(self, websocket: WebSocket, topic: str, payload: dict[str, Any]) -> None:
        """Send a single typed JSON frame to a specific client."""
        frame = {
            "topic": topic,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": payload,
        }
        try:
            await websocket.send_text(json.dumps(frame))
        except (RuntimeError, OSError) as e:
            logger.warning(f"Failed to send message to client: {e}")

    async def broadcast(self, topic: str, payload: dict[str, Any]) -> None:
        """Broadcast a typed JSON frame to all active connections."""
        if not self.active_connections:
            return

        frame = json.dumps(
            {
                "topic": topic,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": payload,
            }
        )

        dead_connections: list[WebSocket] = []
        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(frame)
                except (RuntimeError, OSError):
                    dead_connections.append(connection)

            for dead in dead_connections:
                self.active_connections.discard(dead)

    async def start_heartbeat(self, interval_seconds: float = 10.0) -> None:
        """Start periodic heartbeat task if not already running."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval_seconds))

    async def stop_heartbeat(self) -> None:
        """Stop periodic heartbeat task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _heartbeat_loop(self, interval: float) -> None:
        """Emit periodic heartbeat frames to keep active client connections alive."""
        while True:
            try:
                await asyncio.sleep(interval)
                if self.active_connections:
                    await self.broadcast(
                        topic="heartbeat",
                        payload={
                            "server_time": datetime.now(UTC).isoformat(),
                            "clients_count": len(self.active_connections),
                        },
                    )
            except asyncio.CancelledError:
                break
            except (RuntimeError, OSError) as e:
                logger.error(f"Error in telemetry heartbeat loop: {e}")


# Global singleton instance
telemetry_hub = TelemetryHub()
