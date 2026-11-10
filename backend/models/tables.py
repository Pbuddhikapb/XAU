"""
SQLAlchemy ORM models defining the 14 mandatory database tables.
Strictly conforms to Section 9 of PROJECT_SPECIFICATION.md.
"""

import uuid

from sqlalchemy import (
    BIGINT,
    BOOLEAN,
    INT,
    NUMERIC,
    TEXT,
    VARCHAR,
    Column,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base


class MarketMetadata(Base):
    """Stores contract parameters, precision filters, and operational specifications."""

    __tablename__ = "market_metadata"

    symbol = Column(VARCHAR(20), primary_key=True)
    pair = Column(VARCHAR(20), nullable=False)
    contract_type = Column(VARCHAR(50), nullable=False)
    underlying_type = Column(VARCHAR(50), nullable=False)
    base_asset = Column(VARCHAR(10), nullable=False)
    quote_asset = Column(VARCHAR(10), nullable=False)
    margin_asset = Column(VARCHAR(10), nullable=False)
    price_precision = Column(INT, nullable=False)
    quantity_precision = Column(INT, nullable=False)
    tick_size = Column(NUMERIC(18, 8), nullable=False)
    step_size = Column(NUMERIC(18, 8), nullable=False)
    min_notional = Column(NUMERIC(18, 8), nullable=False)
    maint_margin_percent = Column(NUMERIC(8, 4), nullable=False)
    onboard_timestamp = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(BOOLEAN, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class OHLCVCandle(Base):
    """Authoritative storage for OHLCV candles across all primary and secondary timeframes."""

    __tablename__ = "ohlcv_candles"

    symbol = Column(VARCHAR(20), nullable=False)
    timeframe = Column(VARCHAR(10), nullable=False)
    open_time = Column(DateTime(timezone=True), nullable=False)
    close_time = Column(DateTime(timezone=True), nullable=False)
    open = Column(NUMERIC(18, 4), nullable=False)
    high = Column(NUMERIC(18, 4), nullable=False)
    low = Column(NUMERIC(18, 4), nullable=False)
    close = Column(NUMERIC(18, 4), nullable=False)
    volume = Column(NUMERIC(24, 6), nullable=False)
    quote_volume = Column(NUMERIC(24, 6), nullable=False)
    trades_count = Column(BIGINT, nullable=False)
    taker_buy_volume = Column(NUMERIC(24, 6), nullable=False)
    taker_buy_quote_volume = Column(NUMERIC(24, 6), nullable=False)
    is_confirmed = Column(BOOLEAN, nullable=False, default=True)
    source = Column(VARCHAR(20), nullable=False, default="binance_vision")

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "timeframe", "open_time"),
        Index("idx_ohlcv_query", "symbol", "timeframe", "open_time"),
    )


class LiveMarketState(Base):
    """Single-row latest snapshot of live contract, mark, index, basis, and TradFi state."""

    __tablename__ = "live_market_state"

    symbol = Column(VARCHAR(20), primary_key=True)
    last_price = Column(NUMERIC(18, 4), nullable=False)
    mark_price = Column(NUMERIC(18, 4), nullable=False)
    index_price = Column(NUMERIC(18, 4), nullable=False)
    basis = Column(NUMERIC(18, 4), nullable=False)
    funding_rate = Column(NUMERIC(12, 8), nullable=False)
    next_funding_time = Column(DateTime(timezone=True), nullable=False)
    best_bid = Column(NUMERIC(18, 4), nullable=False)
    best_ask = Column(NUMERIC(18, 4), nullable=False)
    spread = Column(NUMERIC(18, 4), nullable=False)
    tradfi_session_state = Column(VARCHAR(20), nullable=False)  # OPEN, CLOSED, DAILY_BREAK
    last_update = Column(DateTime(timezone=True), nullable=False)


