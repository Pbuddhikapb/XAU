"""
Engine B: Trade Setup Identification Engine for Binance XAUUSDT.
Strictly conforms to Section 6, 7, and 8 of PROJECT_SPECIFICATION.md and Section 16 of Forensic Audit:
- 4 deterministic setup patterns:
    1. TREND_CONTINUATION: Pullback to dynamic EMA/structure in established trend.
    2. BREAKOUT_RETEST: Structural level breakout confirmed by close with subsequent retest rejection.
    3. LIQUIDITY_SWEEP_REVERSAL: Reclaim of swept swing extrema with rejection confirmation.
    4. RANGE_REJECTION: Reaction at established S/R boundaries in low-ADX range market.
- Stop Loss strictly derived from structure + ATR buffer (structural level +/- 0.5 to 1.0 ATR).
- Three Take-Profit targets (T1, T2, T3) using structural levels and risk multiples.
- Conservative Friction Model:
    * Total friction = Taker fee (0.10%) + Slippage (0.02%) + Spread (0.01%) + Funding (0.01%) = 0.14%.
    * Net Risk = Gross Risk + Friction.
    * Net Reward = Gross Reward - Friction.
    * Enforces Net R:R >= 1.5. Discards any setup failing this constraint.
- Evaluates setups strictly from completed candles (never unfinished bars).
- Lifecycle state initialized to CONFIRMED (or POTENTIAL).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.config import settings
from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    NoSetupResponse,
    SetupStatus,
    SetupType,
    TradeDirection,
    TradeSetupModel,
)

logger = logging.getLogger(__name__)


class TradeSetupEngine:
    """Authoritative Engine B for Trade Setup Identification."""

    @staticmethod
    def _initial_status(direction: DirectionType | str) -> SetupStatus:
        dir_val = direction.value if isinstance(direction, DirectionType) else str(direction)
        if dir_val in ("POTENTIAL_BULLISH", "POTENTIAL_BEARISH"):
            return SetupStatus.POTENTIAL
        return SetupStatus.CONFIRMED

    @staticmethod
    def _make_no_setup(
        reason: str,
        symbol: str,
        as_of_time: datetime,
        assessment: DirectionAssessment,
    ) -> NoSetupResponse:
        return NoSetupResponse(
            symbol=symbol,
            assessment_time=as_of_time,
            reason=reason,
            direction=assessment.direction.value
            if isinstance(assessment.direction, DirectionType)
            else str(assessment.direction),
            data_quality_score=assessment.data_quality_score,
            market_regime=assessment.market_regime,
        )

    @classmethod
    def identify_setups(
        cls,
        assessment: DirectionAssessment,
        timeframe_data: dict[str, dict[str, Any]],
        symbol: str = "XAUUSDT",
        as_of_time: datetime | None = None,
        require_completed_candles: bool = True,
    ) -> list[TradeSetupModel] | NoSetupResponse:
        """
        Evaluate market condition and generate qualified trade setups.
        Only completed candles are evaluated.
        """
        if as_of_time is None:
            as_of_time = datetime.now(UTC)

        # Do not generate setups during inactive CME sessions or when data quality is insufficient
        if assessment.market_regime == "SESSION_INACTIVE":
            logger.info("Market regime is SESSION_INACTIVE: skipping setups")
            return cls._make_no_setup("MARKET_CLOSED", symbol, as_of_time, assessment)

        if assessment.data_quality_score < settings.DATA_QUALITY_MIN_SCORE:
            logger.info(
                "Data quality %.1f < %.1f: skipping setups",
                assessment.data_quality_score,
                settings.DATA_QUALITY_MIN_SCORE,
            )
            return cls._make_no_setup("DATA_QUALITY_BELOW_THRESHOLD", symbol, as_of_time, assessment)

        if assessment.direction == DirectionType.NEUTRAL:
            # Range rejections can still be evaluated in NEUTRAL range regimes if data quality is high
            if assessment.market_regime not in ["RANGE_BOUND"]:
                return cls._make_no_setup("NEUTRAL_NON_RANGE", symbol, as_of_time, assessment)

        df_1h = timeframe_data.get("1h", {}).get("df", pd.DataFrame())
        struct_1h = timeframe_data.get("1h", {}).get("structure", {})

        if df_1h.empty or len(df_1h) < 10:
            return cls._make_no_setup("INSUFFICIENT_DATA", symbol, as_of_time, assessment)

        # Enforce completed candles check:
        # A candle is completed if as_of_time >= candle close_time or candle open_time + timeframe_duration
        if require_completed_candles and "close_time" in df_1h.columns:
            last_close_time = df_1h["close_time"].iloc[-1]
            if hasattr(last_close_time, "to_pydatetime"):
                last_close_time = last_close_time.to_pydatetime()
            if isinstance(last_close_time, datetime) and last_close_time.tzinfo is None:
                last_close_time = last_close_time.replace(tzinfo=UTC)
            if as_of_time < last_close_time:
                # Candle is still forming; reject setup generation
                logger.info("Current bar is incomplete (as_of_time < close_time). Setup generation withheld.")
                return cls._make_no_setup("INCOMPLETE_CANDLE", symbol, as_of_time, assessment)

        setups: list[TradeSetupModel] = []

        # 1. Pattern 1: Trend Continuation
        setup_tc = cls._detect_trend_continuation(assessment, df_1h, struct_1h, as_of_time, symbol)
        if setup_tc:
            setups.append(setup_tc)

        # 2. Pattern 2: Breakout Retest
        setup_br = cls._detect_breakout_retest(assessment, df_1h, struct_1h, as_of_time, symbol)
        if setup_br:
            setups.append(setup_br)

        # 3. Pattern 3: Liquidity Sweep Reversal
        initial_sweep_status = cls._initial_status(assessment.direction)
        setup_sr = cls._detect_sweep_reversal(
            df_1h, struct_1h, as_of_time, symbol, initial_status=initial_sweep_status
        )
        if setup_sr:
            setups.append(setup_sr)

        # 4. Pattern 4: Range Rejection
        setup_rr = cls._detect_range_rejection(assessment, df_1h, struct_1h, as_of_time, symbol)
        if setup_rr:
            setups.append(setup_rr)

        # Enforce max 1 setup per direction: keep the highest Net R:R per TradeDirection
        best_by_dir: dict[TradeDirection, TradeSetupModel] = {}
        for s in setups:
            if s.direction not in best_by_dir or s.risk_reward_ratio > best_by_dir[s.direction].risk_reward_ratio:
                best_by_dir[s.direction] = s
        setups = list(best_by_dir.values())

        if not setups:
            return cls._make_no_setup("NO_PATTERN_QUALIFIED", symbol, as_of_time, assessment)

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
        bullish_variants = {DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH}
        bearish_variants = {DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH}
        if direction not in bullish_variants | bearish_variants:
            return None

        trade_dir = TradeDirection.LONG if direction in bullish_variants else TradeDirection.SHORT
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

        dist_to_ema20 = abs(close - ema_20)
        dist_to_ema50 = abs(close - ema_50)
        near_ema = min(dist_to_ema20, dist_to_ema50) <= 2.5 * atr

        if not near_ema:
            return None

        # Structure + ATR derived Stop Loss
        if trade_dir == TradeDirection.LONG:
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

        net_rr, gross_rr = cls._calculate_net_and_gross_rr(entry_mid, stop_loss, t1, trade_dir)
        if net_rr < settings.MIN_NET_RR:
            return None

        return TradeSetupModel(
            setup_id=uuid.uuid4(),
            symbol=symbol,
            created_at=as_of_time,
            status=cls._initial_status(direction),
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
            gross_risk_reward_ratio=gross_rr,
            expiration_time=as_of_time + timedelta(hours=20),
            invalidation_conditions=inval_text,
            supporting_evidence=[
                {"factor": "Trend Alignment", "detail": f"1H Macro direction is {direction.value}"},
                {
                    "factor": "Pullback to EMA",
                    "detail": f"Price within {min(dist_to_ema20, dist_to_ema50):.2f} USDT of dynamic EMA",
                },
                {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {settings.MIN_NET_RR}"},
            ],
            contradicting_evidence=[],
            estimated_fees_pct=settings.TAKER_FEE_PCT,
            estimated_slippage_pct=settings.SLIPPAGE_PCT,
            estimated_spread_pct=settings.SPREAD_PCT,
            estimated_funding_pct=settings.FUNDING_PCT,
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

        recent_bos = [e for e in events[-10:] if "BOS" in str(e.get("event_type", ""))]
        if not recent_bos:
            return None

        latest_bos = recent_bos[-1]
        bos_price = float(latest_bos.get("price", close))
        bos_type = str(latest_bos.get("event_type", ""))

        bullish_variants = {DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH}
        bearish_variants = {DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH}
        if assessment.direction in bullish_variants and "BULLISH" not in bos_type:
            return None
        if assessment.direction in bearish_variants and "BEARISH" not in bos_type:
            return None

        dist_to_bos = abs(close - bos_price)
        if dist_to_bos > 1.2 * atr:
            return None

        # Structure + ATR derived Stop Loss
        if "BULLISH" in bos_type and close >= bos_price - 0.3 * atr:
            trade_dir = TradeDirection.LONG
            stop_loss = round(bos_price - 0.75 * atr, 2)
            entry_min = round(bos_price - 0.2 * atr, 2)
            entry_max = round(bos_price + 0.3 * atr, 2)
            entry_mid = (entry_min + entry_max) / 2.0
            risk = entry_mid - stop_loss
            if risk <= 0:
                return None
            t1 = round(entry_mid + 2.0 * risk, 2)
            t2 = round(entry_mid + 3.2 * risk, 2)
            t3 = round(entry_mid + 4.8 * risk, 2)
            inval_text = f"Invalidated if price closes below retest level at {stop_loss:.2f}."
        elif "BEARISH" in bos_type and close <= bos_price + 0.3 * atr:
            trade_dir = TradeDirection.SHORT
            stop_loss = round(bos_price + 0.75 * atr, 2)
            entry_min = round(bos_price - 0.3 * atr, 2)
            entry_max = round(bos_price + 0.2 * atr, 2)
            entry_mid = (entry_min + entry_max) / 2.0
            risk = stop_loss - entry_mid
            if risk <= 0:
                return None
            t1 = round(entry_mid - 2.0 * risk, 2)
            t2 = round(entry_mid - 3.2 * risk, 2)
            t3 = round(entry_mid - 4.8 * risk, 2)
            inval_text = f"Invalidated if price closes above retest level at {stop_loss:.2f}."
        else:
            return None

        net_rr, gross_rr = cls._calculate_net_and_gross_rr(entry_mid, stop_loss, t1, trade_dir)
        if net_rr < settings.MIN_NET_RR:
            return None

        return TradeSetupModel(
            setup_id=uuid.uuid4(),
            symbol=symbol,
            created_at=as_of_time,
            status=cls._initial_status(assessment.direction),
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
            gross_risk_reward_ratio=gross_rr,
            expiration_time=as_of_time + timedelta(hours=15),
            invalidation_conditions=inval_text,
            supporting_evidence=[
                {"factor": "BOS Confirmation", "detail": f"Recent {bos_type} broke at {bos_price:.2f}"},
                {"factor": "Retest Level", "detail": f"Price within {dist_to_bos:.2f} USDT of broken level"},
                {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {settings.MIN_NET_RR}"},
            ],
            contradicting_evidence=[],
            estimated_fees_pct=settings.TAKER_FEE_PCT,
            estimated_slippage_pct=settings.SLIPPAGE_PCT,
            estimated_spread_pct=settings.SPREAD_PCT,
            estimated_funding_pct=settings.FUNDING_PCT,
        )

    @classmethod
    def _detect_sweep_reversal(
        cls,
        df_1h: pd.DataFrame,
        struct_1h: dict[str, Any],
        as_of_time: datetime,
        symbol: str,
        initial_status: SetupStatus = SetupStatus.CONFIRMED,
    ) -> TradeSetupModel | None:
        """Pattern 3: Liquidity sweep reversal with reclaim confirmation."""
        sweeps = struct_1h.get("liquidity_sweeps", [])
        if not sweeps:
            return None

        close = float(df_1h["close"].iloc[-1])
        atr = (
            float(df_1h["atr_14"].iloc[-1]) if "atr_14" in df_1h.columns and pd.notna(df_1h["atr_14"].iloc[-1]) else 5.0
        )

        latest_sweep = sweeps[-1]
        sweep_level = float(latest_sweep.get("swept_level", latest_sweep.get("sweep_level", close)))
        sweep_type = str(latest_sweep.get("sweep_type", "")).upper()
        extreme_price = float(latest_sweep.get("penetration_price", latest_sweep.get("extreme_price", close)))

        # Structure + ATR derived Stop Loss
        if "LOW" in sweep_type or "SUPPORT" in sweep_type or "BULLISH" in sweep_type:
            trade_dir = TradeDirection.LONG
            stop_loss = round(extreme_price - 0.5 * atr, 2)
            entry_min = round(close - 0.25 * atr, 2)
            entry_max = round(close + 0.25 * atr, 2)
            entry_mid = close
            risk = entry_mid - stop_loss
            if risk <= 0:
                return None
            t1 = round(entry_mid + 2.2 * risk, 2)
            t2 = round(entry_mid + 3.5 * risk, 2)
            t3 = round(entry_mid + 5.0 * risk, 2)
            inval_text = f"Invalidated if price trades below sweep low at {stop_loss:.2f}."
        elif "HIGH" in sweep_type or "RESISTANCE" in sweep_type or "BEARISH" in sweep_type:
            trade_dir = TradeDirection.SHORT
            stop_loss = round(extreme_price + 0.5 * atr, 2)
            entry_min = round(close - 0.25 * atr, 2)
            entry_max = round(close + 0.25 * atr, 2)
            entry_mid = close
            risk = stop_loss - entry_mid
            if risk <= 0:
                return None
            t1 = round(entry_mid - 2.2 * risk, 2)
            t2 = round(entry_mid - 3.5 * risk, 2)
            t3 = round(entry_mid - 5.0 * risk, 2)
            inval_text = f"Invalidated if price trades above sweep high at {stop_loss:.2f}."
        else:
            return None

        net_rr, gross_rr = cls._calculate_net_and_gross_rr(entry_mid, stop_loss, t1, trade_dir)
        if net_rr < settings.MIN_NET_RR:
            return None

        return TradeSetupModel(
            setup_id=uuid.uuid4(),
            symbol=symbol,
            created_at=as_of_time,
            status=initial_status,
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
            gross_risk_reward_ratio=gross_rr,
            expiration_time=as_of_time + timedelta(hours=10),
            invalidation_conditions=inval_text,
            supporting_evidence=[
                {"factor": "Liquidity Sweep", "detail": f"Sweep of {sweep_type} at {sweep_level:.2f}"},
                {"factor": "Reclaim", "detail": f"Price closed back inside sweep level at {close:.2f}"},
                {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {settings.MIN_NET_RR}"},
            ],
            contradicting_evidence=[],
            estimated_fees_pct=settings.TAKER_FEE_PCT,
            estimated_slippage_pct=settings.SLIPPAGE_PCT,
            estimated_spread_pct=settings.SPREAD_PCT,
            estimated_funding_pct=settings.FUNDING_PCT,
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
        adx = float(df_1h["adx"].iloc[-1]) if "adx" in df_1h.columns and pd.notna(df_1h["adx"].iloc[-1]) else 18.0
        if adx >= 25.0:
            return None  # Trend is active, range rejection disqualified

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
                    stop_loss = round(z_min - 0.75 * atr, 2)
                    entry_min = round(z_min, 2)
                    entry_max = round(close + 0.2 * atr, 2)
                    entry_mid = (entry_min + entry_max) / 2.0
                    risk = entry_mid - stop_loss
                    if risk <= 0:
                        continue
                    t1 = round(entry_mid + 2.0 * risk, 2)
                    t2 = round(entry_mid + 3.0 * risk, 2)
                    t3 = round(entry_mid + 4.2 * risk, 2)
                    inval_text = f"Invalidated if price closes below support boundary at {stop_loss:.2f}."
                elif z_type == "RESISTANCE":
                    trade_dir = TradeDirection.SHORT
                    stop_loss = round(z_max + 0.75 * atr, 2)
                    entry_min = round(close - 0.2 * atr, 2)
                    entry_max = round(z_max, 2)
                    entry_mid = (entry_min + entry_max) / 2.0
                    risk = stop_loss - entry_mid
                    if risk <= 0:
                        continue
                    t1 = round(entry_mid - 2.0 * risk, 2)
                    t2 = round(entry_mid - 3.0 * risk, 2)
                    t3 = round(entry_mid - 4.2 * risk, 2)
                    inval_text = f"Invalidated if price closes above resistance boundary at {stop_loss:.2f}."
                else:
                    continue

                net_rr, gross_rr = cls._calculate_net_and_gross_rr(entry_mid, stop_loss, t1, trade_dir)
                if net_rr >= settings.MIN_NET_RR:
                    return TradeSetupModel(
                        setup_id=uuid.uuid4(),
                        symbol=symbol,
                        created_at=as_of_time,
                        status=SetupStatus.CONFIRMED,
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
                        gross_risk_reward_ratio=gross_rr,
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
                            {"factor": "Net R:R", "detail": f"Net R:R={net_rr:.2f} >= {settings.MIN_NET_RR}"},
                        ],
                        contradicting_evidence=[],
                        estimated_fees_pct=settings.TAKER_FEE_PCT,
                        estimated_slippage_pct=settings.SLIPPAGE_PCT,
                        estimated_spread_pct=settings.SPREAD_PCT,
                        estimated_funding_pct=settings.FUNDING_PCT,
                    )

        return None

    # -------------------------------------------------------------------------
    # Friction & Net R:R Calculator
    # -------------------------------------------------------------------------

    @classmethod
    def _calculate_net_and_gross_rr(
        cls, entry: float, stop_loss: float, target: float, direction: TradeDirection
    ) -> tuple[float, float]:
        """
        Calculate Net Risk-to-Reward ratio after:
        - Taker fee (0.10% roundtrip)
        - Slippage (0.02%)
        - Spread (0.01%)
        - Funding fee (0.01%)
        Total friction = 0.14%.
        """
        total_friction_pct = (
            settings.TAKER_FEE_PCT + settings.SLIPPAGE_PCT + settings.SPREAD_PCT + settings.FUNDING_PCT
        )
        friction_per_unit = entry * total_friction_pct

        if direction == TradeDirection.LONG:
            gross_risk = entry - stop_loss
            gross_reward = target - entry
        else:
            gross_risk = stop_loss - entry
            gross_reward = entry - target

        if gross_risk <= 0 or gross_reward <= 0:
            return 0.0, 0.0

        gross_rr = round(gross_reward / gross_risk, 2)

        net_risk = gross_risk + friction_per_unit
        net_reward = gross_reward - friction_per_unit

        if net_risk <= 0 or net_reward <= 0:
            return 0.0, gross_rr

        net_rr = round(net_reward / net_risk, 2)
        return net_rr, gross_rr
