"""
CLI Benchmark Runner and Execution Controller for Phase 5 Backtesting.
Conforms to Section 8, 9, and 10 of PROJECT_SPECIFICATION.md.
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.backtest.engine import BacktestEngine
from backend.backtest.models import BacktestConfig, BacktestRunRequest
from backend.backtest.persistence import BacktestPersistence
from backend.database import get_async_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backtest_runner")


class BacktestRunner:
    """Orchestrates backtest execution from CLI and API requests."""

    @classmethod
    async def execute_and_persist(
        cls,
        request: BacktestRunRequest,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Execute a backtest run and persist all results and signals to PostgreSQL."""
        config = BacktestConfig(
            name=request.name,
            symbol=request.symbol,
            start_time=request.start_time,
            end_time=request.end_time,
            in_sample_ratio=request.in_sample_ratio,
            walk_forward_folds=request.walk_forward_folds,
            initial_capital=request.initial_capital,
            risk_per_trade_pct=request.risk_per_trade_pct,
        )

        engine = BacktestEngine(config)
        logger.info("Loading historical candles from DB for %s...", config.symbol)
        raw_candles = await engine.load_historical_candles_from_db(
            symbol=config.symbol,
            start_time=config.start_time,
            end_time=config.end_time,
        )

        logger.info("Starting chronological walk-forward simulation...")
        summary, trades, signals = await asyncio.to_thread(engine.run, raw_candles)

        logger.info(
            "Backtest completed: %d trades (Win Rate: %.2f%%, Profit Factor: %.2f, Max DD: %.2f%%)",
            summary.total_trades,
            summary.win_rate,
            summary.profit_factor,
            summary.max_drawdown,
        )

        # Persist to PostgreSQL
        await BacktestPersistence.save_backtest_run(
            config=config, metrics=summary, trades=trades, session=session
        )
        if signals:
            saved_signals = await BacktestPersistence.save_signal_outcomes(signals, session=session)
            logger.info("Persisted %d horizon signal outcome evaluations", saved_signals)

        return {
            "run_id": str(summary.run_id),
            "run": {
                "run_id": str(summary.run_id),
                "name": config.name,
                "symbol": config.symbol,
                "start_time": config.start_time.isoformat() if config.start_time else None,
                "end_time": config.end_time.isoformat() if config.end_time else None,
                "initial_balance": config.initial_capital,
            },
            "name": config.name,
            "symbol": config.symbol,
            "total_trades": summary.total_trades,
            "win_rate": summary.win_rate,
            "profit_factor": summary.profit_factor,
            "expectancy": summary.expectancy,
            "max_drawdown": summary.max_drawdown,
            "sharpe_ratio": summary.sharpe_ratio,
            "precision": summary.precision,
            "recall": summary.recall,
            "in_sample_metrics": summary.in_sample_metrics,
            "out_of_sample_metrics": summary.out_of_sample_metrics,
            "walk_forward_folds": summary.walk_forward_folds,
            "signal_outcomes_count": len(signals),
        }


def main() -> None:
    """CLI entry point for python -m backend.backtest.runner."""
    parser = argparse.ArgumentParser(description="XAUUSDT Historical Backtesting Engine (Phase 5)")
    parser.add_argument("--name", type=str, default="XAUUSDT-Benchmark-Run", help="Backtest run name")
    parser.add_argument("--symbol", type=str, default="XAUUSDT", help="Trading symbol")
    parser.add_argument("--start", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--in-sample-ratio", type=float, default=0.70, help="In-sample partition ratio")
    parser.add_argument("--walk-forward-folds", type=int, default=3, help="Walk-forward rolling folds")

    args = parser.parse_args()

    start_dt = datetime.fromisoformat(args.start).replace(tzinfo=UTC) if args.start else None
    end_dt = datetime.fromisoformat(args.end).replace(tzinfo=UTC) if args.end else None

    req = BacktestRunRequest(
        name=args.name,
        symbol=args.symbol,
        start_time=start_dt,
        end_time=end_dt,
        in_sample_ratio=args.in_sample_ratio,
        walk_forward_folds=args.walk_forward_folds,
    )

    async def _run():
        async with get_async_session() as session:
            result = await BacktestRunner.execute_and_persist(req, session)
            print("\n================ BACKTEST RESULTS SUMMARY ================")
            print(f"Run ID:         {result['run_id']}")
            print(f"Name:           {result['name']}")
            print(f"Total Trades:   {result['total_trades']}")
            print(f"Win Rate:       {result['win_rate']:.2f}%")
            print(f"Profit Factor:  {result['profit_factor']:.2f}")
            print(f"Max Drawdown:   {result['max_drawdown']:.2f}%")
            print(f"Expectancy:     ${result['expectancy']:.2f}")
            print(f"Sharpe Ratio:   {result['sharpe_ratio']}")
            print("---------------- In-Sample vs Out-of-Sample --------------")
            print(f"In-Sample Trades:  {result['in_sample_metrics'].get('total_trades', 0)}")
            print(f"In-Sample Win Rate:{result['in_sample_metrics'].get('win_rate', 0.0):.2f}%")
            print(f"Out-of-Sample Trades: {result['out_of_sample_metrics'].get('total_trades', 0)}")
            print(f"Out-of-Sample Win Rate: {result['out_of_sample_metrics'].get('win_rate', 0.0):.2f}%")
            print("==========================================================\n")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
