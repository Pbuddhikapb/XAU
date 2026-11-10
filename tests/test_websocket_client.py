"""
Integration tests for BinanceWebSocketClient.
Connects to live testnet stream for XAUUSDT, receives frames, and verifies state updates.
"""

import asyncio
import contextlib

import pytest

from backend.data.websocket_client import BinanceWebSocketClient
from backend.database import async_engine


@pytest.mark.asyncio
async def test_websocket_client_receives_live_stream():
    client = BinanceWebSocketClient()
    received_state_updates = []

    async def on_state_update(state):
        if state["last_price"] > 0 or state["mark_price"] > 0 or state["best_bid"] > 0:
            received_state_updates.append(dict(state))

    client.on_state_update = on_state_update

    task = asyncio.create_task(client.run())

    # Poll for incoming updates with up to 10 seconds timeout
    for _ in range(100):
        await asyncio.sleep(0.1)
        if len(received_state_updates) > 0:
            break

    client.stop()
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        await async_engine.dispose()

    assert len(received_state_updates) > 0, "Failed to receive live WebSocket stream updates"
    latest = received_state_updates[-1]
    assert latest["symbol"] == "XAUUSDT"
    assert latest["mark_price"] > 0 or latest["last_price"] > 0 or latest["best_bid"] > 0
    assert "imbalance_ratio" in client.current_depth


@pytest.mark.asyncio
async def test_websocket_client_throttling_logic():
    """Verify session tracking and state persistence throttling intervals."""
    from unittest.mock import AsyncMock

    client = BinanceWebSocketClient()
    client.persist_state_snapshot = AsyncMock()  # type: ignore[method-assign]

    dummy_msg = '{"stream": "xauusdt@bookTicker", "data": {"b": "2700.1", "a": "2700.2"}}'

    # Send 10 messages within same second
    for _ in range(10):
        await client._handle_message(dummy_msg)

    # State snapshot should only be dispatched at most once within 1.0s interval
    assert client.persist_state_snapshot.call_count <= 1

