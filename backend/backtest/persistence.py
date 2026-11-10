"""
PostgreSQL Persistence and Query Repository for Backtesting & Historical Validation.
Conforms strictly to Section 8, 9, and 10 of PROJECT_SPECIFICATION.md:
- Persists backtest runs into backtest_runs.
- Persists performance analytics into backtest_metrics.
- Persists multi-horizon evaluations into signal_outcomes.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.backtest.models import (
    BacktestConfig,
    BacktestMetricsSummary,
    HorizonSignalRecord,
    SimulatedTrade,
)
from backend.database import get_async_session
from backend.models.tables import BacktestMetric, BacktestRun, SignalOutcome

logger = logging.getLogger(__name__)


class BacktestPersistence:
    """Handles database persistence and queries for historical backtesting and signal validation."""

    @classmethod
    async def save_backtest_run(
        cls,
        config: BacktestConfig,
        metrics: BacktestMetricsSummary,
        trades: list[SimulatedTrade],
        session: AsyncSession | None = None,
    ) -> uuid.UUID:
        """Persist a completed BacktestRun and BacktestMetric record."""
        now = datetime.now(UTC)
        start_t = config.start_time or (trades[0].entry_time if trades else now)
        end_t = config.end_time or (trades[-1].exit_time if trades else now)

        # Build strategy config payload
        strategy_config = {
            "initial_capital": config.initial_capital,
            "risk_per_trade_pct": config.risk_per_trade_pct,
            "in_sample_ratio": config.in_sample_ratio,
            "walk_forward_folds": config.walk_forward_folds,
            "primary_timeframe": config.primary_timeframe,
            "sub_bar_timeframe": config.sub_bar_timeframe,
            "walk_forward_results": metrics.walk_forward_folds,
            "in_sample_metrics": metrics.in_sample_metrics,
            "out_of_sample_metrics": metrics.out_of_sample_metrics,
            "trades_count": len(trades),
        }

        async def _do_save(s: AsyncSession) -> uuid.UUID:
            run_record = BacktestRun(
                run_id=metrics.run_id,
                name=config.name,
                start_time=start_t,
                end_time=end_t,
                in_sample_end=start_t + (end_t - start_t) * config.in_sample_ratio,
                timeframes=[config.primary_timeframe, config.sub_bar_timeframe, "4h", "1d", "15m"],
                strategy_config=strategy_config,
                trading_costs_config=config.trading_costs,
                methodology_version=config.methodology_version,
                executed_at=now,
            )
            s.add(run_record)
            await s.flush()

            metric_record = BacktestMetric(
                run_id=metrics.run_id,
                total_trades=metrics.total_trades,
                win_rate=metrics.win_rate,
                profit_factor=metrics.profit_factor,
                expectancy=metrics.expectancy,
                max_drawdown=metrics.max_drawdown,
                sharpe_ratio=metrics.sharpe_ratio,
                precision=metrics.precision,
                recall=metrics.recall,
                long_win_rate=metrics.long_win_rate,
                short_win_rate=metrics.short_win_rate,
                metrics_by_timeframe=metrics.metrics_by_timeframe,
                metrics_by_regime=metrics.metrics_by_regime,
            )
            s.add(metric_record)
            await s.flush()
            await s.commit()
            return metrics.run_id

        try:
            if session:
                return await _do_save(session)
            async with get_async_session() as s:
                return await _do_save(s)
        except SQLAlchemyError as exc:
            logger.error("Failed to save backtest run to PostgreSQL: %s", exc)
            if session:
                await session.rollback()
            return metrics.run_id

    @classmethod
    async def save_signal_outcomes(
        cls,
        records: list[HorizonSignalRecord],
        session: AsyncSession | None = None,
    ) -> int:
        """Persist directional horizon evaluations to signal_outcomes."""
        if not records:
            return 0

        async def _do_save_signals(s: AsyncSession) -> int:
            saved = 0
            for r in records:
                outcome_rec = SignalOutcome(
                    setup_id=None,  # Nullable for independent directional horizon evaluations
                    evaluated_at=r.evaluated_at,
                    horizon_candles=r.horizon_candles,
                    outcome=r.outcome,
                    max_favorable_excursion=r.max_favorable_excursion,
                    max_adverse_excursion=r.max_adverse_excursion,
                    realized_rr=r.realized_rr,
                    pnl_percent=r.pnl_percent,
                )
                s.add(outcome_rec)
                saved += 1
            await s.flush()
            await s.commit()
            return saved

        try:
            if session:
                return await _do_save_signals(session)
            async with get_async_session() as s:
                return await _do_save_signals(s)
        except SQLAlchemyError as exc:
            logger.error("Failed to save signal outcomes: %s", exc)
            if session:
                await session.rollback()
            return 0

    @classmethod
    async def get_backtest_runs(
        cls,
        session: AsyncSession,
        symbol: str = "XAUUSDT",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query historical backtest runs with summary performance metrics."""
        stmt = (
            select(BacktestRun, BacktestMetric)
            .outerjoin(BacktestMetric, BacktestRun.run_id == BacktestMetric.run_id)
            .order_by(BacktestRun.executed_at.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        rows = res.all()

        results: list[dict[str, Any]] = []
        for run, metric in rows:
            run_dict = {
                "run_id": str(run.run_id),
                "name": run.name,
                "start_time": run.start_time.isoformat(),
                "end_time": run.end_time.isoformat(),
                "in_sample_end": run.in_sample_end.isoformat() if run.in_sample_end else None,
                "timeframes": run.timeframes,
                "methodology_version": run.methodology_version,
                "executed_at": run.executed_at.isoformat(),
            }
            if metric:
                run_dict["metrics"] = {
                    "total_trades": metric.total_trades,
                    "win_rate": float(metric.win_rate),
                    "profit_factor": float(metric.profit_factor),
                    "expectancy": float(metric.expectancy),
                    "max_drawdown": float(metric.max_drawdown),
                    "sharpe_ratio": float(metric.sharpe_ratio) if metric.sharpe_ratio is not None else None,
                    "precision": float(metric.precision),
                    "recall": float(metric.recall),
                    "long_win_rate": float(metric.long_win_rate),
                    "short_win_rate": float(metric.short_win_rate),
                }
            results.append(run_dict)

        return results

    @classmethod
    async def get_backtest_run_detail(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Retrieve full details of a backtest run including walk-forward breakdown."""
        stmt = (
            select(BacktestRun, BacktestMetric)
            .outerjoin(BacktestMetric, BacktestRun.run_id == BacktestMetric.run_id)
            .where(BacktestRun.run_id == run_id)
        )
        res = await session.execute(stmt)
        row = res.first()

        if not row:
            return None

        run, metric = row
        return {
            "run_id": str(run.run_id),
            "name": run.name,
            "start_time": run.start_time.isoformat(),
            "end_time": run.end_time.isoformat(),
            "in_sample_end": run.in_sample_end.isoformat() if run.in_sample_end else None,
            "timeframes": run.timeframes,
            "strategy_config": run.strategy_config,
            "trading_costs_config": run.trading_costs_config,
            "methodology_version": run.methodology_version,
            "executed_at": run.executed_at.isoformat(),
            "metrics": {
                "total_trades": metric.total_trades if metric else 0,
                "win_rate": float(metric.win_rate) if metric else 0.0,
                "profit_factor": float(metric.profit_factor) if metric else 0.0,
                "expectancy": float(metric.expectancy) if metric else 0.0,
                "max_drawdown": float(metric.max_drawdown) if metric else 0.0,
                "sharpe_ratio": float(metric.sharpe_ratio) if metric and metric.sharpe_ratio is not None else None,
                "precision": float(metric.precision) if metric else 0.0,
                "recall": float(metric.recall) if metric else 0.0,
                "long_win_rate": float(metric.long_win_rate) if metric else 0.0,
                "short_win_rate": float(metric.short_win_rate) if metric else 0.0,
                "metrics_by_timeframe": metric.metrics_by_timeframe if metric else {},
                "metrics_by_regime": metric.metrics_by_regime if metric else {},
            },
        }

    @classmethod
    async def get_signals_history(
        cls,
        session: AsyncSession,
        horizon: int | None = None,
        outcome: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query historical horizon signal evaluations."""
        stmt = select(SignalOutcome)
        if horizon is not None:
            stmt = stmt.where(SignalOutcome.horizon_candles == horizon)
        if outcome is not None:
            stmt = stmt.where(SignalOutcome.outcome == outcome.upper())

        stmt = stmt.order_by(SignalOutcome.evaluated_at.desc()).limit(limit)
        res = await session.execute(stmt)
        records = res.scalars().all()

        return [
            {
                "id": r.id,
                "setup_id": str(r.setup_id) if r.setup_id else None,
                "evaluated_at": r.evaluated_at.isoformat(),
                "horizon_candles": r.horizon_candles,
                "outcome": r.outcome,
                "max_favorable_excursion": float(r.max_favorable_excursion),
                "max_adverse_excursion": float(r.max_adverse_excursion),
                "realized_rr": float(r.realized_rr) if r.realized_rr is not None else None,
                "pnl_percent": float(r.pnl_percent) if r.pnl_percent is not None else None,
            }
            for r in records
        ]
