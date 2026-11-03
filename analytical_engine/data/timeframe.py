"""
Timeframe specifications, boundary alignment, and interval calculations.
"""

from datetime import UTC, datetime
from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


# Standard duration in seconds for each primary timeframe
TIMEFRAME_SECONDS: dict[str, int] = {
    Timeframe.M1.value: 60,
    Timeframe.M5.value: 300,
    Timeframe.M15.value: 900,
    Timeframe.H1.value: 3600,
    Timeframe.H4.value: 14400,
    Timeframe.D1.value: 86400,
}

# Number of 1-minute foundation bars expected in a complete higher-timeframe bar
EXPECTED_1M_BARS: dict[str, int] = {
    Timeframe.M1.value: 1,
    Timeframe.M5.value: 5,
    Timeframe.M15.value: 15,
    Timeframe.H1.value: 60,
    Timeframe.H4.value: 240,
    Timeframe.D1.value: 1440,
}


def get_timeframe_seconds(timeframe: str) -> int:
    """Return interval duration in seconds for a supported timeframe string."""
    tf_str = timeframe.lower()
    if tf_str not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {list(TIMEFRAME_SECONDS.keys())}")
    return TIMEFRAME_SECONDS[tf_str]


def get_expected_1m_count(timeframe: str) -> int:
    """Return expected number of 1-minute bars for a complete higher-timeframe bar."""
    tf_str = timeframe.lower()
    if tf_str not in EXPECTED_1M_BARS:
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {list(EXPECTED_1M_BARS.keys())}")
    return EXPECTED_1M_BARS[tf_str]


def align_to_timeframe_boundary(ts: datetime, timeframe: str) -> datetime:
    """
    Floor a UTC datetime to the start boundary of the specified timeframe.
    All boundaries are strictly UTC-aligned.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)

    epoch_seconds = int(ts.timestamp())
    seconds = get_timeframe_seconds(timeframe)
    floored_seconds = (epoch_seconds // seconds) * seconds
    return datetime.fromtimestamp(floored_seconds, tz=UTC)


def get_candle_close_time(open_time: datetime, timeframe: str) -> datetime:
    """
    Calculate the exact close timestamp of a candle interval given its open time.
    e.g., for 1m bar opening at 08:00:00, close is 08:00:59.999... or boundary 08:01:00.
    """
    seconds = get_timeframe_seconds(timeframe)
    close_epoch = int(open_time.timestamp()) + seconds
    return datetime.fromtimestamp(close_epoch, tz=UTC)
