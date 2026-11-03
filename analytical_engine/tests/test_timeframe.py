"""
Tests for timeframe definitions, seconds conversion, and boundary alignment.
"""

from datetime import UTC, datetime

import pytest

from analytical_engine.data.timeframe import (
    align_to_timeframe_boundary,
    get_candle_close_time,
    get_expected_1m_count,
    get_timeframe_seconds,
)


def test_timeframe_seconds():
    """Verify standard durations in seconds for supported timeframes."""
    assert get_timeframe_seconds("1m") == 60
    assert get_timeframe_seconds("5m") == 300
    assert get_timeframe_seconds("15m") == 900
    assert get_timeframe_seconds("1h") == 3600
    assert get_timeframe_seconds("4h") == 14400
    assert get_timeframe_seconds("1d") == 86400

    with pytest.raises(ValueError):
        get_timeframe_seconds("3m")


def test_expected_1m_count():
    """Verify expected 1m constituent counts."""
    assert get_expected_1m_count("1m") == 1
    assert get_expected_1m_count("5m") == 5
    assert get_expected_1m_count("15m") == 15
    assert get_expected_1m_count("1h") == 60
    assert get_expected_1m_count("4h") == 240
    assert get_expected_1m_count("1d") == 1440


def test_align_to_timeframe_boundary():
    """Verify UTC boundary alignment floor calculations."""
    # 2026-10-30 14:23:45 UTC
    ts = datetime(2026, 10, 30, 14, 23, 45, tzinfo=UTC)

    # 5m floor -> 14:20:00
    assert align_to_timeframe_boundary(ts, "5m") == datetime(2026, 10, 30, 14, 20, 0, tzinfo=UTC)

    # 15m floor -> 14:15:00
    assert align_to_timeframe_boundary(ts, "15m") == datetime(2026, 10, 30, 14, 15, 0, tzinfo=UTC)

    # 1h floor -> 14:00:00
    assert align_to_timeframe_boundary(ts, "1h") == datetime(2026, 10, 30, 14, 0, 0, tzinfo=UTC)

    # 4h floor -> 12:00:00 (since 14 // 4 * 4 = 12)
    assert align_to_timeframe_boundary(ts, "4h") == datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)

    # 1d floor -> 00:00:00
    assert align_to_timeframe_boundary(ts, "1d") == datetime(2026, 10, 30, 0, 0, 0, tzinfo=UTC)


def test_candle_close_time():
    """Verify calculation of candle close boundaries."""
    open_ts = datetime(2026, 10, 30, 14, 0, 0, tzinfo=UTC)
    assert get_candle_close_time(open_ts, "1h") == datetime(2026, 10, 30, 15, 0, 0, tzinfo=UTC)
    assert get_candle_close_time(open_ts, "5m") == datetime(2026, 10, 30, 14, 5, 0, tzinfo=UTC)
