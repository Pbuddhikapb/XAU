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
6. Polling of Binance /fapi/v1/tradingSchedule with cached fallback to ET calendar.
7. Handling of holidays and early closes.
8. Marking of candles for DAILY_BREAK, WEEKEND_CLOSED, and frozen-index periods.
"""

import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from backend.config import settings

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
    source: str                      # "binance_schedule_api" | "binance_schedule_cache" | "fallback_cme_calendar"
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


def _get_easter_sunday(year: int) -> date:
    """Compute Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    rem_l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * rem_l) // 451
    month = (h + rem_l - 7 * m + 114) // 31
    day = ((h + rem_l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_cme_holiday_or_early_close(ny_dt: datetime) -> tuple[TradFiSessionState, str] | None:
    """
    Check if a given Eastern Time datetime falls on a CME Gold holiday or early close.
    Returns (TradFiSessionState, reason_string) or None if normal calendar rules apply.
    """
    cal_date = ny_dt.date()
    cur_time = ny_dt.time()
    year = cal_date.year

    # 1. New Year's Day (Jan 1)
    if cal_date.month == 1 and cal_date.day == 1:
        return TradFiSessionState.NO_TRADING, "CME Holiday: New Year's Day (Closed full day)"

    # 2. Martin Luther King Jr. Day (3rd Monday in January) - Early close 14:30 ET
    if cal_date.month == 1 and cal_date.weekday() == 0 and 15 <= cal_date.day <= 21:
        if cur_time >= time(14, 30):
            return TradFiSessionState.NO_TRADING, "CME Early Close: MLK Jr. Day (Closed at 14:30 ET)"

    # 3. Presidents' Day (3rd Monday in February) - Early close 14:30 ET
    if cal_date.month == 2 and cal_date.weekday() == 0 and 15 <= cal_date.day <= 21:
        if cur_time >= time(14, 30):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Presidents' Day (Closed at 14:30 ET)"

    # 4. Good Friday (Friday before Easter) - Closed full day
    good_friday = _get_easter_sunday(year) - timedelta(days=2)
    if cal_date == good_friday:
        return TradFiSessionState.NO_TRADING, "CME Holiday: Good Friday (Closed full day)"

    # 5. Memorial Day (last Monday in May) - Early close 14:30 ET
    if cal_date.month == 5 and cal_date.weekday() == 0 and cal_date.day >= 25:
        if cur_time >= time(14, 30):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Memorial Day (Closed at 14:30 ET)"

    # 6. Juneteenth (June 19) - Early close 14:30 ET
    if cal_date.month == 6 and cal_date.day == 19 and cal_date.weekday() < 5:
        if cur_time >= time(14, 30):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Juneteenth (Closed at 14:30 ET)"

    # 7. US Independence Day (July 4) - Early close July 3 / July 4 at 13:00 ET
    if cal_date.month == 7 and cal_date.day == 3 and cal_date.weekday() < 5:
        if cur_time >= time(13, 0):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Pre-Independence Day (Closed at 13:00 ET)"
    if cal_date.month == 7 and cal_date.day == 4:
        return TradFiSessionState.NO_TRADING, "CME Holiday: Independence Day (Closed full day)"

    # 8. Labor Day (1st Monday in September) - Early close 14:30 ET
    if cal_date.month == 9 and cal_date.weekday() == 0 and cal_date.day <= 7:
        if cur_time >= time(14, 30):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Labor Day (Closed at 14:30 ET)"

    # 9. Thanksgiving (4th Thursday in November) - Early close 13:00 ET; Black Friday 13:45 ET
    if cal_date.month == 11 and cal_date.weekday() == 3 and 22 <= cal_date.day <= 28:
        if cur_time >= time(13, 0):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Thanksgiving Day (Closed at 13:00 ET)"
    if cal_date.month == 11 and cal_date.weekday() == 4 and 23 <= cal_date.day <= 29:
        if cur_time >= time(13, 45):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Black Friday (Closed at 13:45 ET)"

    # 10. Christmas Eve (Dec 24) early close 13:45 ET; Christmas Day (Dec 25) closed
    if cal_date.month == 12 and cal_date.day == 24 and cal_date.weekday() < 5:
        if cur_time >= time(13, 45):
            return TradFiSessionState.NO_TRADING, "CME Early Close: Christmas Eve (Closed at 13:45 ET)"
    if cal_date.month == 12 and cal_date.day == 25:
        return TradFiSessionState.NO_TRADING, "CME Holiday: Christmas Day (Closed full day)"

    return None


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
    - CME Official Holidays & Early Closes: NO_TRADING
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

        # Check holidays / early closes first
        holiday_check = get_cme_holiday_or_early_close(ny_dt)
        if holiday_check is not None:
            state, reason = holiday_check
            logger.warning("CME calendar fallback evaluated holiday condition: %s at %s", reason, dt.isoformat())
            return SessionStateResult(
                state=state,
                source="fallback_cme_calendar",
                is_uncertain=True,
                retrieval_timestamp=None,
                valid_from=None,
                valid_until=None,
                details={"reason": reason, "limitations": limitations_msg},
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


class BinanceSchedulePoller:
    """
    Polls Binance USDS-M Futures GET /fapi/v1/tradingSchedule endpoint,
    caches responses locally, and provides fallback to the ET calendar with logged warnings.
    """

    def __init__(
        self,
        base_url: str | None = None,
        proxy_url: str | None = None,
        cache_path: Path | str = "config/binance_schedule_cache.json",
        timeout_seconds: float = 5.0,
    ):
        self.base_url = (base_url or settings.BINANCE_FUTURES_HTTP_URL).rstrip("/")
        self.proxy_url = proxy_url or settings.OUTBOUND_PROXY_URL
        self.cache_path = Path(cache_path)
        self.timeout_seconds = timeout_seconds

    def poll(self) -> tuple[dict[str, Any] | None, str]:
        """
        Poll GET /fapi/v1/tradingSchedule.
        Returns (data_dict, source_str) where source_str is:
        - "binance_schedule_api" on live HTTP success
        - "binance_schedule_cache" on disk cache fallback
        - "fallback_cme_calendar" if API and cache are unavailable.
        """
        url = f"{self.base_url}/fapi/v1/tradingSchedule"
        handlers: list[urllib.request.BaseHandler] = []
        if self.proxy_url:
            handlers.append(urllib.request.ProxyHandler({"http": self.proxy_url, "https": self.proxy_url}))
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-XAU/1.0"})

        try:
            with opener.open(req, timeout=self.timeout_seconds) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    self._save_cache(payload)
                    logger.info("Successfully fetched Binance /fapi/v1/tradingSchedule.")
                    return payload, "binance_schedule_api"
                logger.warning(
                    "Binance /fapi/v1/tradingSchedule returned HTTP %d. Falling back to cached schedule/ET calendar.",
                    resp.status,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to poll Binance /fapi/v1/tradingSchedule (%s). Falling back to cached schedule/ET calendar.",
                e,
            )

        # Attempt fallback to disk cache
        cached = self.load_cache()
        if cached:
            logger.info("Loaded cached Binance trading schedule from %s.", self.cache_path)
            return cached, "binance_schedule_cache"

        logger.warning(
            "No cached Binance trading schedule found at %s. Falling back to CME ET calendar.", self.cache_path
        )
        return None, "fallback_cme_calendar"

    def _save_cache(self, data: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (OSError, TypeError) as e:
            logger.warning("Failed to save schedule cache to %s: %s", self.cache_path, e)

    def load_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to load schedule cache from %s: %s", self.cache_path, e)
            return None


class BinanceScheduleProvider(ScheduleProvider):
    """
    Schedule provider that parses and enforces official Binance exchange schedules
    (e.g., from GET /fapi/v1/tradingSchedule for COMMODITY instruments).
    Falls back to FallbackScheduleProvider when data is unavailable or stale,
    logging explicit warnings on every fallback invocation.
    """

    def __init__(
        self,
        schedule_data: dict[str, Any] | None = None,
        retrieval_time: datetime | None = None,
        max_staleness_hours: float = 168.0,  # 7 days TTL
        fallback: ScheduleProvider | None = None,
        poller: BinanceSchedulePoller | None = None,
    ):
        self.schedule_data = schedule_data
        self.retrieval_time = retrieval_time
        self.max_staleness_hours = max_staleness_hours
        self.fallback = fallback or FallbackScheduleProvider()
        self.poller = poller or BinanceSchedulePoller()
        self._parsed_intervals: list[dict[str, Any]] = []
        self._warned_no_schedule: bool = False
        self._warned_stale: bool = False

        if schedule_data:
            self._parse_schedule(schedule_data)

    def refresh(self) -> bool:
        """Poll the Binance tradingSchedule endpoint and update parsed intervals."""
        data, source = self.poller.poll()
        if data:
            self.schedule_data = data
            self.retrieval_time = datetime.now(UTC)
            self._parse_schedule(data)
            self._warned_no_schedule = False
            self._warned_stale = False
            return True
        logger.warning("Binance schedule refresh failed. Operating on fallback provider.")
        return False

    def _parse_schedule(self, data: dict[str, Any]) -> None:
        """Parse intervals from Binance tradingSchedule structure."""
        try:
            # Handle standard marketSchedules format: {"marketSchedules": {"COMMODITY": {"sessions": [...]}}}
            commodity_data = data.get("marketSchedules", {}).get("COMMODITY", {})
            sessions = commodity_data.get("sessions", [])
            if not sessions and isinstance(data.get("sessions"), list):
                sessions = data["sessions"]

            parsed = []
            for s in sessions:
                s_type = (s.get("type") or s.get("sessionType") or "").upper()
                start_ms = s.get("startTime")
                end_ms = s.get("endTime")

                if start_ms is not None and end_ms is not None:
                    # Milliseconds or seconds
                    start_sec = start_ms / 1000.0 if start_ms > 1e11 else float(start_ms)
                    end_sec = end_ms / 1000.0 if end_ms > 1e11 else float(end_ms)
                    start_dt = datetime.fromtimestamp(start_sec, tz=UTC)
                    end_dt = datetime.fromtimestamp(end_sec, tz=UTC)
                elif "start" in s and "end" in s:
                    start_dt = datetime.fromisoformat(s["start"]).replace(tzinfo=UTC)
                    end_dt = datetime.fromisoformat(s["end"]).replace(tzinfo=UTC)
                else:
                    continue

                if s_type == "REGULAR":
                    state = TradFiSessionState.REGULAR
                elif s_type in ("MAINTENANCE", "DAILY_BREAK"):
                    state = TradFiSessionState.MAINTENANCE
                else:
                    # NO_TRADING, CLOSED, WEEKEND_CLOSED, HOLIDAY_CLOSED
                    state = TradFiSessionState.NO_TRADING

                parsed.append({"state": state, "start": start_dt, "end": end_dt, "type": s_type})

            parsed.sort(key=lambda x: x["start"])
            self._parsed_intervals = parsed
        except (ValueError, KeyError, TypeError) as e:
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

        # If no valid schedule parsed, log warning once and delegate to fallback
        if not self._parsed_intervals:
            if not self._warned_no_schedule:
                logger.warning(
                    "No valid Binance trading schedule available for %s. Falling back to CME ET calendar.",
                    dt.isoformat(),
                )
                self._warned_no_schedule = True
            else:
                logger.debug(
                    "No valid Binance trading schedule available for %s. Using CME fallback.",
                    dt.isoformat(),
                )
            return self.fallback.get_session_state(dt)

        stale = self.is_stale(dt)
        if stale:
            if not self._warned_stale:
                logger.warning(
                    "Binance trading schedule is stale (older than %sh). Falling back to CME ET calendar.",
                    self.max_staleness_hours,
                )
                self._warned_stale = True
            else:
                logger.debug(
                    "Binance trading schedule is stale for %s. Using CME fallback.",
                    dt.isoformat(),
                )

        # Search for interval containing dt
        for interval in self._parsed_intervals:
            if interval["start"] <= dt < interval["end"]:
                return SessionStateResult(
                    state=interval["state"],
                    source="binance_schedule_api",
                    is_uncertain=stale,
                    retrieval_timestamp=self.retrieval_time,
                    valid_from=interval["start"],
                    valid_until=interval["end"],
                    details={"session_type": interval["type"], "is_stale": stale},
                )

        # Date falls outside parsed intervals
        logger.warning(
            "Timestamp %s falls outside scheduled intervals. Falling back to CME ET calendar.",
            dt.isoformat(),
        )
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
                    with open(p, encoding="utf-8") as f:
                        loaded_data = json.load(f)
                except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
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
    Includes candle marking to identify DAILY_BREAK, WEEKEND_CLOSED, and frozen-index periods.
    """

    _provider: ScheduleProvider = BinanceScheduleProvider(fallback=FallbackScheduleProvider())

    @classmethod
    def set_provider(cls, provider: ScheduleProvider) -> None:
        """Inject an explicit ScheduleProvider (for testing or configuration)."""
        cls._provider = provider

    @classmethod
    def get_provider(cls) -> ScheduleProvider:
        return cls._provider

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

    @classmethod
    def mark_candles(
        cls,
        df: pd.DataFrame,
        time_col: str = "open_time",
        provider: ScheduleProvider | None = None,
    ) -> pd.DataFrame:
        """
        Mark each candle in DataFrame with its TradFi session state, activity flag, and weight.
        Adds columns:
        - tradfi_session_state: REGULAR, MAINTENANCE, NO_TRADING, UNKNOWN
        - is_tradfi_active: bool (True only if REGULAR)
        - analysis_weight: float (1.0 for active, 0.1 for maintenance break, 0.0 for closed/frozen)
        - exclusion_reason: str | None (DAILY_BREAK, WEEKEND_CLOSED, HOLIDAY_CLOSED, FROZEN_INDEX)
        """
        if df.empty:
            res = df.copy()
            res["tradfi_session_state"] = pd.Series(dtype=str)
            res["is_tradfi_active"] = pd.Series(dtype=bool)
            res["analysis_weight"] = pd.Series(dtype=float)
            res["exclusion_reason"] = pd.Series(dtype=object)
            return res

        res = df.copy()
        times = res[time_col]
        if not pd.api.types.is_datetime64_any_dtype(times):
            times = pd.to_datetime(times, utc=True)
        elif times.dt.tz is None:
            times = times.dt.tz_localize("UTC")
        else:
            times = times.dt.tz_convert("UTC")

        active_provider = provider or cls._provider

        # Map unique timestamps for performance
        unique_times = times.drop_duplicates()
        eval_map: dict[Any, SessionStateResult] = {}
        for t in unique_times:
            py_dt = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
            eval_map[t] = active_provider.get_session_state(py_dt)

        session_states: list[str] = []
        is_actives: list[bool] = []
        weights: list[float] = []
        reasons: list[str | None] = []

        for t in times:
            eval_res = eval_map[t]
            st = eval_res.state
            session_states.append(st.value)

            if st == TradFiSessionState.REGULAR:
                is_actives.append(True)
                weights.append(1.0)
                reasons.append(None)
            elif st == TradFiSessionState.MAINTENANCE:
                is_actives.append(False)
                weights.append(0.1)
                reasons.append("DAILY_BREAK")
            else:  # NO_TRADING or UNKNOWN
                is_actives.append(False)
                weights.append(0.0)
                reason_detail = eval_res.details.get("reason", "")
                if "Holiday" in reason_detail:
                    reasons.append("HOLIDAY_CLOSED")
                elif "weekend" in reason_detail.lower():
                    reasons.append("WEEKEND_CLOSED")
                else:
                    reasons.append("WEEKEND_CLOSED")

        res["tradfi_session_state"] = session_states
        res["is_tradfi_active"] = is_actives
        res["analysis_weight"] = weights
        res["exclusion_reason"] = reasons

        # Detect frozen-index periods: if consecutive bars have identical OHLC and zero volume during closed sessions
        if "close" in res.columns and "volume" in res.columns:
            is_closed = ~res["is_tradfi_active"]
            zero_vol = res["volume"] == 0.0
            flat_price = res["close"].diff().fillna(0.0) == 0.0
            frozen_mask = is_closed & zero_vol & flat_price
            res.loc[frozen_mask, "exclusion_reason"] = "FROZEN_INDEX"
            res.loc[frozen_mask, "analysis_weight"] = 0.0

        return res
