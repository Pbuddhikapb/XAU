"""
TradFi Gold Market Session State Tracker.
Monitors underlying commodity market hours (LBMA / COMEX / dxFeed / Massive)
to distinguish active gold discovery from frozen index / weekend cryptocurrency trading.
"""

from datetime import UTC, datetime, time
from enum import StrEnum


class TradFiSessionState(StrEnum):
    OPEN = "OPEN"
    DAILY_BREAK = "DAILY_BREAK"
    WEEKEND_CLOSED = "WEEKEND_CLOSED"
    HOLIDAY_CLOSED = "HOLIDAY_CLOSED"


class SessionTracker:
    """Tracks TradFi physical/futures gold trading hours in UTC."""

    @staticmethod
    def get_session_state(dt: datetime | None = None) -> TradFiSessionState:
        """
        Determine TradFi physical gold market status at a given UTC datetime.
        Standard Gold Trading Hours:
        - Week starts: Sunday 23:00 UTC.
        - Week ends: Friday 22:00 UTC.
        - Daily break: Monday through Thursday 22:00 - 23:00 UTC.
        """
        if dt is None:
            dt = datetime.now(UTC)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        weekday = dt.weekday()  # Monday=0, Tuesday=1, ... Friday=4, Saturday=5, Sunday=6
        current_time = dt.time()

        # Weekend closure: Friday after 22:00 UTC through Sunday before 23:00 UTC
        if weekday == 4 and current_time >= time(22, 0):  # Friday night
            return TradFiSessionState.WEEKEND_CLOSED
        if weekday == 5:  # Saturday full day
            return TradFiSessionState.WEEKEND_CLOSED
        if weekday == 6 and current_time < time(23, 0):  # Sunday before 23:00 UTC
            return TradFiSessionState.WEEKEND_CLOSED

        # Daily maintenance pause: Monday to Thursday 22:00 - 23:00 UTC
        if weekday in (0, 1, 2, 3) and (time(22, 0) <= current_time < time(23, 0)):
            return TradFiSessionState.DAILY_BREAK

        return TradFiSessionState.OPEN

    @staticmethod
    def is_underlying_active(dt: datetime | None = None) -> bool:
        """True only if underlying institutional gold feeds (dxfeed/massive) are actively quoting."""
        return SessionTracker.get_session_state(dt) == TradFiSessionState.OPEN
