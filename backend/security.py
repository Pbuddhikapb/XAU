"""
Security and authentication dependencies for institutional API protection.
"""

import secrets

from fastapi import Header, HTTPException, status

from backend.config import settings


def verify_admin_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> bool:
    """
    Verify administrative access key for sensitive / heavy endpoints.
    If settings.ADMIN_API_KEY is not configured or empty, allows open access (dev mode).
    If configured, requires valid X-API-Key header or Bearer authorization token.
    Uses constant-time comparison to prevent timing attacks.
    """
    configured_key = settings.ADMIN_API_KEY
    if not configured_key or not configured_key.strip():
        return True

    supplied_key = x_api_key if isinstance(x_api_key, str) else None
    auth_str = authorization if isinstance(authorization, str) else None

    if not supplied_key and auth_str and auth_str.startswith("Bearer "):
        supplied_key = auth_str[7:].strip()

    if not supplied_key or not secrets.compare_digest(supplied_key, configured_key.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Admin API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
