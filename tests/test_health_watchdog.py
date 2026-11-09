"""
Unit tests for production health watchdog and self-healing logic.
"""

from unittest.mock import patch

from scripts.health_watchdog import (
    evaluate_health_and_remediate,
    get_system_memory_usage,
)


def test_get_system_memory_usage():
    """Verify memory usage percentage returns non-negative float."""
    mem = get_system_memory_usage()
    assert isinstance(mem, float)
    assert 0.0 <= mem <= 100.0


def test_evaluate_health_healthy():
    """Verify evaluate_health_and_remediate returns True for healthy payload."""
    payload = {
        "status": "HEALTHY",
        "database_connected": True,
        "underlying_active": False,
        "data_freshness": {"candle_lag_seconds": 60},
    }
    assert evaluate_health_and_remediate(payload) is True


def test_evaluate_health_unhealthy_status():
    """Verify returns False when database is disconnected."""
    payload = {
        "status": "UNHEALTHY",
        "database_connected": False,
        "underlying_active": True,
        "data_freshness": {"candle_lag_seconds": 60},
    }
    assert evaluate_health_and_remediate(payload) is False


def test_evaluate_health_stale_triggers_recovery():
    """Verify excessive candle lag during active market hours triggers remediation."""
    payload = {
        "status": "HEALTHY",
        "database_connected": True,
        "underlying_active": True,
        "data_freshness": {"candle_lag_seconds": 450},
    }
    with patch("subprocess.run") as mock_run:
        result = evaluate_health_and_remediate(payload, max_lag_seconds=300)
        assert result is False
        assert mock_run.called
        # Check restart command
        cmd = mock_run.call_args[0][0]
        assert "systemctl" in cmd
        assert "xau-ingestion.service" in cmd
