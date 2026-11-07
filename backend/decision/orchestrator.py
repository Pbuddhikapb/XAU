"""
Unified Decision Orchestrator for Binance XAUUSDT.
Strictly conforms to Section 6, 7, 8, 9, and 10 of PROJECT_SPECIFICATION.md:
- Orchestrates IndicatorEngine, StructureEngine, MTF alignment, and SessionTracker.
- Executes Engine A (Directional Scoring) and Engine B (Trade Setup Identification).
- Persists outputs into PostgreSQL tables market_analysis and trade_setups.
- Authoritative pipeline shared across live streaming and historical backtesting.
- Methodology Version: v1.1.0-phase4
"""

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analytics.indicator_engine import IndicatorEngine
from backend.config import settings
from backend.data.session_tracker import SessionTracker
from backend.database import get_async_session
from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    SetupStatus,
    SetupType,
    TradeDirection,
    TradeSetupModel,
)
from backend.decision.scoring_engine import DirectionalScoringEngine
from backend.decision.setup_engine import TradeSetupEngine
from backend.models.tables import MarketAnalysis, OHLCVCandle, TradeSetup
from backend.structure.structure_engine import StructureEngine

logger = logging.getLogger(__name__)


class DecisionOrchestrator:
    """Authoritative Decision & Trade Setup Pipeline Orchestrator."""

    @classmethod
    def process_timeframe_data(
        cls,
        raw_candles_by_tf: dict[str, pd.DataFrame],
        symbol: str = "XAUUSDT",
        as_of_time: datetime | None = None,
        is_live: bool = True,
        require_completed_candles: bool = True,
    ) -> tuple[DirectionAssessment, list[TradeSetupModel]]:
        """
        Pure calculation pipeline:
        Takes a dict of raw OHLCV DataFrames for each timeframe,
        computes indicators and structure, and evaluates Direction and Setups.
        """
        if as_of_time is None:
            as_of_time = datetime.now(UTC)

        processed_tf_data: dict[str, dict[str, Any]] = {}

        for tf, df_raw in raw_candles_by_tf.items():
            if df_raw.empty:
                continue

            # 1. Compute indicators
            df_ind = IndicatorEngine.compute_all_indicators(df_raw, symbol=symbol, timeframe=tf, time_col="open_time")

            # 2. Compute market structure
            struct_res = StructureEngine.analyze_timeframe(df_ind, timeframe=tf, swing_window=3, time_col="open_time")

            processed_tf_data[tf] = {
                "df": df_ind,
                "structure": struct_res,
            }

        # Check CME Gold trading session status
        session_active = SessionTracker.is_underlying_active(as_of_time)

        # 3. Engine A: Directional Scoring
        assessment = DirectionalScoringEngine.evaluate(
            timeframe_data=processed_tf_data,
            symbol=symbol,
            session_is_active=session_active,
            assessment_time=as_of_time,
            is_live=is_live,
        )

        # 4. Engine B: Trade Setup Identification
        setups = TradeSetupEngine.identify_setups(
            assessment=assessment,
            timeframe_data=processed_tf_data,
            symbol=symbol,
            as_of_time=as_of_time,
            require_completed_candles=require_completed_candles,
        )

        return assessment, setups

    @classmethod
    async def run_current_pipeline(
        cls, symbol: str = "XAUUSDT", persist: bool = True
    ) -> tuple[DirectionAssessment, list[TradeSetupModel]]:
        """
        Query recent candles across 1D, 4H, 1H, 15M, and 5M from the database,
        execute Engine A and Engine B, and optionally persist the results.
        """
        timeframes = settings.PRIMARY_TIMEFRAMES
        raw_candles: dict[str, pd.DataFrame] = {}

        try:
            async with get_async_session() as session:
                for tf in timeframes:
                    stmt = (
                        select(OHLCVCandle)
                        .where(OHLCVCandle.symbol == symbol.upper(), OHLCVCandle.timeframe == tf)
                        .order_by(OHLCVCandle.open_time.desc())
                        .limit(150)
                    )
                    res = await session.execute(stmt)
                    candles = list(reversed(res.scalars().all()))

                    if candles:
                        df = pd.DataFrame(
                            [
                                {
                                    "open_time": c.open_time,
                                    "open": float(c.open),
                                    "high": float(c.high),
                                    "low": float(c.low),
                                    "close": float(c.close),
                                    "volume": float(c.volume),
                                    "taker_buy_volume": float(c.taker_buy_volume)
                                    if c.taker_buy_volume is not None
                                    else 0.0,
                                }
                                for c in candles
                            ]
                        )
                        raw_candles[tf] = df
        except (SQLAlchemyError, ValueError, KeyError, TypeError, OSError) as e:
            logger.error("Failed to query candles for decision pipeline: %s", e)

        assessment, setups = cls.process_timeframe_data(
            raw_candles_by_tf=raw_candles,
            symbol=symbol,
            as_of_time=datetime.now(UTC),
            is_live=True,
        )

        if persist:
            await cls.persist_assessment(assessment)
            if setups:
                await cls.persist_setups(setups)

        return assessment, setups

    @classmethod
    async def persist_assessment(cls, assessment: DirectionAssessment) -> bool:
        """Persist DirectionAssessment to PostgreSQL market_analysis table."""
        try:
            async with get_async_session() as session:
                record = MarketAnalysis(
                    symbol=assessment.symbol,
                    assessment_time=assessment.assessment_time,
                    direction=assessment.direction.value
                    if isinstance(assessment.direction, DirectionType)
                    else assessment.direction,
                    bullish_score=assessment.bullish_score,
                    bearish_score=assessment.bearish_score,
                    structure_score=assessment.breakdown.structure_score,
                    mtf_trend_score=assessment.breakdown.mtf_trend_score,
                    momentum_score=assessment.breakdown.momentum_score,
                    volume_score=assessment.breakdown.volume_score,
                    liquidity_score=assessment.breakdown.liquidity_score,
                    volatility_pa_score=assessment.breakdown.volatility_pa_score,
                    supporting_evidence=assessment.supporting_evidence,
                    contradicting_evidence=assessment.contradicting_evidence,
                    timeframe_alignment=assessment.timeframe_alignment,
                    key_levels=assessment.key_levels,
                    invalidation_conditions=assessment.invalidation_conditions,
                    data_quality_score=assessment.data_quality_score,
                    methodology_version=assessment.methodology_version,
                    is_live=assessment.is_live,
                )
                session.add(record)
                await session.commit()
                return True
        except SQLAlchemyError as exc:
            logger.error("Failed to persist MarketAnalysis: %s", exc)
            return False

    @classmethod
    async def persist_setups(cls, setups: list[TradeSetupModel]) -> int:
        """Persist TradeSetups to PostgreSQL trade_setups table."""
        if not setups:
            return 0

        persisted = 0
        try:
            async with get_async_session() as session:
                for s in setups:
                    record = TradeSetup(
                        setup_id=s.setup_id,
                        symbol=s.symbol,
                        created_at=s.created_at,
                        status=s.status.value if isinstance(s.status, SetupStatus) else s.status,
                        setup_type=s.setup_type.value if isinstance(s.setup_type, SetupType) else s.setup_type,
                        direction=s.direction.value if isinstance(s.direction, TradeDirection) else s.direction,
                        timeframe=s.timeframe,
                        entry_zone_min=s.entry_zone_min,
                        entry_zone_max=s.entry_zone_max,
                        stop_loss=s.stop_loss,
                        target_1=s.target_1,
                        target_2=s.target_2,
                        target_3=s.target_3,
                        risk_reward_ratio=s.risk_reward_ratio,
                        expiration_time=s.expiration_time,
                        invalidation_conditions=s.invalidation_conditions,
                        supporting_evidence=s.supporting_evidence,
                        estimated_fees_pct=s.estimated_fees_pct,
                        methodology_version=s.methodology_version,
                    )
                    session.add(record)
                    persisted += 1
                await session.commit()
        except SQLAlchemyError as exc:
            logger.error("Failed to persist TradeSetups: %s", exc)

        return persisted

    @classmethod
    async def get_or_compute_latest_analysis(
        cls,
        session: AsyncSession,
        symbol: str = "XAUUSDT",
        max_age_seconds: int = 60,
    ) -> dict[str, Any]:
        """
        Fast-path: Query latest cached analysis from PostgreSQL market_analysis.
        If cache is missing or older than max_age_seconds, compute on demand and persist.
        """
        stmt = (
            select(MarketAnalysis)
            .where(MarketAnalysis.symbol == symbol.upper())
            .order_by(MarketAnalysis.assessment_time.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        now = datetime.now(UTC)
        if record is not None:
            rec_time = record.assessment_time
            if rec_time.tzinfo is None:
                rec_time = rec_time.replace(tzinfo=UTC)
            age = (now - rec_time).total_seconds()
            if age <= max_age_seconds:
                return {
                    "symbol": record.symbol,
                    "assessment_time": rec_time.isoformat(),
                    "direction": record.direction,
                    "bullish_score": float(record.bullish_score),
                    "bearish_score": float(record.bearish_score),
                    "score_label": "HEURISTIC_INDICATOR_SCORE",
                    "breakdown": {
                        "structure_score": float(record.structure_score),
                        "mtf_trend_score": float(record.mtf_trend_score),
                        "momentum_score": float(record.momentum_score),
                        "volume_score": float(record.volume_score),
                        "liquidity_score": float(record.liquidity_score),
                        "volatility_pa_score": float(record.volatility_pa_score),
                    },
                    "supporting_evidence": record.supporting_evidence,
                    "contradicting_evidence": record.contradicting_evidence,
                    "timeframe_alignment": record.timeframe_alignment,
                    "key_levels": record.key_levels,
                    "invalidation_conditions": record.invalidation_conditions,
                    "data_quality_score": float(record.data_quality_score),
                    "methodology_version": record.methodology_version,
                    "is_live": record.is_live,
                    "source": "CACHE",
                }

        # Fallback path: compute live and persist
        assessment, _ = await cls.run_current_pipeline(symbol=symbol, persist=True)
        return {
            "symbol": assessment.symbol,
            "assessment_time": assessment.assessment_time.isoformat(),
            "direction": assessment.direction.value if hasattr(assessment.direction, "value") else assessment.direction,
            "bullish_score": assessment.bullish_score,
            "bearish_score": assessment.bearish_score,
            "score_label": assessment.score_label,
            "breakdown": {
                "structure_score": assessment.breakdown.structure_score,
                "mtf_trend_score": assessment.breakdown.mtf_trend_score,
                "momentum_score": assessment.breakdown.momentum_score,
                "volume_score": assessment.breakdown.volume_score,
                "liquidity_score": assessment.breakdown.liquidity_score,
                "volatility_pa_score": assessment.breakdown.volatility_pa_score,
            },
            "supporting_evidence": assessment.supporting_evidence,
            "contradicting_evidence": assessment.contradicting_evidence,
            "timeframe_alignment": assessment.timeframe_alignment,
            "key_levels": (
                assessment.key_levels.to_dict()
                if hasattr(assessment.key_levels, "to_dict")
                else assessment.key_levels
            ),
            "invalidation_conditions": assessment.invalidation_conditions,
            "data_quality_score": assessment.data_quality_score,
            "methodology_version": assessment.methodology_version,
            "is_live": assessment.is_live,
            "source": "COMPUTED",
        }
