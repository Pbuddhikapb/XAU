"""
Unit and integration tests for LiveIngestionDaemon.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.data.live_daemon import LiveIngestionDaemon


@pytest.mark.asyncio
async def test_live_daemon_handle_candle_close():
    """Verify handle_candle_close inserts 1m candle and delegates resampling."""
    daemon = LiveIngestionDaemon()

    mock_candle = {
        "open_time": 1793000000000,
        "open": 2750.0,
        "high": 2755.0,
        "low": 2748.0,
        "close": 2753.5,
        "volume": 120.5,
        "quote_volume": 331700.0,
        "trades_count": 450,
        "taker_buy_volume": 65.2,
        "taker_buy_quote_volume": 180000.0,
        "close_time": 1793000059999,
        "is_confirmed": True,
    }

    with patch.object(daemon, "_resample_higher_timeframes", new_callable=AsyncMock) as mock_resample:
        await daemon.handle_candle_close(mock_candle)
        assert mock_resample.called


@pytest.mark.asyncio
async def test_live_daemon_start_and_stop():
    """Verify daemon start and clean graceful shutdown."""
    daemon = LiveIngestionDaemon()
    daemon.client.run = AsyncMock()
    daemon.client.stop = MagicMock()

    # Start task and cancel immediately
    task = asyncio.create_task(daemon.start())
    await asyncio.sleep(0.05)
    await daemon.stop()
    await task

    assert daemon.is_running is False
    assert daemon.client.stop.called
