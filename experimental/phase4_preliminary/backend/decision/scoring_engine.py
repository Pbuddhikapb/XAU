"""
Engine A: Market Direction Scoring Engine for Binance XAUUSDT.
Strictly conforms to Section 6, 7, and 9 of PROJECT_SPECIFICATION.md:
- Evaluates multi-factor evidence across 6 weighted dimensions (summing to 100 max pts).
- Calculates Bullish and Bearish scores completely independently (never forced to sum to 100).
- Incorporates data quality checks, timeframe alignment, and CME session status.
- Generates concrete invalidation conditions, key price levels, and structured evidence citations.
- Methodology Version: v1.0.0
"""

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    EvidenceItem,
    KeyLevels,
    MarketRegime,
    ScoreBreakdown,
)

logger = logging.getLogger(__name__)


class DirectionalScoringEngine:
    """Authoritative Engine A for Market Direction Scoring."""

    WEIGHT_STRUCTURE = 25.0
    WEIGHT_MTF_TREND = 20.0
    WEIGHT_MOMENTUM = 15.0
    WEIGHT_VOLUME = 15.0
    WEIGHT_VOLATILITY_PA = 15.0
    WEIGHT_LIQUIDITY = 10.0

    @classmethod
    def evaluate(
        cls,
        timeframe_data: dict[str, dict[str, Any]],
        symbol: str = "XAUUSDT",
        session_is_active: bool = True,
        assessment_time: datetime | None = None,
        is_live: bool = True,
    ) -> DirectionAssessment:
        """
        Evaluate directional bias from multi-timeframe indicator and structure data.
        timeframe_data must contain entries for primary timeframes (e.g. '1d', '4h', '1h', '15m', '5m').
        Each entry has:
          - 'df': pd.DataFrame with OHLCV and computed indicators (from IndicatorEngine)
          - 'structure': dict with structure_events, current_trend, sweeps, sr_zones, etc.
        """
        if assessment_time is None:
            assessment_time = datetime.now(UTC)

        # 1. Data Quality Assessment
        data_quality, quality_evidence = cls._assess_data_quality(timeframe_data)

        # 2. Extract primary analysis timeframe (1H is primary for setups, 4H/1D for macro)
        df_1h = timeframe_data.get("1h", {}).get("df", pd.DataFrame())
        struct_1h = timeframe_data.get("1h", {}).get("structure", {})

        # Evidence collectors
        supporting_evidence: list[dict[str, Any]] = []
        contradicting_evidence: list[dict[str, Any]] = []

        # 3. Factor 1: Market Structure (25%)
        struct_bull, struct_bear, struct_ev = cls._score_market_structure(timeframe_data)
        supporting_evidence.extend([e.to_dict() for e in struct_ev if e.is_supporting])
        contradicting_evidence.extend([e.to_dict() for e in struct_ev if not e.is_supporting])

        # 4. Factor 2: Multi-Timeframe Trend (20%)
        trend_bull, trend_bear, trend_ev, tf_alignment = cls._score_mtf_trend(timeframe_data)
        supporting_evidence.extend([e.to_dict() for e in trend_ev if e.is_supporting])
        contradicting_evidence.extend([e.to_dict() for e in trend_ev if not e.is_supporting])

        # 5. Factor 3: Momentum (15%)
        mom_bull, mom_bear, mom_ev = cls._score_momentum(timeframe_data)
        supporting_evidence.extend([e.to_dict() for e in mom_ev if e.is_supporting])
        contradicting_evidence.extend([e.to_dict() for e in mom_ev if not e.is_supporting])

        # 6. Factor 4: Volume & Flow (15%)
        vol_bull, vol_bear, vol_ev = cls._score_volume(timeframe_data)
        supporting_evidence.extend([e.to_dict() for e in vol_ev if e.is_supporting])
        contradicting_evidence.extend([e.to_dict() for e in vol_ev if not e.is_supporting])

        # 7. Factor 5: Volatility & Price Action (15%)
        pa_bull, pa_bear, pa_ev = cls._score_volatility_pa(timeframe_data)
        supporting_evidence.extend([e.to_dict() for e in pa_ev if e.is_supporting])
        contradicting_evidence.extend([e.to_dict() for e in pa_ev if not e.is_supporting])

        # 8. Factor 6: Liquidity (10%)
        liq_bull, liq_bear, liq_ev = cls._score_liquidity(timeframe_data)
        supporting_evidence.extend([e.to_dict() for e in liq_ev if e.is_supporting])
        contradicting_evidence.extend([e.to_dict() for e in liq_ev if not e.is_supporting])

        # Compute totals
        total_bullish = struct_bull + trend_bull + mom_bull + vol_bull + pa_bull + liq_bull
        total_bearish = struct_bear + trend_bear + mom_bear + vol_bear + pa_bear + liq_bear

        # Clamp between 0.0 and 100.0
        bullish_score = round(float(np.clip(total_bullish, 0.0, 100.0)), 2)
        bearish_score = round(float(np.clip(total_bearish, 0.0, 100.0)), 2)

        breakdown = ScoreBreakdown(
            structure_score=round(max(struct_bull, struct_bear), 2),
            mtf_trend_score=round(max(trend_bull, trend_bear), 2),
            momentum_score=round(max(mom_bull, mom_bear), 2),
            volume_score=round(max(vol_bull, vol_bear), 2),
            volatility_pa_score=round(max(pa_bull, pa_bear), 2),
            liquidity_score=round(max(liq_bull, liq_bear), 2),
            total_bullish=bullish_score,
            total_bearish=bearish_score,
        )

        # Key Levels Extraction
        key_levels = cls._extract_key_levels(df_1h, struct_1h)

        # Market Regime & Direction Classification
        regime, direction = cls._classify_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            data_quality=data_quality,
            session_is_active=session_is_active,
            tf_alignment=tf_alignment,
            df_1h=df_1h,
        )

        # Invalidation Conditions
        invalidation = cls._derive_invalidation(direction, key_levels, struct_1h)

        return DirectionAssessment(
            symbol=symbol,
            assessment_time=assessment_time,
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            breakdown=breakdown,
            supporting_evidence=supporting_evidence,
            contradicting_evidence=contradicting_evidence,
            timeframe_alignment=tf_alignment,
            key_levels=key_levels.to_dict(),
            invalidation_conditions=invalidation,
            data_quality_score=round(data_quality, 2),
            market_regime=regime.value if isinstance(regime, MarketRegime) else regime,
            methodology_version="v1.0.0",
            is_live=is_live,
        )

    # -------------------------------------------------------------------------
    # Scoring Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _score_market_structure(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Market Structure (25% max weight)."""
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        struct_1h = tf_data.get("1h", {}).get("structure", {})
        trend_1h = struct_1h.get("current_trend", "NEUTRAL").upper()
        events_1h = struct_1h.get("structure_events", [])

        # Trend State (up to 10 pts)
        if trend_1h == "BULLISH":
            bull_pts += 10.0
            evidence.append(
                EvidenceItem("Market Structure", "1H market structure is BULLISH (HH/HL series)", 10.0, True)
            )
        elif trend_1h == "BEARISH":
            bear_pts += 10.0
            evidence.append(
                EvidenceItem("Market Structure", "1H market structure is BEARISH (LH/LL series)", 10.0, False)
            )

        # Recent Structural Events (BOS, CHoCH, HH/HL) (up to 10 pts)
        recent_events = events_1h[-5:] if events_1h else []
        for ev in reversed(recent_events):
            evt_type = ev.get("event_type", "").upper()
            if "BULLISH_BOS" in evt_type or "BOS_BULL" in evt_type:
                bull_pts += 10.0
                evidence.append(
                    EvidenceItem("Market Structure", f"Confirmed Bullish BOS at {ev.get('price')}", 10.0, True)
                )
                break
            elif "BEARISH_BOS" in evt_type or "BOS_BEAR" in evt_type:
                bear_pts += 10.0
                evidence.append(
                    EvidenceItem("Market Structure", f"Confirmed Bearish BOS at {ev.get('price')}", 10.0, False)
                )
                break
            elif "BULLISH_CHOCH" in evt_type or "CHOCH_BULL" in evt_type:
                bull_pts += 8.0
                evidence.append(
                    EvidenceItem("Market Structure", f"Bullish CHoCH reversal at {ev.get('price')}", 8.0, True)
                )
                break
            elif "BEARISH_CHOCH" in evt_type or "CHOCH_BEAR" in evt_type:
                bear_pts += 8.0
                evidence.append(
                    EvidenceItem("Market Structure", f"Bearish CHoCH reversal at {ev.get('price')}", 8.0, False)
                )
                break
            elif evt_type in ["HH", "HL"]:
                bull_pts += 6.0
                evidence.append(
                    EvidenceItem("Market Structure", f"Confirmed structural {evt_type} at {ev.get('price')}", 6.0, True)
                )
                break
            elif evt_type in ["LH", "LL"]:
                bear_pts += 6.0
                evidence.append(
                    EvidenceItem(
                        "Market Structure", f"Confirmed structural {evt_type} at {ev.get('price')}", 6.0, False
                    )
                )
                break

        # S/R Zone Reaction (up to 5 pts)
        sr_zones = struct_1h.get("sr_zones", [])
        if sr_zones:
            latest_price = tf_data.get("1h", {}).get("df", pd.DataFrame())
            if not latest_price.empty and "close" in latest_price.columns:
                cur_close = float(latest_price["close"].iloc[-1])
                for z in sr_zones:
                    z_min = float(z.get("level_min", z.get("price_min", 0.0)))
                    z_max = float(z.get("level_max", z.get("price_max", 0.0)))
                    z_type = z.get("zone_type", "")
                    if z_min <= cur_close <= z_max:
                        if z_type == "SUPPORT":
                            bull_pts += 5.0
                            evidence.append(
                                EvidenceItem(
                                    "Market Structure",
                                    f"Price reacting at Support Zone ({z_min:.2f}-{z_max:.2f})",
                                    5.0,
                                    True,
                                )
                            )
                        elif z_type == "RESISTANCE":
                            bear_pts += 5.0
                            evidence.append(
                                EvidenceItem(
                                    "Market Structure",
                                    f"Price reacting at Resistance Zone ({z_min:.2f}-{z_max:.2f})",
                                    5.0,
                                    False,
                                )
                            )
                        break

        return min(bull_pts, cls.WEIGHT_STRUCTURE), min(bear_pts, cls.WEIGHT_STRUCTURE), evidence

    @classmethod
    def _score_mtf_trend(
        cls, tf_data: dict[str, dict[str, Any]]
    ) -> tuple[float, float, list[EvidenceItem], dict[str, Any]]:
        """Multi-Timeframe Trend (20% max weight)."""
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []
        alignment_summary: dict[str, Any] = {}

        # Evaluate 1D, 4H, 1H, 15M, 5M
        macro_bull = 0
        macro_bear = 0
        for tf in ["1d", "4h", "1h", "15m", "5m"]:
            df = tf_data.get(tf, {}).get("df", pd.DataFrame())
            struct = tf_data.get(tf, {}).get("structure", {})
            trend = struct.get("current_trend", "NEUTRAL").upper()

            if not df.empty and "close" in df.columns:
                close = float(df["close"].iloc[-1])
                ema_50 = (
                    float(df["ema_50"].iloc[-1]) if "ema_50" in df.columns and pd.notna(df["ema_50"].iloc[-1]) else None
                )
                direction = (
                    "BULLISH"
                    if trend == "BULLISH" or (ema_50 and close > ema_50)
                    else ("BEARISH" if trend == "BEARISH" or (ema_50 and close < ema_50) else "NEUTRAL")
                )
            else:
                direction = trend

            alignment_summary[tf] = direction
            if tf in ["1d", "4h"]:
                if direction == "BULLISH":
                    macro_bull += 1
                elif direction == "BEARISH":
                    macro_bear += 1

        # Macro Alignment (up to 10 pts)
        if macro_bull == 2:
            bull_pts += 10.0
            evidence.append(EvidenceItem("MTF Trend", "1D and 4H macro trends are fully BULLISH", 10.0, True))
        elif macro_bear == 2:
            bear_pts += 10.0
            evidence.append(EvidenceItem("MTF Trend", "1D and 4H macro trends are fully BEARISH", 10.0, False))
        elif macro_bull == 1:
            bull_pts += 5.0
        elif macro_bear == 1:
            bear_pts += 5.0

        # EMA Ribbon Alignment on 1H (up to 5 pts)
        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        if not df_1h.empty and all(k in df_1h.columns for k in ["ema_20", "ema_50", "ema_100", "ema_200"]):
            c = float(df_1h["close"].iloc[-1])
            e20 = float(df_1h["ema_20"].iloc[-1])
            e50 = float(df_1h["ema_50"].iloc[-1])
            e100 = float(df_1h["ema_100"].iloc[-1])
            e200 = float(df_1h["ema_200"].iloc[-1])

            if c > e20 > e50 > e100 > e200:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem("MTF Trend", "1H EMA Ribbon fully aligned in bullish order (20>50>100>200)", 5.0, True)
                )
            elif c < e20 < e50 < e100 < e200:
                bear_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "MTF Trend", "1H EMA Ribbon fully aligned in bearish order (20<50<100<200)", 5.0, False
                    )
                )

        # ADX Trend Strength on 1H (up to 5 pts)
        if not df_1h.empty and all(k in df_1h.columns for k in ["adx", "plus_di", "minus_di"]):
            adx = float(df_1h["adx"].iloc[-1]) if pd.notna(df_1h["adx"].iloc[-1]) else 0.0
            pdi = float(df_1h["plus_di"].iloc[-1]) if pd.notna(df_1h["plus_di"].iloc[-1]) else 0.0
            mdi = float(df_1h["minus_di"].iloc[-1]) if pd.notna(df_1h["minus_di"].iloc[-1]) else 0.0

            if adx >= 25.0:
                if pdi > mdi:
                    bull_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "MTF Trend", f"ADX is {adx:.1f} >= 25 with +DI > -DI (strong bullish trend)", 5.0, True
                        )
                    )
                elif mdi > pdi:
                    bear_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "MTF Trend", f"ADX is {adx:.1f} >= 25 with -DI > +DI (strong bearish trend)", 5.0, False
                        )
                    )

        return min(bull_pts, cls.WEIGHT_MTF_TREND), min(bear_pts, cls.WEIGHT_MTF_TREND), evidence, alignment_summary

    @classmethod
    def _score_momentum(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Momentum Analysis (15% max weight)."""
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        if df_1h.empty:
            return 0.0, 0.0, evidence

        # 1. RSI 14 (up to 5 pts)
        if "rsi_14" in df_1h.columns and pd.notna(df_1h["rsi_14"].iloc[-1]):
            rsi = float(df_1h["rsi_14"].iloc[-1])
            if 50.0 < rsi <= 80.0:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem("Momentum", f"1H RSI is {rsi:.1f} in bullish expansion regime (50-80)", 5.0, True)
                )
            elif 20.0 <= rsi < 50.0:
                bear_pts += 5.0
                evidence.append(EvidenceItem("Momentum", f"1H RSI is {rsi:.1f} in bearish regime (20-50)", 5.0, False))
            elif rsi < 20.0:
                bull_pts += 3.0  # Oversold bounce potential
                evidence.append(
                    EvidenceItem("Momentum", f"1H RSI is {rsi:.1f} in extreme oversold zone (<20)", 3.0, True)
                )
            elif rsi > 80.0:
                bull_pts += 2.0  # Strong trend momentum but overbought
                evidence.append(
                    EvidenceItem("Momentum", f"1H RSI is {rsi:.1f} in overbought momentum zone (>80)", 2.0, True)
                )

        # 2. MACD (up to 5 pts)
        macd_col = "macd_val" if "macd_val" in df_1h.columns else ("macd" if "macd" in df_1h.columns else None)
        if macd_col and "macd_signal" in df_1h.columns and "macd_hist" in df_1h.columns:
            hist = float(df_1h["macd_hist"].iloc[-1]) if pd.notna(df_1h["macd_hist"].iloc[-1]) else 0.0
            macd = float(df_1h[macd_col].iloc[-1]) if pd.notna(df_1h[macd_col].iloc[-1]) else 0.0
            sig = float(df_1h["macd_signal"].iloc[-1]) if pd.notna(df_1h["macd_signal"].iloc[-1]) else 0.0

            if macd > sig and hist > 0:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem("Momentum", "1H MACD above signal line with positive histogram", 5.0, True)
                )
            elif macd < sig and hist < 0:
                bear_pts += 5.0
                evidence.append(
                    EvidenceItem("Momentum", "1H MACD below signal line with negative histogram", 5.0, False)
                )

        # 3. Momentum Divergence (up to 5 pts)
        struct_1h = tf_data.get("1h", {}).get("structure", {})
        events = struct_1h.get("structure_events", [])
        # Look for divergence markers in structure events
        has_bull_div = any("BULLISH_DIV" in str(e.get("event_type", "")) for e in events[-5:])
        has_bear_div = any("BEARISH_DIV" in str(e.get("event_type", "")) for e in events[-5:])

        if has_bull_div:
            bull_pts += 5.0
            evidence.append(EvidenceItem("Momentum", "Confirmed Bullish Divergence on 1H", 5.0, True))
        elif has_bear_div:
            bear_pts += 5.0
            evidence.append(EvidenceItem("Momentum", "Confirmed Bearish Divergence on 1H", 5.0, False))

        return min(bull_pts, cls.WEIGHT_MOMENTUM), min(bear_pts, cls.WEIGHT_MOMENTUM), evidence

    @classmethod
    def _score_volume(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Volume & Order Flow (15% max weight)."""
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        if df_1h.empty:
            return 0.0, 0.0, evidence

        # 1. RVOL (up to 5 pts)
        rvol_col = (
            "relative_volume" if "relative_volume" in df_1h.columns else ("rvol" if "rvol" in df_1h.columns else None)
        )
        if rvol_col and pd.notna(df_1h[rvol_col].iloc[-1]):
            rvol = float(df_1h[rvol_col].iloc[-1])
            is_green = float(df_1h["close"].iloc[-1]) >= float(df_1h["open"].iloc[-1])
            if rvol >= 1.2:
                if is_green:
                    bull_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "Volume", f"High Relative Volume (RVOL={rvol:.2f} >= 1.2) on bullish bar", 5.0, True
                        )
                    )
                else:
                    bear_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "Volume", f"High Relative Volume (RVOL={rvol:.2f} >= 1.2) on bearish bar", 5.0, False
                        )
                    )

        # 2. Taker Buy/Sell Ratio (up to 5 pts)
        if "taker_buy_ratio" in df_1h.columns and pd.notna(df_1h["taker_buy_ratio"].iloc[-1]):
            taker_ratio = float(df_1h["taker_buy_ratio"].iloc[-1])
            if taker_ratio >= 0.55:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Volume", f"Aggressive taker buying (Taker Ratio={taker_ratio:.2f} >= 0.55)", 5.0, True
                    )
                )
            elif taker_ratio <= 0.45:
                bear_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Volume", f"Aggressive taker selling (Taker Ratio={taker_ratio:.2f} <= 0.45)", 5.0, False
                    )
                )

        # 3. Volume Trend (up to 5 pts)
        if "volume" in df_1h.columns and len(df_1h) >= 3:
            v_now = float(df_1h["volume"].iloc[-1])
            v_prev = float(df_1h["volume"].iloc[-2])
            is_green = float(df_1h["close"].iloc[-1]) >= float(df_1h["open"].iloc[-1])
            if v_now > v_prev:
                if is_green:
                    bull_pts += 5.0
                    evidence.append(EvidenceItem("Volume", "Expanding volume on bullish advance", 5.0, True))
                else:
                    bear_pts += 5.0
                    evidence.append(EvidenceItem("Volume", "Expanding volume on bearish selloff", 5.0, False))

        return min(bull_pts, cls.WEIGHT_VOLUME), min(bear_pts, cls.WEIGHT_VOLUME), evidence

    @classmethod
    def _score_volatility_pa(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Volatility and Price Action (15% max weight)."""
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        struct_1h = tf_data.get("1h", {}).get("structure", {})
        if df_1h.empty:
            return 0.0, 0.0, evidence

        # 1. Bollinger Band Expansion / Position (up to 5 pts)
        if all(k in df_1h.columns for k in ["bb_upper", "bb_lower", "bb_middle"]):
            c = float(df_1h["close"].iloc[-1])
            mid = float(df_1h["bb_middle"].iloc[-1])

            if c > mid:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Volatility/PA", "Price trading in upper Bollinger Band quadrant (> BB Middle)", 5.0, True
                    )
                )
            elif c < mid:
                bear_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Volatility/PA", "Price trading in lower Bollinger Band quadrant (< BB Middle)", 5.0, False
                    )
                )

        # 2. Price Action Patterns (up to 10 pts)
        patterns = struct_1h.get("price_action_patterns", [])
        if patterns:
            latest_patterns = patterns[-3:]
            for p in reversed(latest_patterns):
                ptype = p.get("pattern_type", "").upper()
                if ptype in ["BULLISH_PIN_BAR", "BULLISH_ENGULFING", "HAMMER"]:
                    bull_pts += 10.0
                    evidence.append(
                        EvidenceItem("Volatility/PA", f"Bullish price action pattern detected: {ptype}", 10.0, True)
                    )
                    break
                elif ptype in ["BEARISH_PIN_BAR", "BEARISH_ENGULFING", "SHOOTING_STAR"]:
                    bear_pts += 10.0
                    evidence.append(
                        EvidenceItem("Volatility/PA", f"Bearish price action pattern detected: {ptype}", 10.0, False)
                    )
                    break

        return min(bull_pts, cls.WEIGHT_VOLATILITY_PA), min(bear_pts, cls.WEIGHT_VOLATILITY_PA), evidence

    @classmethod
    def _score_liquidity(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Liquidity Analysis (10% max weight)."""
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        struct_1h = tf_data.get("1h", {}).get("structure", {})
        sweeps = struct_1h.get("liquidity_sweeps", [])
        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())

        # Check for confirmed liquidity sweep within last 5 events
        if sweeps:
            recent_sweeps = sweeps[-3:]
            for s in reversed(recent_sweeps):
                stype = s.get("sweep_type", "").upper()
                if "LOW" in stype or "SUPPORT" in stype or "BULLISH" in stype:
                    bull_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "Liquidity", f"Liquidity sweep of lows confirmed at {s.get('sweep_level')}", 5.0, True
                        )
                    )
                    break
                elif "HIGH" in stype or "RESISTANCE" in stype or "BEARISH" in stype:
                    bear_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "Liquidity", f"Liquidity sweep of highs confirmed at {s.get('sweep_level')}", 5.0, False
                        )
                    )
                    break

        # Check room to run (distance to opposing S/R zone > 2x ATR)
        sr_zones = struct_1h.get("sr_zones", [])
        if not df_1h.empty and sr_zones and "atr_14" in df_1h.columns:
            cur_close = float(df_1h["close"].iloc[-1])
            atr = float(df_1h["atr_14"].iloc[-1]) if pd.notna(df_1h["atr_14"].iloc[-1]) else 5.0
            resistances = [
                float(z.get("level_min", z.get("price_min", 0.0)))
                for z in sr_zones
                if z.get("zone_type") == "RESISTANCE" and float(z.get("level_min", z.get("price_min", 0.0))) > cur_close
            ]
            supports = [
                float(z.get("level_max", z.get("price_max", 0.0)))
                for z in sr_zones
                if z.get("zone_type") == "SUPPORT" and float(z.get("level_max", z.get("price_max", 0.0))) < cur_close
            ]

            if resistances and (min(resistances) - cur_close) >= 2.0 * atr:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Liquidity", f"Ample clearance to next Resistance ({min(resistances):.2f}) > 2x ATR", 5.0, True
                    )
                )
            if supports and (cur_close - max(supports)) >= 2.0 * atr:
                bear_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Liquidity", f"Ample clearance to next Support ({max(supports):.2f}) > 2x ATR", 5.0, False
                    )
                )

        return min(bull_pts, cls.WEIGHT_LIQUIDITY), min(bear_pts, cls.WEIGHT_LIQUIDITY), evidence

    # -------------------------------------------------------------------------
    # Diagnostics & Classification
    # -------------------------------------------------------------------------

    @classmethod
    def _assess_data_quality(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, list[str]]:
        """Assess input candle and indicator quality across primary timeframes."""
        required_tfs = ["1d", "4h", "1h", "15m", "5m"]
        present_tfs = [tf for tf in required_tfs if tf in tf_data and not tf_data[tf].get("df", pd.DataFrame()).empty]

        if not present_tfs:
            return 0.0, ["No timeframe data present."]

        quality_ratio = len(present_tfs) / len(required_tfs)
        notes: list[str] = []

        # Check NaN levels in 1H
        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        if not df_1h.empty:
            req_cols = ["close", "ema_20", "ema_50", "rsi_14", "atr_14"]
            missing_cols = [c for c in req_cols if c not in df_1h.columns or pd.isna(df_1h[c].iloc[-1])]
            if missing_cols:
                quality_ratio *= 0.8
                notes.append(f"Missing indicators in 1H: {missing_cols}")

        return quality_ratio * 100.0, notes

    @classmethod
    def _classify_direction(
        cls,
        bullish_score: float,
        bearish_score: float,
        data_quality: float,
        session_is_active: bool,
        tf_alignment: dict[str, Any],
        df_1h: pd.DataFrame,
    ) -> tuple[MarketRegime, DirectionType]:
        """Classify directional bias and market regime."""
        if not session_is_active:
            return MarketRegime.SESSION_INACTIVE, DirectionType.NEUTRAL

        if data_quality < 70.0:
            return MarketRegime.RANGE_BOUND, DirectionType.NEUTRAL

        diff = bullish_score - bearish_score

        # Check ADX for Trending vs Range regime
        adx = (
            float(df_1h["adx"].iloc[-1])
            if not df_1h.empty and "adx" in df_1h.columns and pd.notna(df_1h["adx"].iloc[-1])
            else 20.0
        )

        if bullish_score >= 65.0 and diff >= 25.0 and data_quality >= 80.0:
            regime = MarketRegime.TRENDING_BULLISH if adx >= 25.0 else MarketRegime.RANGE_BOUND
            return regime, DirectionType.BULLISH

        if bearish_score >= 65.0 and -diff >= 25.0 and data_quality >= 80.0:
            regime = MarketRegime.TRENDING_BEARISH if adx >= 25.0 else MarketRegime.RANGE_BOUND
            return regime, DirectionType.BEARISH

        if bullish_score >= 50.0 and diff > 10.0:
            return MarketRegime.RANGE_BOUND, DirectionType.POTENTIAL_BULLISH

        if bearish_score >= 50.0 and -diff > 10.0:
            return MarketRegime.RANGE_BOUND, DirectionType.POTENTIAL_BEARISH

        return MarketRegime.RANGE_BOUND, DirectionType.NEUTRAL

    @classmethod
    def _extract_key_levels(cls, df_1h: pd.DataFrame, struct_1h: dict[str, Any]) -> KeyLevels:
        """Extract key technical and structural price levels."""
        kl = KeyLevels()
        if not df_1h.empty:
            kl.vwap = (
                float(df_1h["vwap"].iloc[-1]) if "vwap" in df_1h.columns and pd.notna(df_1h["vwap"].iloc[-1]) else None
            )
            kl.ema_20 = (
                float(df_1h["ema_20"].iloc[-1])
                if "ema_20" in df_1h.columns and pd.notna(df_1h["ema_20"].iloc[-1])
                else None
            )
            kl.ema_50 = (
                float(df_1h["ema_50"].iloc[-1])
                if "ema_50" in df_1h.columns and pd.notna(df_1h["ema_50"].iloc[-1])
                else None
            )
            kl.ema_100 = (
                float(df_1h["ema_100"].iloc[-1])
                if "ema_100" in df_1h.columns and pd.notna(df_1h["ema_100"].iloc[-1])
                else None
            )
            kl.ema_200 = (
                float(df_1h["ema_200"].iloc[-1])
                if "ema_200" in df_1h.columns and pd.notna(df_1h["ema_200"].iloc[-1])
                else None
            )

            # 20-period swing extrema
            kl.swing_high = float(df_1h["high"].tail(20).max()) if "high" in df_1h.columns else None
            kl.swing_low = float(df_1h["low"].tail(20).min()) if "low" in df_1h.columns else None

        sr_zones = struct_1h.get("sr_zones", [])
        if sr_zones and not df_1h.empty and "close" in df_1h.columns:
            cur_close = float(df_1h["close"].iloc[-1])
            res = [
                float(z.get("level_min", z.get("price_min", 0.0)))
                for z in sr_zones
                if z.get("zone_type") == "RESISTANCE" and float(z.get("level_min", z.get("price_min", 0.0))) > cur_close
            ]
            sup = [
                float(z.get("level_max", z.get("price_max", 0.0)))
                for z in sr_zones
                if z.get("zone_type") == "SUPPORT" and float(z.get("level_max", z.get("price_max", 0.0))) < cur_close
            ]
            kl.nearest_resistance = min(res) if res else None
            kl.nearest_support = max(sup) if sup else None

        return kl

    @classmethod
    def _derive_invalidation(cls, direction: DirectionType, key_levels: KeyLevels, struct_1h: dict[str, Any]) -> str:
        """Derive explicit price invalidation condition."""
        if direction in [DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH]:
            ref_low = key_levels.nearest_support or key_levels.swing_low or key_levels.ema_50
            if ref_low:
                return f"Bullish bias invalidated if price closes below key structural level at {ref_low:.2f} USDT."
            return "Bullish bias invalidated if price breaks below recent swing low."

        if direction in [DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH]:
            ref_high = key_levels.nearest_resistance or key_levels.swing_high or key_levels.ema_50
            if ref_high:
                return f"Bearish bias invalidated if price closes above key structural level at {ref_high:.2f} USDT."
            return "Bearish bias invalidated if price breaks above recent swing high."

        return "Neutral market regime. No active directional invalidation level."
