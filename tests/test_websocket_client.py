"""
Integration tests for BinanceWebSocketClient.
Connects to live testnet stream for XAUUSDT, receives frames, and verifies state updates.
"""

import asyncio
import pytest

from backend.data.websocket_client import BinanceWebSocketClient


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
    await asyncio.sleep(1.2)  # Allow timeout loop to exit cleanly
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert len(received_state_updates) > 0, "Failed to receive live WebSocket stream updates"
    latest = received_state_updates[-1]
    assert latest["symbol"] == "XAUUSDT"
    assert latest["mark_price"] > 0 or latest["last_price"] > 0 or latest["best_bid"] > 0
    assert "imbalance_ratio" in client.current_depth
