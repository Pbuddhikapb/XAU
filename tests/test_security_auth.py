"""
Unit and integration tests for security and API key authentication.
"""

import pytest
from fastapi import HTTPException

from backend.config import settings
from backend.security import verify_admin_key


def test_verify_admin_key_open_when_unconfigured(monkeypatch):
    """When ADMIN_API_KEY is not set or empty, open access is granted."""
    monkeypatch.setattr(settings, "ADMIN_API_KEY", None)
    assert verify_admin_key() is True

    monkeypatch.setattr(settings, "ADMIN_API_KEY", "")
    assert verify_admin_key() is True


def test_verify_admin_key_rejects_missing_key(monkeypatch):
    """When ADMIN_API_KEY is configured, missing credentials raise 401."""
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "super-secret-key-12345")
    with pytest.raises(HTTPException) as exc:
        verify_admin_key(x_api_key=None, authorization=None)
    assert exc.value.status_code == 401
    assert "Invalid or missing" in exc.value.detail


def test_verify_admin_key_rejects_invalid_key(monkeypatch):
    """When ADMIN_API_KEY is configured, incorrect credentials raise 401."""
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "super-secret-key-12345")
    with pytest.raises(HTTPException) as exc:
        verify_admin_key(x_api_key="wrong-key", authorization=None)
    assert exc.value.status_code == 401


def test_verify_admin_key_accepts_x_api_key(monkeypatch):
    """Valid X-API-Key header is accepted."""
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "super-secret-key-12345")
    assert verify_admin_key(x_api_key="super-secret-key-12345") is True


def test_verify_admin_key_accepts_bearer_token(monkeypatch):
    """Valid Bearer authorization header is accepted."""
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "super-secret-key-12345")
    assert verify_admin_key(authorization="Bearer super-secret-key-12345") is True
