"""
Data models for analytical engine inputs and validation reports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


@dataclass(frozen=True)
class OHLCVRecord:
    """Standardized single OHLCV candle record."""
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: datetime | None = None
    quote_volume: float | None = None
    trades_count: int | None = None
    taker_buy_volume: float | None = None
    taker_buy_quote_volume: float | None = None
    is_confirmed: bool = True


@dataclass
class ValidationIssue:
    """Detailed record of an identified data validation anomaly."""
    issue_type: str
    severity: ValidationSeverity
    timestamp: datetime | None
    row_index: int | None
    description: str
    details: dict[str, Any] | None = None


@dataclass
class ValidationReport:
    """Comprehensive structured data validation report."""
    is_valid: bool
    calculations_permitted: bool
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    non_monotonic_rows: int
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity in (ValidationSeverity.ERROR, ValidationSeverity.FATAL) for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)


@dataclass
class DiscontinuityEvent:
    """Record of a detected temporal discontinuity/gap between consecutive candles."""
    start_time: datetime
    end_time: datetime
    expected_interval_seconds: int
    missing_intervals: int
    duration_seconds: float


@dataclass
class DiscontinuityReport:
    """Summary report of all temporal discontinuities in a dataset."""
    total_discontinuities: int
    total_missing_candles: int
    events: list[DiscontinuityEvent] = field(default_factory=list)
