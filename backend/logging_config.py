"""
Production logging configuration for Binance XAUUSDT Market Intelligence System.
Features size-capped rotating file handlers and structured audit logging for decisions.
"""

import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from backend.config import settings

AUDIT_LOGGER_NAME = "xau.audit"


def setup_production_logging(log_dir: str | None = None) -> None:
    """
    Configure rotating log handlers for application and audit events.
    Avoids disk bloat by enforcing a 10MB per-file ceiling with 5 rolling backups.
    """
    target_dir = os.path.abspath(log_dir or settings.LOG_DIR)
    os.makedirs(target_dir, exist_ok=True)

    app_log_path = os.path.join(target_dir, "app.log")
    audit_log_path = os.path.join(target_dir, "audit.log")

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s (pid:%(process)d): %(message)s")

    # Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Check if RotatingFileHandler already attached to avoid duplication
    has_app_file_handler = any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == app_log_path
        for h in root_logger.handlers
    )

    if not has_app_file_handler:
        app_file_handler = RotatingFileHandler(
            app_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        app_file_handler.setFormatter(formatter)
        app_file_handler.setLevel(logging.INFO)
        root_logger.addHandler(app_file_handler)

    # Audit Logger
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False  # Keep audit events dedicated to audit.log

    has_audit_handler = any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == audit_log_path
        for h in audit_logger.handlers
    )

    if not has_audit_handler:
        audit_file_handler = RotatingFileHandler(
            audit_log_path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        audit_file_handler.setFormatter(logging.Formatter("%(message)s"))
        audit_file_handler.setLevel(logging.INFO)
        audit_logger.addHandler(audit_file_handler)


def log_audit_event(event_type: str, details: dict[str, Any]) -> None:
    """Write an immutable, structured JSON event record into audit.log."""
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "symbol": settings.SYMBOL,
        "details": details,
    }
    audit_logger.info(json.dumps(record))