class MarkIndexPrice(Base):
    """Synchronized price series tracking contract, mark, and index price divergence."""

    __tablename__ = "mark_index_prices"

    symbol = Column(VARCHAR(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    contract_price = Column(NUMERIC(18, 4), nullable=False)
    mark_price = Column(NUMERIC(18, 4), nullable=False)
    index_price = Column(NUMERIC(18, 4), nullable=False)
    basis = Column(NUMERIC(18, 4), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "timestamp"),
        Index("idx_mark_index_time", "symbol", "timestamp"),
    )


class OrderbookSnapshot(Base):
    """Downsampled order book depth snapshots for liquidity and spread analysis."""

    __tablename__ = "orderbook_snapshots"

    symbol = Column(VARCHAR(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    bid_depth_json = Column(JSONB, nullable=False)
    ask_depth_json = Column(JSONB, nullable=False)
    imbalance_ratio = Column(NUMERIC(8, 4), nullable=False)
    spread = Column(NUMERIC(18, 4), nullable=False)
    top_cluster_bid = Column(NUMERIC(18, 4), nullable=True)
    top_cluster_ask = Column(NUMERIC(18, 4), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "timestamp"),
        Index("idx_orderbook_time", "symbol", "timestamp"),
    )


class FundingHistory(Base):
    """Settled 8-hour funding rates."""

    __tablename__ = "funding_history"

    symbol = Column(VARCHAR(20), nullable=False)
    funding_time = Column(DateTime(timezone=True), nullable=False)
    funding_rate = Column(NUMERIC(12, 8), nullable=False)
    mark_price = Column(NUMERIC(18, 4), nullable=False)

    __table_args__ = (PrimaryKeyConstraint("symbol", "funding_time"),)


class IndicatorSnapshot(Base):
    """Immutable calculation records for every confirmed candle close."""

    __tablename__ = "indicator_snapshots"

    symbol = Column(VARCHAR(20), nullable=False)
    timeframe = Column(VARCHAR(10), nullable=False)
    candle_time = Column(DateTime(timezone=True), nullable=False)
    ema_20 = Column(NUMERIC(18, 4), nullable=True)
    ema_50 = Column(NUMERIC(18, 4), nullable=True)
    ema_100 = Column(NUMERIC(18, 4), nullable=True)
    ema_200 = Column(NUMERIC(18, 4), nullable=True)
    adx = Column(NUMERIC(8, 4), nullable=True)
    trend_strength = Column(NUMERIC(8, 4), nullable=True)
    rsi_14 = Column(NUMERIC(8, 4), nullable=True)
    macd_val = Column(NUMERIC(18, 4), nullable=True)
    macd_signal = Column(NUMERIC(18, 4), nullable=True)
    macd_hist = Column(NUMERIC(18, 4), nullable=True)
    atr_14 = Column(NUMERIC(18, 4), nullable=True)
    bb_upper = Column(NUMERIC(18, 4), nullable=True)
    bb_middle = Column(NUMERIC(18, 4), nullable=True)
    bb_lower = Column(NUMERIC(18, 4), nullable=True)
    volatility_percentile = Column(NUMERIC(8, 4), nullable=True)
    relative_volume = Column(NUMERIC(8, 4), nullable=True)
    taker_buy_ratio = Column(NUMERIC(8, 4), nullable=True)
    vwap = Column(NUMERIC(18, 4), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "timeframe", "candle_time"),
        Index("idx_indicator_query", "symbol", "timeframe", "candle_time"),
    )


class StructureEvent(Base):
    """Market structure events (Swing High/Low, BOS, CHoCH)."""

    __tablename__ = "structure_events"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    symbol = Column(VARCHAR(20), nullable=False)
    timeframe = Column(VARCHAR(10), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)
    # Event types: SWING_HIGH, SWING_LOW, BOS_BULL, BOS_BEAR, CHOCH_BULL, CHOCH_BEAR
    event_type = Column(VARCHAR(20), nullable=False)
    price = Column(NUMERIC(18, 4), nullable=False)
    invalidated_level = Column(NUMERIC(18, 4), nullable=True)
    confirmed_candle_time = Column(DateTime(timezone=True), nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=True)

    __table_args__ = (Index("idx_structure_time", "symbol", "timeframe", "event_time"),)


class MarketAnalysis(Base):
    """Engine A output: Market direction, bullish/bearish scores, and supporting evidence."""

    __tablename__ = "market_analysis"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    symbol = Column(VARCHAR(20), nullable=False)
    assessment_time = Column(DateTime(timezone=True), nullable=False)
    direction = Column(VARCHAR(25), nullable=False)  # BULLISH, POTENTIAL BULLISH, NEUTRAL, POTENTIAL BEARISH, BEARISH
    bullish_score = Column(NUMERIC(5, 2), nullable=False)
    bearish_score = Column(NUMERIC(5, 2), nullable=False)
    structure_score = Column(NUMERIC(5, 2), nullable=False)
    mtf_trend_score = Column(NUMERIC(5, 2), nullable=False)
    momentum_score = Column(NUMERIC(5, 2), nullable=False)
    volume_score = Column(NUMERIC(5, 2), nullable=False)
    liquidity_score = Column(NUMERIC(5, 2), nullable=False)
    volatility_pa_score = Column(NUMERIC(5, 2), nullable=False)
    supporting_evidence = Column(JSONB, nullable=False)
    contradicting_evidence = Column(JSONB, nullable=False)
    timeframe_alignment = Column(JSONB, nullable=False)
    key_levels = Column(JSONB, nullable=False)
    invalidation_conditions = Column(TEXT, nullable=False)
    data_quality_score = Column(NUMERIC(5, 2), nullable=False)
    methodology_version = Column(VARCHAR(20), nullable=False)
    is_live = Column(BOOLEAN, nullable=False, default=True)

    __table_args__ = (Index("idx_analysis_time", "symbol", "assessment_time"),)


class TradeSetup(Base):
    """Engine B output: Specific trade setups with levels and invalidation."""

    __tablename__ = "trade_setups"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    setup_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    symbol = Column(VARCHAR(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    # Statuses: POTENTIAL LONG/SHORT, CONFIRMED LONG/SHORT, INVALIDATED, EXPIRED
    status = Column(VARCHAR(20), nullable=False)
    setup_type = Column(VARCHAR(50), nullable=False)
    direction = Column(VARCHAR(10), nullable=False)  # LONG, SHORT
    timeframe = Column(VARCHAR(10), nullable=False)
    entry_zone_min = Column(NUMERIC(18, 4), nullable=False)
    entry_zone_max = Column(NUMERIC(18, 4), nullable=False)
    stop_loss = Column(NUMERIC(18, 4), nullable=False)
    target_1 = Column(NUMERIC(18, 4), nullable=False)
    target_2 = Column(NUMERIC(18, 4), nullable=True)
    target_3 = Column(NUMERIC(18, 4), nullable=True)
    risk_reward_ratio = Column(NUMERIC(6, 2), nullable=False)
    expiration_time = Column(DateTime(timezone=True), nullable=False)
    invalidation_conditions = Column(TEXT, nullable=False)
    supporting_evidence = Column(JSONB, nullable=False)
    estimated_fees_pct = Column(NUMERIC(6, 4), nullable=False)
    methodology_version = Column(VARCHAR(20), nullable=False)
    active_stop_loss = Column(NUMERIC(18, 4), nullable=True)
    breakeven_locked = Column(BOOLEAN, nullable=False, default=False, server_default="false")

    __table_args__ = (Index("idx_setups_time", "symbol", "created_at"),)


class SignalOutcome(Base):
    """Historical tracking of trade setup and signal performance."""

    __tablename__ = "signal_outcomes"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    setup_id = Column(UUID(as_uuid=True), ForeignKey("trade_setups.setup_id"), nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    horizon_candles = Column(INT, nullable=False)  # 5, 10, 20, 50
    outcome = Column(VARCHAR(20), nullable=False)  # TARGET_HIT, STOPPED_OUT, EXPIRED, FAVORABLE_FIRST, ADVERSE_FIRST
    max_favorable_excursion = Column(NUMERIC(18, 4), nullable=False)
    max_adverse_excursion = Column(NUMERIC(18, 4), nullable=False)
    realized_rr = Column(NUMERIC(6, 2), nullable=True)
    pnl_percent = Column(NUMERIC(8, 4), nullable=True)

    __table_args__ = (Index("idx_outcomes_setup", "setup_id"),)


class BacktestRun(Base):
    """Backtesting execution log."""

    __tablename__ = "backtest_runs"

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(VARCHAR(100), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    in_sample_end = Column(DateTime(timezone=True), nullable=True)
    timeframes = Column(JSONB, nullable=False)
    strategy_config = Column(JSONB, nullable=False)
    trading_costs_config = Column(JSONB, nullable=False)
    methodology_version = Column(VARCHAR(20), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    metric = relationship("BacktestMetric", backref="run", uselist=False, cascade="all, delete-orphan")


class BacktestMetric(Base):
    """Detailed performance metrics for a backtest run."""

    __tablename__ = "backtest_metrics"

    run_id = Column(UUID(as_uuid=True), ForeignKey("backtest_runs.run_id"), primary_key=True)
    total_trades = Column(INT, nullable=False)
    win_rate = Column(NUMERIC(6, 2), nullable=False)
    profit_factor = Column(NUMERIC(8, 4), nullable=False)
    expectancy = Column(NUMERIC(10, 4), nullable=False)
    max_drawdown = Column(NUMERIC(6, 2), nullable=False)
    sharpe_ratio = Column(NUMERIC(6, 2), nullable=True)
    precision = Column(NUMERIC(6, 2), nullable=False)
    recall = Column(NUMERIC(6, 2), nullable=False)
    long_win_rate = Column(NUMERIC(6, 2), nullable=False)
    short_win_rate = Column(NUMERIC(6, 2), nullable=False)
    metrics_by_timeframe = Column(JSONB, nullable=False)
    metrics_by_regime = Column(JSONB, nullable=False)


class SystemHealth(Base):
    """System health telemetry, heartbeat, data lag, and reconnection logs."""

    __tablename__ = "system_health"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    subsystem = Column(VARCHAR(50), nullable=False)
    status = Column(VARCHAR(20), nullable=False)  # OK, DEGRADED, RECONNECTING, ERROR
    lag_ms = Column(INT, nullable=False)
    details = Column(JSONB, nullable=True)

    __table_args__ = (Index("idx_health_time", "timestamp"),)
