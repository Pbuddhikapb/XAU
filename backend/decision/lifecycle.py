"""
Setup Lifecycle State Machine for Binance XAUUSDT.
Strictly conforms to Section 7 and 8 of PROJECT_SPECIFICATION.md and Section 16 of Forensic Audit:
- Strict lifecycle state progression:
    POTENTIAL -> CONFIRMED -> TRIGGERED -> TARGET_HIT / STOPPED_OUT / INVALIDATED / EXPIRED.
- Conservative collision rule: Stop Loss WINS if both Stop Loss and Target are hit in the same candle.
- Invalidation before entry: Stop Loss hit before entry zone fill transitions setup to INVALIDATED.
- Expiration handling: Unfilled setups expire cleanly at expiration_time.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from backend.decision.models import SetupStatus, TradeDirection, TradeSetupModel

logger = logging.getLogger(__name__)


class SetupLifecycleTracker:
    """Manages state transitions and outcome evaluations for TradeSetups."""

    @classmethod
    def evaluate_bar(
        cls, setup: TradeSetupModel, bar: pd.Series | dict[str, Any], current_time: datetime | None = None
    ) -> TradeSetupModel:
        """
        Evaluate a single closed candle against the current setup state.
        bar must have: high, low, open, close, and optionally open_time / close_time.
        """
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        bar_time = bar.get("open_time")
        if bar_time is not None:
            if isinstance(bar_time, str):
                bar_time = pd.to_datetime(bar_time, utc=True).to_pydatetime()
            elif isinstance(bar_time, pd.Timestamp):
                bar_time = bar_time.to_pydatetime()
        elif current_time is not None:
            bar_time = current_time
        else:
            bar_time = datetime.now(UTC)

        # 1. State: POTENTIAL (Pending secondary confirmation)
        if setup.status == SetupStatus.POTENTIAL:
            # Check expiration
            if bar_time >= setup.expiration_time:
                setup.status = SetupStatus.EXPIRED
                setup.closed_at = bar_time
                setup.outcome = "EXPIRED_UNCONFIRMED"
                return setup

            # Check invalidation before confirmation
            if setup.direction == TradeDirection.LONG and low <= setup.stop_loss:
                setup.status = SetupStatus.INVALIDATED
                setup.closed_at = bar_time
                setup.outcome = "INVALIDATED_BEFORE_CONFIRMATION"
                return setup
            elif setup.direction == TradeDirection.SHORT and high >= setup.stop_loss:
                setup.status = SetupStatus.INVALIDATED
                setup.closed_at = bar_time
                setup.outcome = "INVALIDATED_BEFORE_CONFIRMATION"
                return setup

            # If candle holds without hitting stop, promote to CONFIRMED
            setup.status = SetupStatus.CONFIRMED

        # 2. State: CONFIRMED (Awaiting entry fill)
        if setup.status == SetupStatus.CONFIRMED:
            # Check expiration
            if bar_time >= setup.expiration_time:
                setup.status = SetupStatus.EXPIRED
                setup.closed_at = bar_time
                setup.outcome = "EXPIRED_WITHOUT_FILL"
                return setup

            # Check if Stop Loss hit before entry was touched -> INVALIDATED
            if setup.direction == TradeDirection.LONG and low <= setup.stop_loss:
                setup.status = SetupStatus.INVALIDATED
                setup.closed_at = bar_time
                setup.outcome = "INVALIDATED_SL_HIT_BEFORE_ENTRY"
                return setup
            elif setup.direction == TradeDirection.SHORT and high >= setup.stop_loss:
                setup.status = SetupStatus.INVALIDATED
                setup.closed_at = bar_time
                setup.outcome = "INVALIDATED_SL_HIT_BEFORE_ENTRY"
                return setup

            # Check for Entry Fill: Candle overlaps [entry_zone_min, entry_zone_max]
            entry_hit = not (high < setup.entry_zone_min or low > setup.entry_zone_max)
            if entry_hit:
                setup.status = SetupStatus.TRIGGERED
                setup.triggered_at = bar_time
                return setup

        # 3. State: TRIGGERED (Active trade position)
        elif setup.status == SetupStatus.TRIGGERED:
            is_long = setup.direction == TradeDirection.LONG

            # Check Stop Loss & Target hits on current candle
            sl_hit = (low <= setup.stop_loss) if is_long else (high >= setup.stop_loss)
            tp_hit = (high >= setup.target_1) if is_long else (low <= setup.target_1)

            # MANDATORY RULE: "stop wins if stop and target hit in the same candle"
            if sl_hit and tp_hit:
                setup.status = SetupStatus.STOPPED_OUT
                setup.closed_at = bar_time
                setup.outcome = "STOPPED_OUT_SAME_CANDLE_COLLISION"
                setup.realized_rr = -1.0
                return setup

            if sl_hit:
                setup.status = SetupStatus.STOPPED_OUT
                setup.closed_at = bar_time
                setup.outcome = "STOPPED_OUT"
                setup.realized_rr = -1.0
                return setup

            if tp_hit:
                setup.status = SetupStatus.TARGET_HIT
                setup.closed_at = bar_time
                # Check higher targets
                if setup.target_3 and ((is_long and high >= setup.target_3) or (not is_long and low <= setup.target_3)):
                    setup.outcome = "TARGET_3_HIT"
                    setup.realized_rr = round(setup.risk_reward_ratio * 2.5, 2)
                elif setup.target_2 and (
                    (is_long and high >= setup.target_2) or (not is_long and low <= setup.target_2)
                ):
                    setup.outcome = "TARGET_2_HIT"
                    setup.realized_rr = round(setup.risk_reward_ratio * 1.6, 2)
                else:
                    setup.outcome = "TARGET_1_HIT"
                    setup.realized_rr = setup.risk_reward_ratio
                return setup

            # Check trade expiration while active
            if bar_time >= setup.expiration_time:
                setup.status = SetupStatus.EXPIRED
                setup.closed_at = bar_time
                setup.outcome = "EXPIRED_IN_TRADE"
                entry_mid = (setup.entry_zone_min + setup.entry_zone_max) / 2.0
                risk = abs(entry_mid - setup.stop_loss)
                pnl = (close - entry_mid) if is_long else (entry_mid - close)
                setup.realized_rr = round(pnl / risk, 2) if risk > 0 else 0.0
                return setup

        return setup
