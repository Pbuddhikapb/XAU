"""
Unit and integration tests for TelemetryHub and /ws/telemetry WebSocket endpoint.
"""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.telemetry.websocket_hub import TelemetryHub


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_websocket_telemetry_connection_and_ping(client):
    """Test connecting to /ws/telemetry, receiving ack, and ping/pong."""
    with client.websocket_connect("/ws/telemetry") as websocket:
        # First message should be connection_ack
        ack_data = websocket.receive_text()
        ack = json.loads(ack_data)
        assert ack["topic"] == "connection_ack"
        assert ack["data"]["status"] == "connected"
        assert ack["data"]["symbol"] == "XAUUSDT"

        # Send ping
        websocket.send_text("ping")
        pong = websocket.receive_text()
        assert pong == "pong"


@pytest.mark.asyncio
async def test_telemetry_hub_register_broadcast_unregister():
    """Test TelemetryHub direct lifecycle, message broadcast, and exception resilience."""
    hub = TelemetryHub()
    mock_ws = AsyncMock()

    # Register
    await hub.register(mock_ws)
    assert mock_ws in hub.active_connections
    assert mock_ws.accept.called

    # Broadcast
    payload = {"price": 2750.50, "direction": "BULLISH"}
    await hub.broadcast("market_tick", payload)
    assert mock_ws.send_text.called

    # Verify message contents
    call_args = mock_ws.send_text.call_args[0][0]
    data = json.loads(call_args)
    assert data["topic"] == "market_tick"
    assert data["data"] == payload

    # Heartbeat loop execution
    await hub.start_heartbeat(interval_seconds=0.05)
    assert hub._heartbeat_task is not None
    await hub.stop_heartbeat()
    assert hub._heartbeat_task is None

    # Unregister
    await hub.unregister(mock_ws)
    assert mock_ws not in hub.active_connections
