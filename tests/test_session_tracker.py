"""
Unit tests for SessionTracker.
Validates session states: OPEN, DAILY_BREAK, and WEEKEND_CLOSED.
"""

from datetime import UTC, datetime

from backend.data.session_tracker import SessionTracker, TradFiSessionState


def test_session_tracker_states():
    # Wednesday 14:00 UTC -> Regular TradFi market OPEN
    wednesday_midday = datetime(2026, 10, 28, 14, 0, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_midday) == TradFiSessionState.OPEN
    assert SessionTracker.is_underlying_active(wednesday_midday) is True

    # Wednesday 22:30 UTC -> Daily maintenance pause (22:00 - 23:00 UTC)
    wednesday_maintenance = datetime(2026, 10, 28, 22, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_maintenance) == TradFiSessionState.DAILY_BREAK
    assert SessionTracker.is_underlying_active(wednesday_maintenance) is False

    # Friday 23:30 UTC -> Weekend closed (starts Friday 22:00 UTC)
    friday_night = datetime(2026, 10, 23, 23, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(friday_night) == TradFiSessionState.WEEKEND_CLOSED
    assert SessionTracker.is_underlying_active(friday_night) is False

    # Saturday 12:00 UTC -> Weekend closed
    saturday = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(saturday) == TradFiSessionState.WEEKEND_CLOSED
    assert SessionTracker.is_underlying_active(saturday) is False

    # Sunday 22:00 UTC -> Weekend closed (opens at 23:00 UTC)
    sunday_before_open = datetime(2026, 10, 25, 22, 0, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(sunday_before_open) == TradFiSessionState.WEEKEND_CLOSED

    # Sunday 23:15 UTC -> Market reopened
    sunday_after_open = datetime(2026, 10, 25, 23, 15, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(sunday_after_open) == TradFiSessionState.OPEN
    assert SessionTracker.is_underlying_active(sunday_after_open) is True
