"""
Multi-Resolution Event-Driven Walk-Forward Backtesting Engine.
Strictly conforms to Section 8, 9, and 10 of PROJECT_SPECIFICATION.md:
- No lookahead bias, no future leakage, no repainting.
- Shares the exact calculation and decision logic with live trading (DecisionOrchestrator & SetupLifecycleTracker).
- Multi-resolution: 1H setups & directional scoring, 5M sub-bar execution tracking.
- Independent out-of-sample evaluation (70% in-sample / 30% out-of-sample) + walk-forward folds.
- Realistic trading costs: 0.14% total friction (taker + slippage + spread + funding).
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.analytics.indicator_engine import IndicatorEngine
from backend.backtest.metrics import MetricsCalculator
from backend.backtest.models import (
    BacktestConfig,
    BacktestMetricsSummary,
    HorizonSignalRecord,
    SimulatedTrade,
)
from backend.backtest.signal_evaluator import DirectionalSignalEvaluator
from backend.database import get_async_session
from backend.decision.lifecycle import SetupLifecycleTracker
from backend.decision.models import (
    DirectionType,
    MarketRegime,
    SetupStatus,
    TradeDirection,
    TradeSetupModel,
)
from backend.decision.orchestrator import DecisionOrchestrator
from backend.models.tables import OHLCVCandle

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Authoritative Historical Backtesting & Validation Engine."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.run_id = uuid.uuid4()

    async def load_historical_candles_from_db(
        self,
        symbol: str = "XAUUSDT",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load historical multi-timeframe candles from PostgreSQL."""
        timeframes = ["1d", "4h", "1h", "15m", "5m"]
        candles_by_tf: dict[str, pd.DataFrame] = {}

        try:
            async with get_async_session() as session:
                for tf in timeframes:
                    stmt = select(OHLCVCandle).where(
                        OHLCVCandle.symbol == symbol.upper(),
                        OHLCVCandle.timeframe == tf,
                    )
                    if start_time:
                        stmt = stmt.where(OHLCVCandle.open_time >= start_time)
                    if end_time:
                        stmt = stmt.where(OHLCVCandle.open_time <= end_time)

                    stmt = stmt.order_by(OHLCVCandle.open_time.asc())
                    res = await session.execute(stmt)
                    rows = res.scalars().all()

                    if rows:
                        df = pd.DataFrame(
                            [
                                {
                                    "open_time": r.open_time,
                                    "close_time": r.close_time,
                                    "open": float(r.open),
                                    "high": float(r.high),
                                    "low": float(r.low),
                                    "close": float(r.close),
                                    "volume": float(r.volume),
                                    "taker_buy_volume": float(r.taker_buy_volume or 0.0),
                                }
                                for r in rows
                            ]
                        )
                        candles_by_tf[tf] = df
                    else:
                        candles_by_tf[tf] = pd.DataFrame()
        except SQLAlchemyError as exc:
            logger.error("Failed to load historical candles: %s", exc)

        return candles_by_tf

    def run(
        self,
        raw_candles_by_tf: dict[str, pd.DataFrame],
    ) -> tuple[BacktestMetricsSummary, list[SimulatedTrade], list[HorizonSignalRecord]]:
        """
        Execute chronological walk-forward backtest.
        Guarantees zero lookahead bias by strictly slicing candles up to t_eval.
        """
        df_1h = raw_candles_by_tf.get("1h", pd.DataFrame())
        df_5m = raw_candles_by_tf.get("5m", pd.DataFrame())

        if df_1h.empty or len(df_1h) < 20:
            logger.warning("Insufficient 1H candle data for backtest.")
            empty_summary = MetricsCalculator._empty_summary(self.run_id)
            return empty_summary, [], []

        # 1. Precompute indicators on full historical series
        # Precomputation on past history is mathematically identical to online computation
        # because IndicatorEngine indicators are purely backward-looking (EMAs, ATRs, etc.)
        ind_candles: dict[str, pd.DataFrame] = {}
        for tf, df in raw_candles_by_tf.items():
            if not df.empty:
                ind_candles[tf] = IndicatorEngine.compute_all_indicators(
                    df.copy(), symbol=self.config.symbol, timeframe=tf
                )
            else:
                ind_candles[tf] = pd.DataFrame()

        df_1h_ind = ind_candles.get("1h", df_1h)

        # 2. Setup chronological timeline
        all_1h_close_times = df_1h_ind["close_time"].tolist()
        total_bars = len(all_1h_close_times)
        in_sample_cutoff_idx = int(total_bars * self.config.in_sample_ratio)

        active_setups: list[TradeSetupModel] = []
        completed_trades: list[SimulatedTrade] = []
        signal_records: list[HorizonSignalRecord] = []
        total_setups_generated = 0

        # Burn-in window: ensure sufficient history for 1D/4H indicators
        burn_in = min(30, total_bars // 4)
        last_regime: MarketRegime | None = None

        # 3. Step chronologically bar-by-bar
        for i in range(burn_in, total_bars):
            t_eval = all_1h_close_times[i]
            is_in_sample = i <= in_sample_cutoff_idx

            # Slicing: strictly NO LOOKAHEAD - only candles closed at or before t_eval
            sliced_tf_data: dict[str, pd.DataFrame] = {}
            for tf, df in ind_candles.items():
                if not df.empty and "close_time" in df.columns:
                    sliced_tf_data[tf] = df[df["close_time"] <= t_eval].copy()
                else:
                    sliced_tf_data[tf] = df.copy()

            # Execute Engine A & Engine B via DecisionOrchestrator
            assessment, setups = DecisionOrchestrator.process_timeframe_data(
                raw_candles_by_tf=sliced_tf_data,
                symbol=self.config.symbol,
                as_of_time=t_eval,
                is_live=False,
                require_completed_candles=True,
                prev_regime=last_regime,
            )
            try:
                last_regime = MarketRegime(assessment.market_regime)
            except (ValueError, TypeError):
                last_regime = None

            # A. Track Directional Signal Evaluation (5, 10, 20, 50 bars)
            if assessment.direction != DirectionType.NEUTRAL:
                future_1h = df_1h_ind[df_1h_ind["open_time"] >= t_eval].copy()
                if not future_1h.empty:
                    horizons_outcomes = DirectionalSignalEvaluator.evaluate_signal_horizons(
                        assessment=assessment,
                        future_candles_1h=future_1h,
                    )
                    signal_records.extend(horizons_outcomes)

            # B. Manage active setups and trade promotions
            if setups and isinstance(setups, list):
                # Auto-invalidate opposing active setups on directional flip
                active_setups = SetupLifecycleTracker.auto_invalidate_opposing(
                    active_setups, assessment.direction
                )
                for new_s in setups:
                    total_setups_generated += 1
                    # Enforce max 1 setup per direction
                    active_setups = [s for s in active_setups if s.direction != new_s.direction]
                    active_setups.append(new_s)

            # C. Multi-resolution execution on 5M sub-bars for the current 1H interval
            curr_bar_open = df_1h_ind["open_time"].iloc[i]
            if not df_5m.empty and "open_time" in df_5m.columns:
                sub_bars = df_5m[(df_5m["open_time"] >= curr_bar_open) & (df_5m["close_time"] <= t_eval)]
            else:
                sub_bars = pd.DataFrame()

            # Iterate over sub-bars (or current 1H bar if 5M unavailable)
            bars_to_eval = [row for _, row in sub_bars.iterrows()] if not sub_bars.empty else [df_1h_ind.iloc[i]]

            still_active: list[TradeSetupModel] = []
            for setup in active_setups:
                resolved = False
                for bar in bars_to_eval:
                    setup = SetupLifecycleTracker.evaluate_bar(setup, bar)

                    # Check for completed trades
                    if setup.status in (
                        SetupStatus.TARGET_HIT,
                        SetupStatus.STOPPED_OUT,
                        SetupStatus.EXPIRED,
                        SetupStatus.INVALIDATED,
                    ):
                        if setup.triggered_at is not None:
                            # Trade was active -> record completed trade
                            trade = self._create_simulated_trade(
                                setup=setup,
                                exit_time=setup.closed_at or t_eval,
                                is_in_sample=is_in_sample,
                                market_regime=assessment.market_regime,
                            )
                            completed_trades.append(trade)
                        resolved = True
                        break

                if not resolved:
                    still_active.append(setup)

            active_setups = still_active

        # Close any lingering trades at the end of simulation
        final_close_price = float(df_1h_ind["close"].iloc[-1])
        final_time = all_1h_close_times[-1]
        for setup in active_setups:
            if setup.triggered_at is not None:
                setup.status = SetupStatus.EXPIRED
                setup.closed_at = final_time
                setup.outcome = "EXPIRED_END_OF_DATA"
                trade = self._create_simulated_trade(
                    setup=setup,
                    exit_time=final_time,
                    is_in_sample=False,
                    market_regime="SESSION_INACTIVE",
                    fallback_exit_price=final_close_price,
                )
                completed_trades.append(trade)

        # 4. Calculate comprehensive metrics
        summary = MetricsCalculator.calculate_metrics(
            trades=completed_trades,
            run_id=self.run_id,
            total_potential_setups=total_setups_generated,
            initial_capital=self.config.initial_capital,
        )

        # Add walk-forward rolling degradation
        summary.walk_forward_folds = self._calculate_walk_forward_folds(
            trades=completed_trades, folds=self.config.walk_forward_folds
        )

        return summary, completed_trades, signal_records

    def _create_simulated_trade(
        self,
        setup: TradeSetupModel,
        exit_time: datetime,
        is_in_sample: bool,
        market_regime: str,
        fallback_exit_price: float | None = None,
    ) -> SimulatedTrade:
        """Create a SimulatedTrade record from a completed TradeSetupModel."""
        entry_mid = (setup.entry_zone_min + setup.entry_zone_max) / 2.0
        is_long = setup.direction == TradeDirection.LONG

        # Calculate exit price
        if fallback_exit_price is not None:
            exit_price = fallback_exit_price
        elif "TARGET_3" in str(setup.outcome) and setup.target_3:
            exit_price = setup.target_3
        elif "TARGET_2" in str(setup.outcome) and setup.target_2:
            exit_price = setup.target_2
        elif "TARGET_1" in str(setup.outcome):
            exit_price = setup.target_1
        elif "BREAKEVEN" in str(setup.outcome) and setup.active_stop_loss:
            exit_price = setup.active_stop_loss
        elif setup.status == SetupStatus.STOPPED_OUT:
            exit_price = setup.stop_loss
        else:
            exit_price = entry_mid

        # PnL accounting with 0.14% friction deducted
        friction_rate = self.config.trading_costs.get("total_friction", 0.0014)
        gross_return_pct = ((exit_price - entry_mid) / entry_mid) if is_long else ((entry_mid - exit_price) / entry_mid)
        net_return_pct = gross_return_pct - friction_rate

        position_size_usd = self.config.initial_capital * self.config.risk_per_trade_pct * 10.0
        pnl_usd = round(position_size_usd * net_return_pct, 2)

        realized_rr = setup.realized_rr if setup.realized_rr is not None else round(net_return_pct / 0.01, 2)

        return SimulatedTrade(
            trade_id=uuid.uuid4(),
            setup_id=setup.setup_id,
            symbol=setup.symbol,
            direction=setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
            setup_type=setup.setup_type.value if hasattr(setup.setup_type, "value") else str(setup.setup_type),
            entry_time=setup.triggered_at or setup.created_at,
            entry_price=entry_mid,
            initial_stop_loss=setup.stop_loss,
            target_1=setup.target_1,
            target_2=setup.target_2,
            target_3=setup.target_3,
            exit_time=exit_time,
            exit_price=exit_price,
            exit_reason=setup.outcome or setup.status.value,
            planned_rr=setup.risk_reward_ratio,
            realized_rr=realized_rr,
            pnl_usd=pnl_usd,
            pnl_pct=round(net_return_pct, 4),
            is_in_sample=is_in_sample,
            market_regime=market_regime,
            active_stop_loss=setup.active_stop_loss,
            breakeven_locked=setup.breakeven_locked,
        )

    def _calculate_walk_forward_folds(self, trades: list[SimulatedTrade], folds: int = 3) -> list[dict[str, Any]]:
        """Divide trades into rolling walk-forward train/test windows and measure degradation."""
        if not trades or len(trades) < folds * 2:
            return []

        sorted_trades = sorted(trades, key=lambda t: t.entry_time)
        chunk_size = len(sorted_trades) // (folds + 1)
        results: list[dict[str, Any]] = []

        for fold in range(folds):
            train_start = fold * chunk_size
            train_end = train_start + (chunk_size * 2)
            test_start = train_end
            test_end = test_start + chunk_size

            train_trades = sorted_trades[train_start:train_end]
            test_trades = sorted_trades[test_start:test_end]

            train_metrics = MetricsCalculator._calculate_subset_metrics(train_trades)
            test_metrics = MetricsCalculator._calculate_subset_metrics(test_trades)

            train_wr = train_metrics["win_rate"]
            test_wr = test_metrics["win_rate"]
            degradation = round(train_wr - test_wr, 2)

            results.append(
                {
                    "fold": fold + 1,
                    "train_trades_count": len(train_trades),
                    "test_trades_count": len(test_trades),
                    "train_win_rate": train_wr,
                    "test_win_rate": test_wr,
                    "train_profit_factor": train_metrics["profit_factor"],
                    "test_profit_factor": test_metrics["profit_factor"],
                    "win_rate_degradation": degradation,
                }
            )

        return results
