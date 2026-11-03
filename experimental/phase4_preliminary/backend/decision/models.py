"""
Domain models, enums, and schemas for Phase 4: Decision & Trade Setup Engines.
Strictly conforms to Section 6, 7, 8, and 9 of PROJECT_SPECIFICATION.md.
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DirectionType(StrEnum):
    BULLISH = "BULLISH"
    POTENTIAL_BULLISH = "POTENTIAL_BULLISH"
    NEUTRAL = "NEUTRAL"
    POTENTIAL_BEARISH = "POTENTIAL_BEARISH"
    BEARISH = "BEARISH"


class SetupType(StrEnum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    RANGE_REJECTION = "RANGE_REJECTION"


class SetupStatus(StrEnum):
    IDENTIFIED = "IDENTIFIED"
    TRIGGERED = "TRIGGERED"
    TARGET_HIT = "TARGET_HIT"
    STOPPED_OUT = "STOPPED_OUT"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class TradeDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class MarketRegime(StrEnum):
    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    RANGE_BOUND = "RANGE_BOUND"
    VOLATILE_EXPANSION = "VOLATILE_EXPANSION"
    SESSION_INACTIVE = "SESSION_INACTIVE"


@dataclass
class EvidenceItem:
    factor: str
    description: str
    score_contribution: float
    is_supporting: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeyLevels:
    vwap: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    ema_100: float | None = None
    ema_200: float | None = None
    nearest_support: float | None = None
    nearest_resistance: float | None = None
    swing_high: float | None = None
    swing_low: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreBreakdown:
    # Six weighted dimensions summing to 100 max possible points
    structure_score: float = 0.0  # Max 25 pts
    mtf_trend_score: float = 0.0  # Max 20 pts
    momentum_score: float = 0.0  # Max 15 pts
    volume_score: float = 0.0  # Max 15 pts
    volatility_pa_score: float = 0.0  # Max 15 pts
    liquidity_score: float = 0.0  # Max 10 pts
    total_bullish: float = 0.0
    total_bearish: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DirectionAssessment:
    symbol: str
    assessment_time: datetime
    direction: DirectionType
    bullish_score: float
    bearish_score: float
    breakdown: ScoreBreakdown
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradicting_evidence: list[dict[str, Any]] = field(default_factory=list)
    timeframe_alignment: dict[str, Any] = field(default_factory=dict)
    key_levels: dict[str, Any] = field(default_factory=dict)
    invalidation_conditions: str = ""
    data_quality_score: float = 100.0
    market_regime: str = MarketRegime.RANGE_BOUND.value
    methodology_version: str = "v1.0.0"
    is_live: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["assessment_time"] = self.assessment_time.isoformat()
        data["direction"] = self.direction.value if isinstance(self.direction, DirectionType) else self.direction
        return data


@dataclass
class TradeSetupModel:
    symbol: str
    created_at: datetime
    status: SetupStatus
    setup_type: SetupType
    direction: TradeDirection
    timeframe: str
    entry_zone_min: float
    entry_zone_max: float
    stop_loss: float
    target_1: float
    target_2: float | None
    target_3: float | None
    risk_reward_ratio: float
    expiration_time: datetime
    invalidation_conditions: str
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    estimated_fees_pct: float = 0.0010  # 0.05% entry + 0.05% exit taker
    methodology_version: str = "v1.0.0"
    setup_id: uuid.UUID = field(default_factory=uuid.uuid4)
    triggered_at: datetime | None = None
    closed_at: datetime | None = None
    outcome: str | None = None
    realized_rr: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["setup_id"] = str(self.setup_id)
        data["created_at"] = self.created_at.isoformat()
        data["expiration_time"] = self.expiration_time.isoformat()
        data["status"] = self.status.value if isinstance(self.status, SetupStatus) else self.status
        data["setup_type"] = self.setup_type.value if isinstance(self.setup_type, SetupType) else self.setup_type
        data["direction"] = self.direction.value if isinstance(self.direction, TradeDirection) else self.direction
        if self.triggered_at:
            data["triggered_at"] = self.triggered_at.isoformat()
        if self.closed_at:
            data["closed_at"] = self.closed_at.isoformat()
        return data
