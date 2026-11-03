"""
Data models for standardized calculation outputs and analytical event records.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class IndicatorResult:
    """Standardized single-point calculation output with full audit metadata."""
    symbol: str
    timeframe: str
    candle_time: datetime
    calculation_time: datetime
    name: str
    parameters: dict[str, Any]
    values: dict[str, float | None]
    is_valid: bool
    is_warmup: bool
    data_quality: str
    version: str = "2.0.0"
    fingerprint: str | None = None


@dataclass(frozen=True)
class PivotRecord:
    """Record of a verified swing high or swing low pivot."""
    pivot_time: datetime
    pivot_price: float
    pivot_type: str  # "HIGH" or "LOW"
    confirmation_time: datetime
    confirmation_lag_bars: int
    left_bars: int
    right_bars: int
    timeframe: str
    index: int = -1
    confirmed_index: int = -1


@dataclass(frozen=True)
class StructureEventRecord:
    """Record of a market structure event (BOS, CHoCH, HH, HL, LH, LL)."""
    event_time: datetime
    event_type: str  # "HH", "HL", "LH", "LL", "BOS_BULL", "BOS_BEAR", "CHOCH_BULL", "CHOCH_BEAR"
    price: float
    broken_level: float | None
    broken_pivot_time: datetime | None
    confirmed_candle_time: datetime
    timeframe: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DivergenceRecord:
    """Record of a confirmed regular or hidden momentum divergence."""
    divergence_type: str  # "REGULAR_BULLISH", "REGULAR_BEARISH", "HIDDEN_BULLISH", "HIDDEN_BEARISH"
    indicator_name: str   # "RSI", "MACD_HIST"
    price_pivot_1_time: datetime
    price_pivot_1_price: float
    price_pivot_2_time: datetime
    price_pivot_2_price: float
    indicator_val_1: float
    indicator_val_2: float
    confirmation_time: datetime
    confirmation_lag_bars: int
    timeframe: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregatedCandle:
    """Higher-timeframe aggregated bar with completeness audit metadata."""
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades_count: int
    taker_buy_volume: float
    taker_buy_quote_volume: float
    is_confirmed: bool
    constituent_count: int
    expected_constituent_count: int
    is_complete: bool


@dataclass(frozen=True)
class LiquiditySweepRecord:
    """Record of a confirmed liquidity sweep / false breakout event."""
    sweep_type: str  # "SWEEP_HIGH" (bearish bias) | "SWEEP_LOW" (bullish bias)
    swept_level: float
    penetration_price: float
    close_price: float
    sweep_distance: float
    event_time: datetime
    confirmed_candle_time: datetime
    timeframe: str
    is_wick_reversal: bool = True
    swept_pivot_time: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SupportResistanceZoneRecord:
    """Record of a clustered horizontal support or resistance zone."""
    zone_type: str  # "SUPPORT" | "RESISTANCE"
    level_center: float
    level_min: float
    level_max: float
    touch_count: int
    first_touch_time: datetime
    last_touch_time: datetime
    confirmed_time: datetime
    strength_score: float
    is_active: bool
    timeframe: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BreakoutRetestRecord:
    """Record of a structural breakout and subsequent retest event."""
    direction: str  # "BULLISH" | "BEARISH"
    level_price: float
    level_pivot_time: datetime
    breakout_time: datetime
    breakout_confirmed_time: datetime
    breakout_price: float
    retest_time: datetime | None
    retest_confirmed_time: datetime | None
    retest_price: float | None
    status: str  # "SUCCESSFUL" | "FAILED" | "PENDING" | "EXPIRED"
    timeframe: str
    confirmed_time: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)
