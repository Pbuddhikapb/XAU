"""
Domain models, schemas, and dataclasses for Phase 5 Backtesting & Historical Validation.
Conforms strictly to Section 8, 9, and 10 of PROJECT_SPECIFICATION.md.
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class BacktestConfig:
    """Configuration for historical backtest run."""

    name: str = "XAUUSDT-WalkForward-Backtest"
    symbol: str = "XAUUSDT"
    start_time: datetime | None = None
    end_time: datetime | None = None
    in_sample_ratio: float = 0.70  # 70% in-sample / 30% out-of-sample
    walk_forward_folds: int = 3
    primary_timeframe: str = "1h"
    sub_bar_timeframe: str = "5m"
    initial_capital: float = 100_000.0
    risk_per_trade_pct: float = 0.01  # 1% equity risk per trade
    trading_costs: dict[str, float] = field(
        default_factory=lambda: {
            "taker_fee": 0.0010,
            "slippage": 0.0002,
            "spread": 0.0001,
            "funding": 0.0001,
            "total_friction": 0.0014,
        }
    )
    methodology_version: str = "v1.2.0-phase5"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.start_time:
            data["start_time"] = self.start_time.isoformat()
        if self.end_time:
            data["end_time"] = self.end_time.isoformat()
        return data


@dataclass
class SimulatedTrade:
    """Record of a simulated trade executed during backtesting."""

    trade_id: uuid.UUID
    setup_id: uuid.UUID
    symbol: str
    direction: str  # LONG or SHORT
    setup_type: str
    entry_time: datetime
    entry_price: float
    initial_stop_loss: float
    target_1: float
    target_2: float | None
    target_3: float | None
    exit_time: datetime
    exit_price: float
    exit_reason: str  # TARGET_1_HIT, TARGET_2_HIT, TARGET_3_HIT, STOPPED_OUT, STOPPED_OUT_BREAKEVEN, EXPIRED
    planned_rr: float
    realized_rr: float
    pnl_usd: float
    pnl_pct: float
    is_in_sample: bool
    market_regime: str
    active_stop_loss: float | None = None
    breakeven_locked: bool = False
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trade_id"] = str(self.trade_id)
        data["setup_id"] = str(self.setup_id)
        data["entry_time"] = self.entry_time.isoformat()
        data["exit_time"] = self.exit_time.isoformat()
        return data


@dataclass
class HorizonSignalRecord:
    """Evaluation of an Engine A directional signal over a specific candle horizon."""

    signal_id: uuid.UUID
    setup_id: uuid.UUID
    symbol: str
    direction: str
    assessment_time: datetime
    horizon_candles: int  # 5, 10, 20, 50
    evaluated_at: datetime
    outcome: str  # FAVORABLE_FIRST, ADVERSE_FIRST, NEUTRAL_RANGE, TARGET_HIT, STOPPED_OUT
    max_favorable_excursion: float
    max_adverse_excursion: float
    realized_rr: float
    pnl_percent: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signal_id"] = str(self.signal_id)
        data["setup_id"] = str(self.setup_id)
        data["assessment_time"] = self.assessment_time.isoformat()
        data["evaluated_at"] = self.evaluated_at.isoformat()
        return data


@dataclass
class BacktestMetricsSummary:
    """Complete statistical metrics conforming strictly to Section 8."""

    run_id: uuid.UUID
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    max_drawdown_duration_bars: int
    sharpe_ratio: float | None
    precision: float
    recall: float
    long_win_rate: float
    short_win_rate: float
    long_trades_count: int
    short_trades_count: int
    metrics_by_timeframe: dict[str, Any]
    metrics_by_regime: dict[str, Any]
    in_sample_metrics: dict[str, Any] = field(default_factory=dict)
    out_of_sample_metrics: dict[str, Any] = field(default_factory=dict)
    walk_forward_folds: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["run_id"] = str(self.run_id)
        return data


class BacktestRunRequest(BaseModel):
    """Pydantic model for POST /api/v1/backtests/run."""

    name: str = Field(default="API-WalkForward-Run", description="Identifier name for the run")
    symbol: str = Field(default="XAUUSDT", description="Instrument symbol")
    start_time: datetime | None = Field(default=None, description="Start time for backtest window")
    end_time: datetime | None = Field(default=None, description="End time for backtest window")
    in_sample_ratio: float = Field(default=0.70, ge=0.1, le=0.9, description="In-sample data ratio")
    walk_forward_folds: int = Field(default=3, ge=1, le=10, description="Number of walk-forward rolling folds")
    initial_capital: float = Field(default=100_000.0, ge=1000.0, description="Starting equity USD")
    risk_per_trade_pct: float = Field(default=0.01, ge=0.001, le=0.05, description="Equity risk per trade")
