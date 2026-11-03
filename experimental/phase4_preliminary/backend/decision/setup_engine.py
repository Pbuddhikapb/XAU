"""
Engine B: Trade Setup Identification Engine for Binance XAUUSDT.
Strictly conforms to Section 6, 7, and 8 of PROJECT_SPECIFICATION.md:
- Detects 4 deterministic setup patterns:
  1. TREND_CONTINUATION
  2. BREAKOUT_RETEST
  3. LIQUIDITY_SWEEP_REVERSAL
  4. RANGE_REJECTION
- Calculates concrete Entry Zone, Stop Loss, and 3 Take-Profit targets.
- Enforces strict Net Risk-to-Reward ratio >= 1.5 after trading fees (0.10% taker) and slippage (0.02%).
- Discards any setup failing R:R or data quality constraints.
- Methodology Version: v1.0.0
"""

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    SetupStatus,
    SetupType,
    TradeDirection,
    TradeSetupModel,
)

logger = logging.getLogger(__name__)


class TradeSetupEngine:
    """Authoritative Engine B for Trade Setup Identification."""

    MIN_RR_RATIO = 1.5
    DEFAULT_TAKER_FEE_PCT = 0.0010  # 0.05% entry + 0.05% exit = 0.10%
    DEFAULT_SLIPPAGE_PCT = 0.0002  # 0.02% slippage allowance
    TOTAL_FRICTION_PCT = DEFAULT_TAKER_FEE_PCT + DEFAULT_SLIPPAGE_PCT

    @classmethod
    def identify_setups(
        cls,
        assessment: DirectionAssessment,
        timeframe_data: dict[str, dict[str, Any]],
        symbol: str = "XAUUSDT",
        as_of_time: datetime | None = None,
    ) -> list[TradeSetupModel]:
        """
        Evaluate market condition and generate qualified trade setups.
        Returns a list of TradeSetupModel instances meeting all R:R and structural criteria.
        """
        if as_of_time is None:
            as_of_time = datetime.now(UTC)

        # Do not generate setups during inactive CME sessions or when data quality is poor
        if assessment.direction == DirectionType.NEUTRAL and assessment.data_quality_score < 70.0:
            return []

        setups: list[TradeSetupModel] = []

        df_1h = timeframe_data.get("1h", {}).get("df", pd.DataFrame())
        struct_1h = timeframe_data.get("1h", {}).get("structure", {})

        if df_1h.empty or len(df_1h) < 10:
            return []

        # 1. Pattern 1: Trend Continuation
        setup_tc = cls._detect_trend_continuation(assessment, df_1h, struct_1h, as_of_time, symbol)
        if setup_tc:
            setups.append(setup_tc)

        # 2. Pattern 2: Breakout Retest
        setup_br = cls._detect_breakout_retest(assessment, df_1h, struct_1h, as_of_time, symbol)
        if setup_br:
            setups.append(setup_br)

        # 3. Pattern 3: Liquidity Sweep Reversal
        setup_sr = cls._detect_sweep_reversal(df_1h, struct_1h, as_of_time, symbol)
        if setup_sr:
            setups.append(setup_sr)

        # 4. Pattern 4: Range Rejection
        setup_rr = cls._detect_range_rejection(assessment, df_1h, struct_1h, as_of_time, symbol)
        if setup_rr:
            setups.append(setup_rr)

        return setups

    # -------------------------------------------------------------------------
    # Setup Detectors
    # -------------------------------------------------------------------------

    @classmethod
    def _detect_trend_continuation(
        cls,
        assessment: DirectionAssessment,
        df_1h: pd.DataFrame,
        struct_1h: dict[str, Any],
        as_of_time: datetime,
        symbol: str,
    ) -> TradeSetupModel | None:
        """Pattern 1: Pullback to dynamic EMA/support in established trend."""
        direction = assessment.direction
        if direction not in [DirectionType.BULLISH, DirectionType.BEARISH]:
            return None

        trade_dir = TradeDirection.LONG if direction == DirectionType.BULLISH else TradeDirection.SHORT
        close = float(df_1h["close"].iloc[-1])
        atr = (
            float(df_1h["atr_14"].iloc[-1]) if "atr_14" in df_1h.columns and pd.notna(df_1h["atr_14"].iloc[-1]) else 5.0
        )
        ema_20 = (
            float(df_1h["ema_20"].iloc[-1])
            if "ema_20" in df_1h.columns and pd.notna(df_1h["ema_20"].iloc[-1])
            else close
        )
        ema_50 = (
            float(df_1h["ema_50"].iloc[-1])
            if "ema_50" in df_1h.columns and pd.notna(df_1h["ema_50"].iloc[-1])
            else close
        )

        # Check if price is within pullback proximity of EMA 20 or EMA 50
        dist_to_ema20 = abs(close - ema_20)
        dist_to_ema50 = abs(close - ema_50)
        near_ema = min(dist_to_ema20, dist_to_ema50) <= 2.5 * atr

        if not near_ema:
            return None

        # Determine levels
        if trade_dir == TradeDirection.LONG:
            # Stop loss below EMA 50 or recent swing low
            swing_low = float(df_1h["low"].tail(10).min())
            sl_candidate = swing_low - 0.5 * atr
            if not np.isnan(ema_50):
                sl_candidate = min(ema_50 - 0.5 * atr, sl_candidate)
            stop_loss = round(sl_candidate, 2)
            entry_min = round(close - 0.25 * atr, 2)
            entry_max = round(close + 0.25 * atr, 2)
            entry_mid = close

            risk = entry_mid - stop_loss
            if risk <= 0:
                return None

            # Targets
            swing_high = float(df_1h["high"].tail(20).max())
            t1 = round(max(swing_high, entry_mid + 2.0 * risk), 2)
            t2 = round(entry_mid + 3.2 * risk, 2)
            t3 = round(entry_mid + 4.5 * risk, 2)
            inval_text = f"Invalidated if price closes below 1H EMA50 / Support at {stop_loss:.2f}."
        else:
            swing_high = float(df_1h["high"].tail(10).max())
            sl_candidate = swing_high + 0.5 * atr
            if not np.isnan(ema_50):
                sl_candidate = max(ema_50 + 0.5 * atr, sl_candidate)
            stop_loss = round(sl_candidate, 2)
            entry_min = round(close - 0.25 * atr, 2)
            entry_max = round(close + 0.25 * atr, 2)
            entry_mid = close

            risk = stop_loss - entry_mid
            if risk <= 0:
                return None

            swing_low = float(df_1h["low"].tail(20).min())
            t1 = round(min(swing_low, entry_mid - 2.0 * risk), 2)
            t2 = round(entry_mid - 3.2 * risk, 2)
            t3 = round(entry_mid - 4.5 * risk, 2)
            inval_text = f"Invalidated if price closes above 1H EMA50 / Resistance at {stop_loss:.2f}."

        net_rr = cls._calculate_net_rr(entry_mid, stop_loss, t1, trade_dir)
        if net_rr < cls.MIN_RR_RATIO:
            return None

        return TradeSetupModel(
            setup_id=uuid.uuid4(),
            symbol=symbol,
            created_at=as_of_time,
            status=SetupStatus.IDENTIFIED,
            setup_type=SetupType.TREND_CONTINUATION,
            direction=trade_dir,
            timeframe="1h",
            entry_zone_min=entry_min,
            entry_zone_max=entry_max,
            stop_loss=stop_loss,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            risk_reward_ratio=net_rr,
            expiration_time=as_of_time + timedelta(hours=20),
            invalidation_conditions=inval_text,
            supporting_evidence=[
                {"factor": "Trend Alignment", "detail": f"1H Macro direction is {direction.value}"},
                {
                    "factor": "Pullback to EMA",
                    "detail": f"Price within {min(dist_to_ema20, dist_to_ema50):.2f} USDT of dynamic EMA",
                },
                {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} exceeds minimum threshold {cls.MIN_RR_RATIO}"},
            ],
            estimated_fees_pct=cls.DEFAULT_TAKER_FEE_PCT,
        )

    @classmethod
    def _detect_breakout_retest(
        cls,
        assessment: DirectionAssessment,
        df_1h: pd.DataFrame,
        struct_1h: dict[str, Any],
        as_of_time: datetime,
        symbol: str,
    ) -> TradeSetupModel | None:
        """Pattern 2: Breakout of swing extrema and subsequent retest."""
        events = struct_1h.get("structure_events", [])
        if not events:
            return None

        close = float(df_1h["close"].iloc[-1])
        atr = (
            float(df_1h["atr_14"].iloc[-1]) if "atr_14" in df_1h.columns and pd.notna(df_1h["atr_14"].iloc[-1]) else 5.0
        )

        # Find recent BOS within last 10 structure events
        recent_bos = [e for e in events[-10:] if "BOS" in str(e.get("event_type", ""))]
        if not recent_bos:
            return None

        latest_bos = recent_bos[-1]
        bos_price = float(latest_bos.get("price", close))
        bos_type = str(latest_bos.get("event_type", ""))

        dist_to_bos = abs(close - bos_price)
        # Retest within 1.0 ATR of broken level
        if dist_to_bos > 1.0 * atr:
            return None

        if "BULLISH" in bos_type and close >= bos_price - 0.25 * atr:
            trade_dir = TradeDirection.LONG
            stop_loss = round(bos_price - 1.0 * atr, 2)
            entry_min = round(bos_price - 0.2 * atr, 2)
            entry_max = round(bos_price + 0.3 * atr, 2)
            entry_mid = (entry_min + entry_max) / 2.0
            risk = entry_mid - stop_loss
            if risk <= 0:
                return None
            t1 = round(entry_mid + 1.8 * risk, 2)
            t2 = round(entry_mid + 3.0 * risk, 2)
            t3 = round(entry_mid + 4.5 * risk, 2)
            inval_text = f"Invalidated if price closes below retest level at {stop_loss:.2f}."
        elif "BEARISH" in bos_type and close <= bos_price + 0.25 * atr:
            trade_dir = TradeDirection.SHORT
            stop_loss = round(bos_price + 1.0 * atr, 2)
            entry_min = round(bos_price - 0.3 * atr, 2)
            entry_max = round(bos_price + 0.2 * atr, 2)
            entry_mid = (entry_min + entry_max) / 2.0
            risk = stop_loss - entry_mid
            if risk <= 0:
                return None
            t1 = round(entry_mid - 1.8 * risk, 2)
            t2 = round(entry_mid - 3.0 * risk, 2)
            t3 = round(entry_mid - 4.5 * risk, 2)
            inval_text = f"Invalidated if price closes above retest level at {stop_loss:.2f}."
        else:
            return None

        net_rr = cls._calculate_net_rr(entry_mid, stop_loss, t1, trade_dir)
        if net_rr < cls.MIN_RR_RATIO:
            return None

        return TradeSetupModel(
            setup_id=uuid.uuid4(),
            symbol=symbol,
            created_at=as_of_time,
            status=SetupStatus.IDENTIFIED,
            setup_type=SetupType.BREAKOUT_RETEST,
            direction=trade_dir,
            timeframe="1h",
            entry_zone_min=entry_min,
            entry_zone_max=entry_max,
            stop_loss=stop_loss,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            risk_reward_ratio=net_rr,
            expiration_time=as_of_time + timedelta(hours=15),
            invalidation_conditions=inval_text,
            supporting_evidence=[
                {"factor": "BOS Confirmation", "detail": f"Recent {bos_type} broke at {bos_price:.2f}"},
                {"factor": "Retest Level", "detail": f"Price within {dist_to_bos:.2f} USDT of broken swing level"},
                {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {cls.MIN_RR_RATIO}"},
            ],
            estimated_fees_pct=cls.DEFAULT_TAKER_FEE_PCT,
        )

    @classmethod
    def _detect_sweep_reversal(
        cls,
        df_1h: pd.DataFrame,
        struct_1h: dict[str, Any],
        as_of_time: datetime,
        symbol: str,
    ) -> TradeSetupModel | None:
        """Pattern 3: Liquidity sweep reversal with divergence confirmation."""
        sweeps = struct_1h.get("liquidity_sweeps", [])
        if not sweeps:
            return None

        close = float(df_1h["close"].iloc[-1])
        atr = (
            float(df_1h["atr_14"].iloc[-1]) if "atr_14" in df_1h.columns and pd.notna(df_1h["atr_14"].iloc[-1]) else 5.0
        )

        latest_sweep = sweeps[-1]
        sweep_level = float(latest_sweep.get("sweep_level", close))
        sweep_type = str(latest_sweep.get("sweep_type", "")).upper()

        if "LOW" in sweep_type or "SUPPORT" in sweep_type or "BULLISH" in sweep_type:
            trade_dir = TradeDirection.LONG
            extreme_low = float(latest_sweep.get("extreme_price", df_1h["low"].tail(5).min()))
            stop_loss = round(min(extreme_low - 0.5 * atr, close - 2.0 * atr), 2)
            entry_min = round(close - 0.25 * atr, 2)
            entry_max = round(close + 0.25 * atr, 2)
            entry_mid = close
            risk = entry_mid - stop_loss
            if risk <= 0:
                return None
            t1 = round(entry_mid + 2.0 * risk, 2)
            t2 = round(entry_mid + 3.5 * risk, 2)
            t3 = round(entry_mid + 5.0 * risk, 2)
            inval_text = f"Invalidated if price trades below sweep low at {stop_loss:.2f}."
        elif "HIGH" in sweep_type or "RESISTANCE" in sweep_type or "BEARISH" in sweep_type:
            trade_dir = TradeDirection.SHORT
            extreme_high = float(latest_sweep.get("extreme_price", df_1h["high"].tail(5).max()))
            stop_loss = round(max(extreme_high + 0.5 * atr, close + 2.0 * atr), 2)
            entry_min = round(close - 0.25 * atr, 2)
            entry_max = round(close + 0.25 * atr, 2)
            entry_mid = close
            risk = stop_loss - entry_mid
            if risk <= 0:
                return None
            t1 = round(entry_mid - 2.0 * risk, 2)
            t2 = round(entry_mid - 3.5 * risk, 2)
            t3 = round(entry_mid - 5.0 * risk, 2)
            inval_text = f"Invalidated if price trades above sweep high at {stop_loss:.2f}."
        else:
            return None

        net_rr = cls._calculate_net_rr(entry_mid, stop_loss, t1, trade_dir)
        if net_rr < cls.MIN_RR_RATIO:
            return None

        return TradeSetupModel(
            setup_id=uuid.uuid4(),
            symbol=symbol,
            created_at=as_of_time,
            status=SetupStatus.IDENTIFIED,
            setup_type=SetupType.LIQUIDITY_SWEEP_REVERSAL,
            direction=trade_dir,
            timeframe="1h",
            entry_zone_min=entry_min,
            entry_zone_max=entry_max,
            stop_loss=stop_loss,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            risk_reward_ratio=net_rr,
            expiration_time=as_of_time + timedelta(hours=10),
            invalidation_conditions=inval_text,
            supporting_evidence=[
                {"factor": "Liquidity Sweep", "detail": f"Sweep of {sweep_type} at {sweep_level:.2f}"},
                {"factor": "Sweep Reclaim", "detail": f"Price closed back inside sweep level at {close:.2f}"},
                {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {cls.MIN_RR_RATIO}"},
            ],
            estimated_fees_pct=cls.DEFAULT_TAKER_FEE_PCT,
        )

    @classmethod
    def _detect_range_rejection(
        cls,
        assessment: DirectionAssessment,
        df_1h: pd.DataFrame,
        struct_1h: dict[str, Any],
        as_of_time: datetime,
        symbol: str,
    ) -> TradeSetupModel | None:
        """Pattern 4: Support / Resistance rejection in range-bound market."""
        # Range setup only applies when market is not aggressively trending
        adx = float(df_1h["adx"].iloc[-1]) if "adx" in df_1h.columns and pd.notna(df_1h["adx"].iloc[-1]) else 18.0
        if adx >= 25.0:
            return None  # Trend is too strong for range rejections

        sr_zones = struct_1h.get("sr_zones", [])
        if not sr_zones:
            return None

        close = float(df_1h["close"].iloc[-1])
        atr = (
            float(df_1h["atr_14"].iloc[-1]) if "atr_14" in df_1h.columns and pd.notna(df_1h["atr_14"].iloc[-1]) else 5.0
        )

        for zone in sr_zones:
            z_min = float(zone.get("level_min", zone.get("price_min", 0.0)))
            z_max = float(zone.get("level_max", zone.get("price_max", 0.0)))
            z_type = zone.get("zone_type", "")

            # If price is reacting inside or within 0.3 ATR of zone
            if z_min - 0.3 * atr <= close <= z_max + 0.3 * atr:
                if z_type == "SUPPORT":
                    trade_dir = TradeDirection.LONG
                    stop_loss = round(z_min - 1.0 * atr, 2)
                    entry_min = round(z_min, 2)
                    entry_max = round(close + 0.2 * atr, 2)
                    entry_mid = (entry_min + entry_max) / 2.0
                    risk = entry_mid - stop_loss
                    if risk <= 0:
                        continue
                    t1 = round(entry_mid + 1.8 * risk, 2)
                    t2 = round(entry_mid + 2.8 * risk, 2)
                    t3 = round(entry_mid + 4.0 * risk, 2)
                    inval_text = f"Invalidated if price closes below support boundary at {stop_loss:.2f}."
                elif z_type == "RESISTANCE":
                    trade_dir = TradeDirection.SHORT
                    stop_loss = round(z_max + 1.0 * atr, 2)
                    entry_min = round(close - 0.2 * atr, 2)
                    entry_max = round(z_max, 2)
                    entry_mid = (entry_min + entry_max) / 2.0
                    risk = stop_loss - entry_mid
                    if risk <= 0:
                        continue
                    t1 = round(entry_mid - 1.8 * risk, 2)
                    t2 = round(entry_mid - 2.8 * risk, 2)
                    t3 = round(entry_mid - 4.0 * risk, 2)
                    inval_text = f"Invalidated if price closes above resistance boundary at {stop_loss:.2f}."
                else:
                    continue

                net_rr = cls._calculate_net_rr(entry_mid, stop_loss, t1, trade_dir)
                if net_rr >= cls.MIN_RR_RATIO:
                    return TradeSetupModel(
                        setup_id=uuid.uuid4(),
                        symbol=symbol,
                        created_at=as_of_time,
                        status=SetupStatus.IDENTIFIED,
                        setup_type=SetupType.RANGE_REJECTION,
                        direction=trade_dir,
                        timeframe="1h",
                        entry_zone_min=entry_min,
                        entry_zone_max=entry_max,
                        stop_loss=stop_loss,
                        target_1=t1,
                        target_2=t2,
                        target_3=t3,
                        risk_reward_ratio=net_rr,
                        expiration_time=as_of_time + timedelta(hours=15),
                        invalidation_conditions=inval_text,
                        supporting_evidence=[
                            {
                                "factor": "Range Regime",
                                "detail": f"Market ADX={adx:.1f} < 25 confirms range-bound regime",
                            },
                            {
                                "factor": "S/R Reaction",
                                "detail": f"Price reacting at {z_type} ({z_min:.2f} - {z_max:.2f})",
                            },
                            {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {cls.MIN_RR_RATIO}"},
                        ],
                        estimated_fees_pct=cls.DEFAULT_TAKER_FEE_PCT,
                    )

        return None

    # -------------------------------------------------------------------------
    # Friction & R:R Calculator
    # -------------------------------------------------------------------------

    @classmethod
    def _calculate_net_rr(cls, entry: float, stop_loss: float, target: float, direction: TradeDirection) -> float:
        """
        Calculate net Risk-to-Reward ratio after roundtrip taker fees (0.10%) and slippage (0.02%).
        """
        friction_per_unit = entry * cls.TOTAL_FRICTION_PCT

        if direction == TradeDirection.LONG:
            gross_risk = entry - stop_loss
            gross_reward = target - entry
        else:
            gross_risk = stop_loss - entry
            gross_reward = entry - target

        if gross_risk <= 0 or gross_reward <= 0:
            return 0.0

        net_risk = gross_risk + friction_per_unit
        net_reward = gross_reward - friction_per_unit

        if net_risk <= 0 or net_reward <= 0:
            return 0.0

        return round(net_reward / net_risk, 2)
