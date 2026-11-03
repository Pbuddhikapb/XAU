"""
TradFi Gold Market Session State Tracker and Schedule Provider Architecture.
Monitors underlying commodity market hours (LBMA / COMEX / Binance COMMODITY)
to distinguish active gold price discovery from frozen index / weekend trading.

Architecture conforms to Section 4 & 5 of PROJECT_SPECIFICATION.md and Pre-Phase 4 Audit:
1. ScheduleProvider abstraction separating exchange schedule from fallback.
2. Preference for authentic Binance exchange tradingSchedule when available.
3. Explicit session states: REGULAR, NO_TRADING, MAINTENANCE, UNKNOWN.
4. Timezone-aware handling with dynamic US Daylight Saving Time (EDT vs EST) accounting.
5. Explicit uncertainty tracking for fallback-derived or stale schedule states.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
import logging
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# CME Globex Gold Futures operating calendar in US Eastern Time
CME_TIMEZONE = ZoneInfo("America/New_York")


class TradFiSessionState(StrEnum):
    REGULAR = "REGULAR"          # Active order-matching and price discovery
    NO_TRADING = "NO_TRADING"    # Weekend / scheduled market closure
    MAINTENANCE = "MAINTENANCE"  # Daily maintenance break or exchange technical pause
    UNKNOWN = "UNKNOWN"          # Unresolvable schedule / missing data

    # Backward compatibility aliases
    OPEN = "REGULAR"
    DAILY_BREAK = "MAINTENANCE"
    WEEKEND_CLOSED = "NO_TRADING"
    HOLIDAY_CLOSED = "NO_TRADING"


@dataclass(frozen=True)
class SessionStateResult:
    """Detailed audit representation of evaluated session state."""
    state: TradFiSessionState
    source: str                      # "binance_schedule_api" | "fallback_cme_calendar"
    is_uncertain: bool               # True if derived from fallback, stale, or unverified schedule
    retrieval_timestamp: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "source": self.source,
            "is_uncertain": self.is_uncertain,
            "retrieval_timestamp": self.retrieval_timestamp.isoformat() if self.retrieval_timestamp else None,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "details": self.details,
        }


class ScheduleProvider(ABC):
    """Abstract base provider for instrument trading schedules."""

    @abstractmethod
    def get_session_state(self, dt: datetime) -> SessionStateResult:
        """Evaluate session state at a given UTC datetime."""
        pass


class FallbackScheduleProvider(ScheduleProvider):
    """
    Timezone-aware fallback provider using the CME Globex Gold Futures operating calendar.
    Evaluates trading hours in America/New_York time to automatically handle US DST shifts:
    - Friday 17:00 ET to Sunday 18:00 ET: NO_TRADING (Weekend close)
    - Monday through Thursday 17:00 to 18:00 ET: MAINTENANCE (Daily settlement break)
    - All other times: REGULAR (Active trading)

    Always marks results as is_uncertain=True because fallback cannot observe
    unscheduled Binance maintenance or exchange-specific holiday calendar changes.
    """

    def get_session_state(self, dt: datetime) -> SessionStateResult:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)

        ny_dt = dt.astimezone(CME_TIMEZONE)
        weekday = ny_dt.weekday()  # Monday=0, Tuesday=1, ... Friday=4, Saturday=5, Sunday=6
        current_time = ny_dt.time()

        limitations_msg = (
            "Derived from CME Globex New York calendar fallback. "
            "Does not capture dynamic Binance-specific maintenance or unscheduled exchange halts."
        )

        # Saturday: Closed full day
        if weekday == 5:
            return SessionStateResult(
                state=TradFiSessionState.NO_TRADING,
                source="fallback_cme_calendar",
                is_uncertain=True,
                retrieval_timestamp=None,
                valid_from=None,
                valid_until=None,
                details={"reason": "Saturday full-day weekend closure", "limitations": limitations_msg},
            )

        # Sunday: Closed until 18:00 ET
        if weekday == 6:
            if current_time < time(18, 0):
                return SessionStateResult(
                    state=TradFiSessionState.NO_TRADING,
                    source="fallback_cme_calendar",
                    is_uncertain=True,
                    retrieval_timestamp=None,
                    valid_from=None,
                    valid_until=None,
                    details={"reason": "Sunday pre-open weekend closure", "limitations": limitations_msg},
                )
            return SessionStateResult(
                state=TradFiSessionState.REGULAR,
                source="fallback_cme_calendar",
                is_uncertain=True,
                retrieval_timestamp=None,
                valid_from=None,
                valid_until=None,
                details={"reason": "Sunday market reopened for weekly trading", "limitations": limitations_msg},
            )

        # Friday: Closes at 17:00 ET for the weekend
        if weekday == 4:
            if current_time >= time(17, 0):
                return SessionStateResult(
                    state=TradFiSessionState.NO_TRADING,
                    source="fallback_cme_calendar",
                    is_uncertain=True,
                    retrieval_timestamp=None,
                    valid_from=None,
                    valid_until=None,
                    details={"reason": "Friday post-close weekend closure", "limitations": limitations_msg},
                )
            return SessionStateResult(
                state=TradFiSessionState.REGULAR,
                source="fallback_cme_calendar",
                is_uncertain=True,
                retrieval_timestamp=None,
                valid_from=None,
                valid_until=None,
                details={"reason": "Friday regular trading session", "limitations": limitations_msg},
            )

        # Monday through Thursday (0, 1, 2, 3):
        # Daily maintenance pause: 17:00 - 18:00 ET
        if weekday in (0, 1, 2, 3):
            if time(17, 0) <= current_time < time(18, 0):
                return SessionStateResult(
                    state=TradFiSessionState.MAINTENANCE,
                    source="fallback_cme_calendar",
                    is_uncertain=True,
                    retrieval_timestamp=None,
                    valid_from=None,
                    valid_until=None,
                    details={"reason": "Daily CME settlement break (17:00-18:00 ET)", "limitations": limitations_msg},
                )
            return SessionStateResult(
                state=TradFiSessionState.REGULAR,
                source="fallback_cme_calendar",
                is_uncertain=True,
                retrieval_timestamp=None,
                valid_from=None,
                valid_until=None,
                details={"reason": "Regular weekday trading", "limitations": limitations_msg},
            )

        return SessionStateResult(
            state=TradFiSessionState.REGULAR,
            source="fallback_cme_calendar",
            is_uncertain=True,
            retrieval_timestamp=None,
            valid_from=None,
            valid_until=None,
            details={"reason": "Regular trading", "limitations": limitations_msg},
        )


class BinanceScheduleProvider(ScheduleProvider):
    """
    Schedule provider that parses and enforces official Binance exchange schedules
    (e.g., from GET /fapi/v1/tradingSchedule for COMMODITY instruments).
    Falls back to FallbackScheduleProvider when data is unavailable or stale.
    """

    def __init__(
        self,
        schedule_data: dict[str, Any] | None = None,
        retrieval_time: datetime | None = None,
        max_staleness_hours: float = 168.0,  # 7 days TTL
        fallback: ScheduleProvider | None = None,
    ):
        self.schedule_data = schedule_data
        self.retrieval_time = retrieval_time
        self.max_staleness_hours = max_staleness_hours
        self.fallback = fallback or FallbackScheduleProvider()
        self._parsed_intervals: list[dict[str, Any]] = []

        if schedule_data:
            self._parse_schedule(schedule_data)

    def _parse_schedule(self, data: dict[str, Any]) -> None:
        """Parse intervals from Binance tradingSchedule structure."""
        try:
            # Handle standard marketSchedules format: {"marketSchedules": {"COMMODITY": {"sessions": [...]}}}
            commodity_data = data.get("marketSchedules", {}).get("COMMODITY", {})
            sessions = commodity_data.get("sessions", [])
            parsed = []

            for s in sessions:
                s_type = s.get("sessionType", "").upper()
                start_ms = s.get("startTime")
                end_ms = s.get("endTime")

                if start_ms is not None and end_ms is not None:
                    start_dt = datetime.fromtimestamp(start_ms / 1000.0, tz=UTC)
                    end_dt = datetime.fromtimestamp(end_ms / 1000.0, tz=UTC)
                elif "start" in s and "end" in s:
                    # ISO string support
                    start_dt = datetime.fromisoformat(s["start"]).replace(tzinfo=UTC)
                    end_dt = datetime.fromisoformat(s["end"]).replace(tzinfo=UTC)
                else:
                    continue

                state = (
                    TradFiSessionState.REGULAR
                    if s_type == "REGULAR"
                    else (
                        TradFiSessionState.MAINTENANCE
                        if s_type in ("MAINTENANCE", "DAILY_BREAK")
                        else TradFiSessionState.NO_TRADING
                    )
                )

                parsed.append({"state": state, "start": start_dt, "end": end_dt, "type": s_type})

            # Sort chronologically
            parsed.sort(key=lambda x: x["start"])
            self._parsed_intervals = parsed
        except Exception as e:
            logger.warning(f"Failed to parse Binance trading schedule: {e}")
            self._parsed_intervals = []

    def is_stale(self, as_of: datetime) -> bool:
        if self.retrieval_time is None:
            return True
        age = as_of - self.retrieval_time
        return age.total_seconds() > (self.max_staleness_hours * 3600.0)

    def get_session_state(self, dt: datetime) -> SessionStateResult:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)

        # If no valid schedule parsed, log warning and delegate to fallback
        if not self._parsed_intervals:
            logger.debug("No valid Binance trading schedule available. Delegating to FallbackScheduleProvider.")
            return self.fallback.get_session_state(dt)

        stale = self.is_stale(dt)
        if stale:
            logger.warning(f"Binance trading schedule is stale (older than {self.max_staleness_hours}h).")

        # Search for interval containing dt
        for interval in self._parsed_intervals:
            if interval["start"] <= dt < interval["end"]:
                return SessionStateResult(
                    state=interval["state"],
                    source="binance_schedule_api",
                    is_uncertain=stale,  # Mark uncertain if schedule is stale
                    retrieval_timestamp=self.retrieval_time,
                    valid_from=interval["start"],
                    valid_until=interval["end"],
                    details={"session_type": interval["type"], "is_stale": stale},
                )

        # Date falls outside parsed intervals
        logger.warning(f"Timestamp {dt.isoformat()} falls outside scheduled intervals. Using fallback.")
        fallback_res = self.fallback.get_session_state(dt)
        return SessionStateResult(
            state=fallback_res.state,
            source="fallback_cme_calendar",
            is_uncertain=True,
            retrieval_timestamp=self.retrieval_time,
            valid_from=None,
            valid_until=None,
            details={"reason": "Timestamp outside schedule range; fell back to CME calendar", "is_stale": True},
        )


class BinanceStaticScheduleProvider(ScheduleProvider):
    """
    Authoritative offline schedule provider loading from a static configuration export.
    Used when outbound network connectivity to Binance REST API is restricted.
    Audit metadata: source='binance_static_config', is_uncertain=False.
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        schedule_data: dict[str, Any] | None = None,
        fallback: ScheduleProvider | None = None,
    ):
        self.fallback = fallback or FallbackScheduleProvider()
        self._delegate: BinanceScheduleProvider | None = None

        loaded_data = schedule_data
        if loaded_data is None and config_path is not None:
            p = Path(config_path)
            if p.exists():
                try:
                    import json
                    with open(p, "r", encoding="utf-8") as f:
                        loaded_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load static Binance schedule from {config_path}: {e}")

        if loaded_data:
            self._delegate = BinanceScheduleProvider(
                schedule_data=loaded_data,
                retrieval_time=datetime.now(UTC),
                max_staleness_hours=87600.0,  # 10 years (static verified schedule)
                fallback=self.fallback,
            )

    def get_session_state(self, dt: datetime) -> SessionStateResult:
        if self._delegate and self._delegate._parsed_intervals:
            res = self._delegate.get_session_state(dt)
            if res.source == "binance_schedule_api":
                return SessionStateResult(
                    state=res.state,
                    source="binance_static_config",
                    is_uncertain=False,
                    retrieval_timestamp=res.retrieval_timestamp,
                    valid_from=res.valid_from,
                    valid_until=res.valid_until,
                    details={"version": "static_v1", "session_type": res.details.get("session_type")},
                )
            return res
        return self.fallback.get_session_state(dt)


class SessionTracker:

    """
    Unified Session Tracker for Binance XAUUSDT.
    Delegates session evaluation to a configured ScheduleProvider.
    """

    _provider: ScheduleProvider = BinanceScheduleProvider(fallback=FallbackScheduleProvider())

    @classmethod
    def set_provider(cls, provider: ScheduleProvider) -> None:
        """Inject an explicit ScheduleProvider (for testing or configuration)."""
        cls._provider = provider

    @classmethod
    def get_session_details(cls, dt: datetime | None = None) -> SessionStateResult:
        """Retrieve full audit details for session status."""
        if dt is None:
            dt = datetime.now(UTC)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return cls._provider.get_session_state(dt)

    @classmethod
    def get_session_state(cls, dt: datetime | None = None) -> TradFiSessionState:
        """Determine TradFi physical/futures gold market status."""
        return cls.get_session_details(dt).state

    @classmethod
    def is_underlying_active(cls, dt: datetime | None = None) -> bool:
        """True only if underlying market is in active REGULAR trading session."""
        return cls.get_session_state(dt) == TradFiSessionState.REGULAR
