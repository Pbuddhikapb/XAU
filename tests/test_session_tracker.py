"""
Unit tests for TradFi Session Tracker and Schedule Provider Architecture.
Validates:
1. Provider abstraction (BinanceScheduleProvider, FallbackScheduleProvider).
2. Eastern Daylight Time (EDT, summer/autumn): Friday 21:00 UTC close, Sunday 22:00 UTC open,
   daily break 21:00-22:00 UTC.
3. Eastern Standard Time (EST, winter): Friday 22:00 UTC close, Sunday 23:00 UTC open,
   daily break 22:00-23:00 UTC.
4. Fallback uncertainty tracking (is_uncertain=True).
5. Stale schedule handling (detects expired schedule data).
6. Malformed/missing schedule handling (graceful fallback).
7. Sharp boundary transitions at 17:00:00 and 18:00:00 ET.
"""

import json
import urllib.error
from datetime import UTC, datetime

from backend.data.session_tracker import (
    BinanceScheduleProvider,
    FallbackScheduleProvider,
    SessionTracker,
    TradFiSessionState,
)


def test_session_tracker_edt_summer_sessions():
    """Verify session tracking during US Eastern Daylight Time (EDT, UTC-4)."""
    # Wednesday 14:00 UTC -> Regular TradFi market REGULAR (10:00 EDT)
    wednesday_midday = datetime(2026, 10, 28, 14, 0, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_midday) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(wednesday_midday) is True

    # Wednesday 21:30 UTC -> Daily maintenance pause (17:30 EDT)
    wednesday_maintenance = datetime(2026, 10, 28, 21, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_maintenance) == TradFiSessionState.MAINTENANCE
    assert SessionTracker.is_underlying_active(wednesday_maintenance) is False

    # Wednesday 22:30 UTC -> Market reopened for next CME day (18:30 EDT)
    wednesday_reopened = datetime(2026, 10, 28, 22, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_reopened) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(wednesday_reopened) is True

    # Friday 20:30 UTC -> Active pre-close trading (16:30 EDT)
    friday_active = datetime(2026, 10, 23, 20, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(friday_active) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(friday_active) is True

    # Friday 21:15 UTC -> Weekend closed (closed at 17:00 EDT = 21:00 UTC)
    friday_night = datetime(2026, 10, 23, 21, 15, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(friday_night) == TradFiSessionState.NO_TRADING
    assert SessionTracker.is_underlying_active(friday_night) is False

    # Saturday 12:00 UTC -> Full weekend closure
    saturday = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(saturday) == TradFiSessionState.NO_TRADING
    assert SessionTracker.is_underlying_active(saturday) is False

    # Sunday 21:30 UTC -> Weekend closed (opens at 18:00 EDT = 22:00 UTC)
    sunday_before_open = datetime(2026, 10, 25, 21, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(sunday_before_open) == TradFiSessionState.NO_TRADING

    # Sunday 22:15 UTC -> Reopened for new trading week (18:15 EDT)
    sunday_after_open = datetime(2026, 10, 25, 22, 15, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(sunday_after_open) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(sunday_after_open) is True


def test_session_tracker_est_winter_sessions():
    """Verify session tracking during US Eastern Standard Time (EST, UTC-5)."""
    # Wednesday 14:00 UTC -> Regular TradFi market REGULAR (09:00 EST)
    wednesday_midday = datetime(2026, 1, 14, 14, 0, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_midday) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(wednesday_midday) is True

    # Wednesday 21:30 UTC -> Active pre-pause trading in winter (16:30 EST)
    wednesday_active = datetime(2026, 1, 14, 21, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_active) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(wednesday_active) is True

    # Wednesday 22:30 UTC -> Daily maintenance pause in winter (17:30 EST = 22:30 UTC)
    wednesday_break = datetime(2026, 1, 14, 22, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(wednesday_break) == TradFiSessionState.MAINTENANCE
    assert SessionTracker.is_underlying_active(wednesday_break) is False

    # Friday 21:30 UTC -> Still active in winter (16:30 EST)
    friday_active = datetime(2026, 1, 16, 21, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(friday_active) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(friday_active) is True

    # Friday 22:15 UTC -> Weekend closed in winter (closed at 17:00 EST = 22:00 UTC)
    friday_closed = datetime(2026, 1, 16, 22, 15, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(friday_closed) == TradFiSessionState.NO_TRADING
    assert SessionTracker.is_underlying_active(friday_closed) is False

    # Sunday 22:30 UTC -> Weekend closed in winter (opens at 18:00 EST = 23:00 UTC)
    sunday_before_open = datetime(2026, 1, 18, 22, 30, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(sunday_before_open) == TradFiSessionState.NO_TRADING

    # Sunday 23:15 UTC -> Reopened in winter (18:15 EST = 23:15 UTC)
    sunday_after_open = datetime(2026, 1, 18, 23, 15, 0, tzinfo=UTC)
    assert SessionTracker.get_session_state(sunday_after_open) == TradFiSessionState.REGULAR
    assert SessionTracker.is_underlying_active(sunday_after_open) is True


def test_fallback_uncertainty_and_audit_details():
    """Verify that fallback provider explicitly documents uncertainty and limitations."""
    fallback = FallbackScheduleProvider()
    dt = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)
    res = fallback.get_session_state(dt)

    assert res.state == TradFiSessionState.REGULAR
    assert res.source == "fallback_cme_calendar"
    assert res.is_uncertain is True
    assert "limitations" in res.details


def test_binance_schedule_provider_valid():
    """Verify that a valid Binance trading schedule takes precedence and is marked certain."""
    mock_data = {
        "marketSchedules": {
            "COMMODITY": {
                "sessions": [
                    {
                        "sessionType": "REGULAR",
                        "start": "2026-10-18T22:00:00Z",
                        "end": "2026-10-23T21:00:00Z",
                    },
                    {
                        "sessionType": "NO_TRADING",
                        "start": "2026-10-23T21:00:00Z",
                        "end": "2026-10-25T22:00:00Z",
                    },
                ]
            }
        }
    }
    retrieval_time = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    provider = BinanceScheduleProvider(schedule_data=mock_data, retrieval_time=retrieval_time)

    # Active regular trading
    t_regular = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    res_reg = provider.get_session_state(t_regular)
    assert res_reg.state == TradFiSessionState.REGULAR
    assert res_reg.source == "binance_schedule_api"
    assert res_reg.is_uncertain is False

    # Weekend closure
    t_closed = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    res_closed = provider.get_session_state(t_closed)
    assert res_closed.state == TradFiSessionState.NO_TRADING
    assert res_closed.source == "binance_schedule_api"
    assert res_closed.is_uncertain is False


def test_binance_schedule_provider_stale():
    """Verify that a schedule older than max_staleness_hours is flagged as uncertain."""
    mock_data = {
        "marketSchedules": {
            "COMMODITY": {
                "sessions": [
                    {
                        "sessionType": "REGULAR",
                        "start": "2026-10-01T00:00:00Z",
                        "end": "2026-10-31T00:00:00Z",
                    }
                ]
            }
        }
    }
    old_retrieval = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    # Stale by 20 days (TTL is 7 days / 168h)
    provider = BinanceScheduleProvider(
        schedule_data=mock_data, retrieval_time=old_retrieval, max_staleness_hours=168.0
    )

    t_eval = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    res = provider.get_session_state(t_eval)
    assert res.state == TradFiSessionState.REGULAR
    assert res.is_uncertain is True  # Flagged uncertain due to staleness


def test_binance_schedule_provider_invalid_data_graceful_fallback():
    """Verify that corrupt schedule data gracefully delegates to fallback without throwing."""
    corrupt_data = {"invalid_structure": 12345}
    provider = BinanceScheduleProvider(schedule_data=corrupt_data)

    dt = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)
    res = provider.get_session_state(dt)
    assert res.state == TradFiSessionState.REGULAR
    assert res.source == "fallback_cme_calendar"
    assert res.is_uncertain is True


def test_sharp_session_boundary_transitions():
    """Verify sharp transitions down to the second at 17:00:00 and 18:00:00 ET."""
    # On Wednesday in EDT (UTC-4):
    # 20:59:59 UTC = 16:59:59 EDT -> REGULAR
    # 21:00:00 UTC = 17:00:00 EDT -> MAINTENANCE
    # 21:59:59 UTC = 17:59:59 EDT -> MAINTENANCE
    # 22:00:00 UTC = 18:00:00 EDT -> REGULAR
    t_before_break = datetime(2026, 10, 28, 20, 59, 59, tzinfo=UTC)
    t_start_break = datetime(2026, 10, 28, 21, 0, 0, tzinfo=UTC)
    t_end_break = datetime(2026, 10, 28, 21, 59, 59, tzinfo=UTC)
    t_after_break = datetime(2026, 10, 28, 22, 0, 0, tzinfo=UTC)

    assert SessionTracker.get_session_state(t_before_break) == TradFiSessionState.REGULAR
    assert SessionTracker.get_session_state(t_start_break) == TradFiSessionState.MAINTENANCE
    assert SessionTracker.get_session_state(t_end_break) == TradFiSessionState.MAINTENANCE
    assert SessionTracker.get_session_state(t_after_break) == TradFiSessionState.REGULAR


def test_binance_static_schedule_provider():
    """Verify that BinanceStaticScheduleProvider loads static config and marks is_uncertain=False."""
    from backend.data.session_tracker import BinanceStaticScheduleProvider

    provider = BinanceStaticScheduleProvider(config_path="config/binance_xauusdt_schedule_v1.json")
    dt = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    res = provider.get_session_state(dt)
    assert res.state == TradFiSessionState.REGULAR
    assert res.source == "binance_static_config"
    assert res.is_uncertain is False


def test_cme_holidays_and_early_closes():
    """Verify that CME Gold holidays (Good Friday, Christmas) and early closes (Thanksgiving) are respected."""
    fallback = FallbackScheduleProvider()

    # 1. Good Friday 2026: April 3, 2026 - full day closure
    good_friday_noon = datetime(2026, 4, 3, 16, 0, tzinfo=UTC)  # 12:00 EDT
    res_gf = fallback.get_session_state(good_friday_noon)
    assert res_gf.state == TradFiSessionState.NO_TRADING
    assert "Good Friday" in res_gf.details.get("reason", "")

    # 2. Christmas Day: Dec 25, 2026 - full day closure
    xmas_noon = datetime(2026, 12, 25, 17, 0, tzinfo=UTC)  # 12:00 EST
    res_xmas = fallback.get_session_state(xmas_noon)
    assert res_xmas.state == TradFiSessionState.NO_TRADING
    assert "Christmas Day" in res_xmas.details.get("reason", "")

    # 3. Thanksgiving Day 2026: Nov 26, 2026 - early close at 13:00 ET
    # 12:00 ET (17:00 UTC) -> Still REGULAR
    thanksgiving_pre_close = datetime(2026, 11, 26, 17, 0, tzinfo=UTC)
    res_tg_pre = fallback.get_session_state(thanksgiving_pre_close)
    assert res_tg_pre.state == TradFiSessionState.REGULAR

    # 14:00 ET (19:00 UTC) -> Closed early (NO_TRADING)
    thanksgiving_post_close = datetime(2026, 11, 26, 19, 0, tzinfo=UTC)
    res_tg_post = fallback.get_session_state(thanksgiving_post_close)
    assert res_tg_post.state == TradFiSessionState.NO_TRADING
    assert "Thanksgiving" in res_tg_post.details.get("reason", "")


def test_binance_schedule_poller_and_caching(tmp_path):
    """Verify BinanceSchedulePoller caching to disk, handling errors, and fallback to ET calendar."""
    from unittest.mock import MagicMock, patch

    from backend.data.session_tracker import BinanceSchedulePoller

    cache_file = tmp_path / "test_schedule_cache.json"
    poller = BinanceSchedulePoller(cache_path=cache_file)

    mock_api_payload = {
        "updateTime": 1761286643918,
        "marketSchedules": {
            "COMMODITY": {
                "sessions": [
                    {
                        "sessionType": "REGULAR",
                        "startTime": 1760000000000,
                        "endTime": 1770000000000,
                    }
                ]
            }
        },
    }

    # 1. Successful poll: writes to cache and returns payload
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_api_payload).encode("utf-8")

    with patch("urllib.request.OpenerDirector.open", return_value=mock_resp):
        payload, source = poller.poll()
        assert payload is not None
        assert source == "binance_schedule_api"
        assert cache_file.exists()

    # 2. HTTP error: falls back to disk cache
    err = urllib.error.HTTPError("url", 500, "Server Error", {}, None)  # type: ignore[arg-type]
    with patch("urllib.request.OpenerDirector.open", side_effect=err):
        cached_payload, source_cached = poller.poll()
        assert cached_payload is not None
        assert source_cached == "binance_schedule_cache"

    # 3. HTTP error with no disk cache: falls back to CME ET calendar
    cache_file.unlink()
    with patch("urllib.request.OpenerDirector.open", side_effect=Exception("Network down")):
        none_payload, source_fallback = poller.poll()
        assert none_payload is None
        assert source_fallback == "fallback_cme_calendar"


def test_mark_candles_session_states():
    """Verify that candles are correctly annotated with session states, weights, and exclusion reasons."""
    import pandas as pd

    # Construct candles spanning:
    # 1. Wednesday 20:30 UTC (16:30 EDT) -> REGULAR, active=True, weight=1.0
    # 2. Wednesday 21:30 UTC (17:30 EDT) -> MAINTENANCE (DAILY_BREAK), active=False, weight=0.1
    # 3. Saturday 12:00 UTC -> NO_TRADING (WEEKEND_CLOSED), active=False, weight=0.0
    # 4. Saturday 13:00 UTC -> flatline/zero vol -> FROZEN_INDEX, weight=0.0
    times = [
        datetime(2026, 10, 28, 20, 30, tzinfo=UTC),
        datetime(2026, 10, 28, 21, 30, tzinfo=UTC),
        datetime(2026, 10, 31, 12, 0, tzinfo=UTC),
        datetime(2026, 10, 31, 13, 0, tzinfo=UTC),
    ]
    df = pd.DataFrame({
        "open_time": times,
        "open": [2650.0, 2652.0, 2652.0, 2652.0],
        "high": [2655.0, 2652.0, 2652.0, 2652.0],
        "low": [2648.0, 2652.0, 2652.0, 2652.0],
        "close": [2652.0, 2652.0, 2652.0, 2652.0],
        "volume": [100.0, 5.0, 0.0, 0.0],
    })

    marked = SessionTracker.mark_candles(df)
    assert "tradfi_session_state" in marked.columns
    assert "is_tradfi_active" in marked.columns
    assert "analysis_weight" in marked.columns
    assert "exclusion_reason" in marked.columns

    # Bar 0: Active regular trading
    assert marked.loc[0, "tradfi_session_state"] == "REGULAR"
    assert bool(marked.loc[0, "is_tradfi_active"]) is True
    assert float(marked.loc[0, "analysis_weight"]) == 1.0
    assert marked.loc[0, "exclusion_reason"] is None

    # Bar 1: Daily maintenance break
    assert marked.loc[1, "tradfi_session_state"] == "MAINTENANCE"
    assert bool(marked.loc[1, "is_tradfi_active"]) is False
    assert float(marked.loc[1, "analysis_weight"]) == 0.1
    assert marked.loc[1, "exclusion_reason"] == "DAILY_BREAK"

    # Bar 2 & 3: Weekend closed and frozen index
    assert marked.loc[2, "tradfi_session_state"] == "NO_TRADING"
    assert bool(marked.loc[2, "is_tradfi_active"]) is False
    assert float(marked.loc[2, "analysis_weight"]) == 0.0
    assert marked.loc[2, "exclusion_reason"] in ("WEEKEND_CLOSED", "FROZEN_INDEX")

    # Bar 3 has flat price and zero volume while closed -> FROZEN_INDEX
    assert marked.loc[3, "exclusion_reason"] == "FROZEN_INDEX"
    assert float(marked.loc[3, "analysis_weight"]) == 0.0

