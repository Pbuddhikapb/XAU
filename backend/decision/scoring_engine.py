"""
Engine A: Market Direction Scoring Engine for Binance XAUUSDT.
Strictly conforms to Section 6, 7, and 9 of PROJECT_SPECIFICATION.md and Section 16 of Forensic Audit:
- Multi-factor heuristic evidence evaluated across 6 weighted dimensions.
- Independent Bullish and Bearish scoring (never forced to sum to 100).
- Labeled explicitly as heuristic indicator scores (0-100), never statistical probabilities.
- Correlation-Aware Deduplication & Capping:
    * Collinear Group 1: Structure (25%) + MTF Trend (20%) capped at config threshold (default 35.0).
    * Collinear Group 2: Momentum (15%) + Volatility/Price Action (15%) capped at config threshold (default 22.0).
- Data Quality & Market Session Gating:
    * Data quality score < 70 or closed CME market forces NEUTRAL / DATA_UNAVAILABLE.
- Comprehensive output: Supporting evidence, contradicting evidence, key levels, invalidation, and version stamping.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from backend.config import settings
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

    @classmethod
    def evaluate(
        cls,
        timeframe_data: dict[str, dict[str, Any]],
        symbol: str = "XAUUSDT",
        session_is_active: bool = True,
        assessment_time: datetime | None = None,
        is_live: bool = False,
    ) -> DirectionAssessment:
        """
        Evaluate directional bias from multi-timeframe indicator and structure data.
        timeframe_data contains entries for primary timeframes ('1d', '4h', '1h', '15m', '5m').
        Each entry has:
          - 'df': pd.DataFrame with OHLCV and computed indicators
          - 'structure': dict with structure_events, current_trend, sweeps, sr_zones, price_action_patterns
        """
        if assessment_time is None:
            if is_live:
                assessment_time = datetime.now(UTC)
            else:
                # Find latest candle timestamp across supplied timeframes
                latest_t: datetime | None = None
                for tf_bundle in timeframe_data.values():
                    df_cur = tf_bundle.get("df", pd.DataFrame())
                    if not df_cur.empty and "open_time" in df_cur.columns:
                        t = df_cur["open_time"].iloc[-1]
                        if latest_t is None or t > latest_t:
                            latest_t = t
                assessment_time = latest_t or datetime.now(UTC)

        # 1. Data Quality Assessment (including staleness check for live mode)
        data_quality, quality_warnings = cls._assess_data_quality(
            timeframe_data,
            session_is_active=session_is_active,
            assessment_time=assessment_time,
            is_live=is_live,
        )

        # 2. Extract primary analysis timeframe (1H primary, 4H/1D macro)
        df_1h = timeframe_data.get("1h", {}).get("df", pd.DataFrame())
        struct_1h = timeframe_data.get("1h", {}).get("structure", {})

        # Raw factor evidence lists
        bull_evidence_pool: list[EvidenceItem] = []
        bear_evidence_pool: list[EvidenceItem] = []

        # 3. Factor 1: Market Structure (Weight: settings.WEIGHT_STRUCTURE)
        struct_bull, struct_bear, struct_ev = cls._score_market_structure(timeframe_data)
        for e in struct_ev:
            (bull_evidence_pool if e.is_supporting else bear_evidence_pool).append(e)

        # 4. Factor 2: Multi-Timeframe Trend (Weight: settings.WEIGHT_MTF_TREND)
        trend_bull, trend_bear, trend_ev, tf_alignment = cls._score_mtf_trend(timeframe_data)
        for e in trend_ev:
            (bull_evidence_pool if e.is_supporting else bear_evidence_pool).append(e)

        # 5. Factor 3: Momentum (Weight: settings.WEIGHT_MOMENTUM)
        mom_bull, mom_bear, mom_ev = cls._score_momentum(timeframe_data)
        for e in mom_ev:
            (bull_evidence_pool if e.is_supporting else bear_evidence_pool).append(e)

        # 6. Factor 4: Volume & Order Flow (Weight: settings.WEIGHT_VOLUME)
        vol_bull, vol_bear, vol_ev = cls._score_volume(timeframe_data)
        for e in vol_ev:
            (bull_evidence_pool if e.is_supporting else bear_evidence_pool).append(e)

        # 7. Factor 5: Volatility & Price Action (Weight: settings.WEIGHT_VOLATILITY_PA)
        pa_bull, pa_bear, pa_ev = cls._score_volatility_pa(timeframe_data)
        for e in pa_ev:
            (bull_evidence_pool if e.is_supporting else bear_evidence_pool).append(e)

        # 8. Factor 6: Liquidity (Weight: settings.WEIGHT_LIQUIDITY)
        liq_bull, liq_bear, liq_ev = cls._score_liquidity(timeframe_data)
        for e in liq_ev:
            (bull_evidence_pool if e.is_supporting else bear_evidence_pool).append(e)

        # ---------------------------------------------------------------------
        # Correlation-Aware Deduplication & Capping
        # ---------------------------------------------------------------------
        # Group 1: Structure (25) + MTF Trend (20) collinearity cap
        max_struct_trend = settings.MAX_STRUCTURE_TREND_COMBINED
        struct_trend_bull_raw = struct_bull + trend_bull
        struct_trend_bear_raw = struct_bear + trend_bear
        struct_trend_bull_dampened = min(struct_trend_bull_raw, max_struct_trend)
        struct_trend_bear_dampened = min(struct_trend_bear_raw, max_struct_trend)

        if struct_trend_bull_raw > max_struct_trend:
            bull_evidence_pool.append(
                EvidenceItem(
                    "Correlation Control",
                    f"Structure + MTF Trend collinearity capped at {max_struct_trend:.1f} pts "
                    f"(dampened by -{struct_trend_bull_raw - max_struct_trend:.1f} pts)",
                    0.0,
                    True,
                )
            )
        if struct_trend_bear_raw > max_struct_trend:
            bear_evidence_pool.append(
                EvidenceItem(
                    "Correlation Control",
                    f"Structure + MTF Trend collinearity capped at {max_struct_trend:.1f} pts "
                    f"(dampened by -{struct_trend_bear_raw - max_struct_trend:.1f} pts)",
                    0.0,
                    False,
                )
            )

        # Group 2: Momentum (15) + Volatility/Price Action (15) collinearity cap
        max_mom_pa = settings.MAX_MOMENTUM_PA_COMBINED
        mom_pa_bull_raw = mom_bull + pa_bull
        mom_pa_bear_raw = mom_bear + pa_bear
        mom_pa_bull_dampened = min(mom_pa_bull_raw, max_mom_pa)
        mom_pa_bear_dampened = min(mom_pa_bear_raw, max_mom_pa)

        if mom_pa_bull_raw > max_mom_pa:
            bull_evidence_pool.append(
                EvidenceItem(
                    "Correlation Control",
                    f"Momentum + Price Action collinearity capped at {max_mom_pa:.1f} pts "
                    f"(dampened by -{mom_pa_bull_raw - max_mom_pa:.1f} pts)",
                    0.0,
                    True,
                )
            )
        if mom_pa_bear_raw > max_mom_pa:
            bear_evidence_pool.append(
                EvidenceItem(
                    "Correlation Control",
                    f"Momentum + Price Action collinearity capped at {max_mom_pa:.1f} pts "
                    f"(dampened by -{mom_pa_bear_raw - max_mom_pa:.1f} pts)",
                    0.0,
                    False,
                )
            )

        # Compute independent totals
        total_bullish_calc = struct_trend_bull_dampened + mom_pa_bull_dampened + vol_bull + liq_bull
        total_bearish_calc = struct_trend_bear_dampened + mom_pa_bear_dampened + vol_bear + liq_bear

        # Clamp between 0.0 and 100.0 (strictly heuristic scores, never probabilities)
        bullish_score = round(float(np.clip(total_bullish_calc, 0.0, 100.0)), 2)
        bearish_score = round(float(np.clip(total_bearish_calc, 0.0, 100.0)), 2)

        breakdown = ScoreBreakdown(
            structure_score=round(max(struct_bull, struct_bear), 2),
            mtf_trend_score=round(max(trend_bull, trend_bear), 2),
            momentum_score=round(max(mom_bull, mom_bear), 2),
            volume_score=round(max(vol_bull, vol_bear), 2),
            volatility_pa_score=round(max(pa_bull, pa_bear), 2),
            liquidity_score=round(max(liq_bull, liq_bear), 2),
            structure_trend_uncapped=round(max(struct_trend_bull_raw, struct_trend_bear_raw), 2),
            structure_trend_dampened=round(max(struct_trend_bull_dampened, struct_trend_bear_dampened), 2),
            momentum_pa_uncapped=round(max(mom_pa_bull_raw, mom_pa_bear_raw), 2),
            momentum_pa_dampened=round(max(mom_pa_bull_dampened, mom_pa_bear_dampened), 2),
            total_bullish=bullish_score,
            total_bearish=bearish_score,
        )

        # Key Levels Extraction
        key_levels = cls._extract_key_levels(df_1h, struct_1h)

        # Market Regime & Direction Classification (Gated by Quality, CME Session & Macro Alignment)
        regime, direction, macro_note = cls._classify_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            data_quality=data_quality,
            session_is_active=session_is_active,
            tf_alignment=tf_alignment,
            df_1h=df_1h,
        )

        # Systematic Supporting vs Contradicting Evidence Categorization
        supporting_evidence: list[dict[str, Any]] = []
        contradicting_evidence: list[dict[str, Any]] = []

        if direction in [DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH]:
            supporting_evidence = [e.to_dict() for e in bull_evidence_pool]
            contradicting_evidence = [e.to_dict() for e in bear_evidence_pool]
        elif direction in [DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH]:
            supporting_evidence = [e.to_dict() for e in bear_evidence_pool]
            contradicting_evidence = [e.to_dict() for e in bull_evidence_pool]
        else:
            # NEUTRAL: present both sets transparently
            supporting_evidence = [e.to_dict() for e in bull_evidence_pool]
            contradicting_evidence = [e.to_dict() for e in bear_evidence_pool]

        if macro_note:
            contradicting_evidence.append(
                {"factor": "Macro Trend Filter", "description": macro_note, "score_contribution": 0.0}
            )

        for w in quality_warnings:
            contradicting_evidence.append(
                {"factor": "Data Quality Warning", "description": w, "score_contribution": 0.0}
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
            score_label="HEURISTIC_INDICATOR_SCORE",
            methodology_version=settings.DECISION_METHODOLOGY_VERSION,
            is_live=is_live,
        )

    # -------------------------------------------------------------------------
    # Scoring Factors
    # -------------------------------------------------------------------------

    @classmethod
    def _score_market_structure(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Market Structure (settings.WEIGHT_STRUCTURE = 25% max weight)."""
        max_wt = settings.WEIGHT_STRUCTURE
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        struct_1h = tf_data.get("1h", {}).get("structure", {})
        trend_1h = struct_1h.get("current_trend", "NEUTRAL").upper()
        events_1h = struct_1h.get("structure_events", [])

        # 1. Structural Trend State (up to 10 pts)
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

        # 2. Structural Events (BOS, CHoCH, Swing Extrema) (up to 10 pts)
        recent_events = events_1h[-5:] if events_1h else []
        for ev in reversed(recent_events):
            evt_type = ev.get("event_type", "").upper()
            price = ev.get("price", 0.0)
            if "BULLISH_BOS" in evt_type or "BOS_BULL" in evt_type:
                bull_pts += 10.0
                evidence.append(EvidenceItem("Market Structure", f"Confirmed Bullish BOS at {price}", 10.0, True))
                break
            elif "BEARISH_BOS" in evt_type or "BOS_BEAR" in evt_type:
                bear_pts += 10.0
                evidence.append(EvidenceItem("Market Structure", f"Confirmed Bearish BOS at {price}", 10.0, False))
                break
            elif "BULLISH_CHOCH" in evt_type or "CHOCH_BULL" in evt_type:
                bull_pts += 8.0
                evidence.append(EvidenceItem("Market Structure", f"Bullish CHoCH reversal at {price}", 8.0, True))
                break
            elif "BEARISH_CHOCH" in evt_type or "CHOCH_BEAR" in evt_type:
                bear_pts += 8.0
                evidence.append(EvidenceItem("Market Structure", f"Bearish CHoCH reversal at {price}", 8.0, False))
                break
            elif evt_type in ["HH", "HL", "SWING_HIGH", "SWING_LOW"]:
                if evt_type in ["HH", "HL"]:
                    bull_pts += 6.0
                    evidence.append(
                        EvidenceItem("Market Structure", f"Confirmed structural {evt_type} at {price}", 6.0, True)
                    )
                else:
                    bear_pts += 6.0
                    evidence.append(
                        EvidenceItem("Market Structure", f"Confirmed structural {evt_type} at {price}", 6.0, False)
                    )
                break

        # 3. S/R Zone Proximity & Reaction (up to 5 pts)
        sr_zones = struct_1h.get("sr_zones", [])
        if sr_zones:
            df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
            if not df_1h.empty and "close" in df_1h.columns:
                cur_close = float(df_1h["close"].iloc[-1])
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

        return min(bull_pts, max_wt), min(bear_pts, max_wt), evidence

    @classmethod
    def _score_mtf_trend(
        cls, tf_data: dict[str, dict[str, Any]]
    ) -> tuple[float, float, list[EvidenceItem], dict[str, Any]]:
        """Multi-Timeframe Trend (settings.WEIGHT_MTF_TREND = 20% max weight)."""
        max_wt = settings.WEIGHT_MTF_TREND
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []
        alignment_summary: dict[str, Any] = {}

        macro_bull = 0
        macro_bear = 0
        for tf in ["1d", "4h", "1h", "15m", "5m"]:
            df = tf_data.get(tf, {}).get("df", pd.DataFrame())
            struct = tf_data.get(tf, {}).get("structure", {})
            trend = struct.get("current_trend", "NEUTRAL").upper()

            if not df.empty and "close" in df.columns:
                close = float(df["close"].iloc[-1])
                ema_50 = (
                    float(df["ema_50"].iloc[-1])
                    if "ema_50" in df.columns and pd.notna(df["ema_50"].iloc[-1])
                    else None
                )
                if trend == "BULLISH" or (ema_50 and close > ema_50):
                    direction = "BULLISH"
                elif trend == "BEARISH" or (ema_50 and close < ema_50):
                    direction = "BEARISH"
                else:
                    direction = "NEUTRAL"
            else:
                direction = trend

            alignment_summary[tf] = direction
            if tf in ["1d", "4h"]:
                if direction == "BULLISH":
                    macro_bull += 1
                elif direction == "BEARISH":
                    macro_bear += 1

        # 1. Macro Alignment (up to 10 pts)
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

        # 2. EMA Ribbon Alignment on 1H (up to 5 pts)
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

        # 3. ADX Directional Index on 1H (up to 5 pts)
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

        return min(bull_pts, max_wt), min(bear_pts, max_wt), evidence, alignment_summary

    @classmethod
    def _score_momentum(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Momentum Analysis (settings.WEIGHT_MOMENTUM = 15% max weight)."""
        max_wt = settings.WEIGHT_MOMENTUM
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
                bull_pts += 2.0  # Overbought expansion
                evidence.append(
                    EvidenceItem("Momentum", f"1H RSI is {rsi:.1f} in overbought momentum zone (>80)", 2.0, True)
                )

        # 2. MACD Histogram & Signal (up to 5 pts)
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
        has_bull_div = any("BULLISH_DIV" in str(e.get("event_type", "")) for e in events[-5:])
        has_bear_div = any("BEARISH_DIV" in str(e.get("event_type", "")) for e in events[-5:])

        if has_bull_div:
            bull_pts += 5.0
            evidence.append(EvidenceItem("Momentum", "Confirmed Bullish Divergence on 1H", 5.0, True))
        elif has_bear_div:
            bear_pts += 5.0
            evidence.append(EvidenceItem("Momentum", "Confirmed Bearish Divergence on 1H", 5.0, False))

        return min(bull_pts, max_wt), min(bear_pts, max_wt), evidence

    @classmethod
    def _score_volume(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Volume & Order Flow (settings.WEIGHT_VOLUME = 15% max weight)."""
        max_wt = settings.WEIGHT_VOLUME
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        if df_1h.empty:
            return 0.0, 0.0, evidence

        # 1. Relative Volume (RVOL) (up to 5 pts)
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
                            "Volume", f"High Relative Volume (RVOL={rvol:.2f} >= 1.2) on bullish candle", 5.0, True
                        )
                    )
                else:
                    bear_pts += 5.0
                    evidence.append(
                        EvidenceItem(
                            "Volume", f"High Relative Volume (RVOL={rvol:.2f} >= 1.2) on bearish candle", 5.0, False
                        )
                    )

        # 2. Taker Buy/Sell Ratio (up to 5 pts)
        if "taker_buy_ratio" in df_1h.columns and pd.notna(df_1h["taker_buy_ratio"].iloc[-1]):
            taker_ratio = float(df_1h["taker_buy_ratio"].iloc[-1])
            if taker_ratio >= 0.55:
                bull_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Volume", f"Aggressive taker buying flow (Taker Ratio={taker_ratio:.2f} >= 0.55)", 5.0, True
                    )
                )
            elif taker_ratio <= 0.45:
                bear_pts += 5.0
                evidence.append(
                    EvidenceItem(
                        "Volume", f"Aggressive taker selling flow (Taker Ratio={taker_ratio:.2f} <= 0.45)", 5.0, False
                    )
                )

        # 3. Volume Trend Progression (up to 5 pts)
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

        return min(bull_pts, max_wt), min(bear_pts, max_wt), evidence

    @classmethod
    def _score_volatility_pa(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Volatility and Price Action (settings.WEIGHT_VOLATILITY_PA = 15% max weight)."""
        max_wt = settings.WEIGHT_VOLATILITY_PA
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        struct_1h = tf_data.get("1h", {}).get("structure", {})
        if df_1h.empty:
            return 0.0, 0.0, evidence

        # 1. Bollinger Band Quadrant (up to 5 pts)
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
            for p in reversed(patterns[-3:]):
                ptype = p.get("pattern_type", "").upper()
                if ptype in ["REJECTION_BULL", "ENGULFING_BULL", "BREAKOUT_RETEST", "BULLISH_PIN_BAR"]:
                    bull_pts += 10.0
                    evidence.append(
                        EvidenceItem("Volatility/PA", f"Bullish price action pattern detected: {ptype}", 10.0, True)
                    )
                    break
                elif ptype in ["REJECTION_BEAR", "ENGULFING_BEAR", "BEARISH_PIN_BAR"]:
                    bear_pts += 10.0
                    evidence.append(
                        EvidenceItem("Volatility/PA", f"Bearish price action pattern detected: {ptype}", 10.0, False)
                    )
                    break

        return min(bull_pts, max_wt), min(bear_pts, max_wt), evidence

    @classmethod
    def _score_liquidity(cls, tf_data: dict[str, dict[str, Any]]) -> tuple[float, float, list[EvidenceItem]]:
        """Liquidity Analysis (settings.WEIGHT_LIQUIDITY = 10% max weight)."""
        max_wt = settings.WEIGHT_LIQUIDITY
        bull_pts = 0.0
        bear_pts = 0.0
        evidence: list[EvidenceItem] = []

        struct_1h = tf_data.get("1h", {}).get("structure", {})
        sweeps = struct_1h.get("liquidity_sweeps", [])
        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())

        # 1. Confirmed Liquidity Sweeps (up to 5 pts)
        if sweeps:
            for s in reversed(sweeps[-3:]):
                stype = s.get("sweep_type", "").upper()
                level = s.get("swept_level", s.get("sweep_level", 0.0))
                if "LOW" in stype or "SUPPORT" in stype:
                    bull_pts += 5.0
                    evidence.append(
                        EvidenceItem("Liquidity", f"Liquidity sweep of lows confirmed at {level}", 5.0, True)
                    )
                    break
                elif "HIGH" in stype or "RESISTANCE" in stype:
                    bear_pts += 5.0
                    evidence.append(
                        EvidenceItem("Liquidity", f"Liquidity sweep of highs confirmed at {level}", 5.0, False)
                    )
                    break

        # 2. Clearance / Room to Run (> 2x ATR to opposing zone) (up to 5 pts)
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

        return min(bull_pts, max_wt), min(bear_pts, max_wt), evidence

    # -------------------------------------------------------------------------
    # Diagnostics & Classification
    # -------------------------------------------------------------------------

    @classmethod
    def _assess_data_quality(
        cls,
        tf_data: dict[str, dict[str, Any]],
        session_is_active: bool = True,
        assessment_time: datetime | None = None,
        is_live: bool = False,
    ) -> tuple[float, list[str]]:
        """Assess input candle and indicator quality across primary timeframes, including real-time staleness."""
        required_tfs = settings.PRIMARY_TIMEFRAMES
        present_tfs = [tf for tf in required_tfs if tf in tf_data and not tf_data[tf].get("df", pd.DataFrame()).empty]

        if not present_tfs:
            return 0.0, ["No timeframe data present."]

        quality_ratio = len(present_tfs) / len(required_tfs)
        notes: list[str] = []

        if len(present_tfs) < len(required_tfs):
            missing_tfs = [tf for tf in required_tfs if tf not in present_tfs]
            notes.append(f"Missing required primary timeframes: {missing_tfs}")

        # Check NaN levels in 1H
        df_1h = tf_data.get("1h", {}).get("df", pd.DataFrame())
        if not df_1h.empty:
            req_cols = ["close", "ema_20", "ema_50", "rsi_14", "atr_14"]
            missing_cols = [c for c in req_cols if c not in df_1h.columns or pd.isna(df_1h[c].iloc[-1])]
            if missing_cols:
                quality_ratio *= 0.8
                notes.append(f"Missing essential indicators in 1H: {missing_cols}")

        # Real-time staleness penalty: if live and CME market is open and latest candle lag exceeds 180s, force DQ < 70
        if is_live and session_is_active and assessment_time is not None:
            latest_candle_time: datetime | None = None
            for tf_bundle in tf_data.values():
                df_cur = tf_bundle.get("df", pd.DataFrame())
                if not df_cur.empty and "open_time" in df_cur.columns:
                    t = df_cur["open_time"].iloc[-1]
                    if latest_candle_time is None or t > latest_candle_time:
                        latest_candle_time = t

            if latest_candle_time is not None:
                eval_t = assessment_time
                if eval_t.tzinfo is not None and latest_candle_time.tzinfo is None:
                    latest_candle_time = latest_candle_time.replace(tzinfo=UTC)
                elif eval_t.tzinfo is None and latest_candle_time.tzinfo is not None:
                    eval_t = eval_t.replace(tzinfo=UTC)
                lag_seconds = (eval_t - latest_candle_time).total_seconds()
                if lag_seconds > 180.0:
                    quality_ratio = min(quality_ratio, 0.65)
                    notes.append(
                        f"Data staleness warning: latest candle lag {lag_seconds:.0f}s "
                        "exceeds 180s during active CME hours."
                    )

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
    ) -> tuple[MarketRegime, DirectionType, str | None]:
        """Classify directional bias and market regime with strict gating and macro alignment confirmation."""
        if not session_is_active:
            return MarketRegime.SESSION_INACTIVE, DirectionType.NEUTRAL, None

        if data_quality < settings.DATA_QUALITY_MIN_SCORE:
            return MarketRegime.DATA_UNAVAILABLE, DirectionType.NEUTRAL, None

        diff = bullish_score - bearish_score

        # Check ADX for Trending vs Range regime
        adx = (
            float(df_1h["adx"].iloc[-1])
            if not df_1h.empty and "adx" in df_1h.columns and pd.notna(df_1h["adx"].iloc[-1])
            else 20.0
        )

        if bullish_score >= 65.0 and diff >= 25.0 and data_quality >= 80.0:
            regime = MarketRegime.TRENDING_BULLISH if adx >= 25.0 else MarketRegime.RANGE_BOUND
            # Macro alignment confirmation: check if 4H or 1D actively opposes
            opposing_tf = []
            if tf_alignment.get("4h") == "BEARISH":
                opposing_tf.append("4H")
            if tf_alignment.get("1d") == "BEARISH":
                opposing_tf.append("1D")
            if opposing_tf:
                note = (
                    f"Macro trend {'/'.join(opposing_tf)} is BEARISH, opposing 1H bullish bias; "
                    "downgraded to POTENTIAL_BULLISH."
                )
                return regime, DirectionType.POTENTIAL_BULLISH, note
            return regime, DirectionType.BULLISH, None

        if bearish_score >= 65.0 and -diff >= 25.0 and data_quality >= 80.0:
            regime = MarketRegime.TRENDING_BEARISH if adx >= 25.0 else MarketRegime.RANGE_BOUND
            # Macro alignment confirmation: check if 4H or 1D actively opposes
            opposing_tf = []
            if tf_alignment.get("4h") == "BULLISH":
                opposing_tf.append("4H")
            if tf_alignment.get("1d") == "BULLISH":
                opposing_tf.append("1D")
            if opposing_tf:
                note = (
                    f"Macro trend {'/'.join(opposing_tf)} is BULLISH, opposing 1H bearish bias; "
                    "downgraded to POTENTIAL_BEARISH."
                )
                return regime, DirectionType.POTENTIAL_BEARISH, note
            return regime, DirectionType.BEARISH, None

        if bullish_score >= 50.0 and diff > 10.0:
            return MarketRegime.RANGE_BOUND, DirectionType.POTENTIAL_BULLISH, None

        if bearish_score >= 50.0 and -diff > 10.0:
            return MarketRegime.RANGE_BOUND, DirectionType.POTENTIAL_BEARISH, None

        return MarketRegime.RANGE_BOUND, DirectionType.NEUTRAL, None

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
        """Derive explicit two-tier price & momentum invalidation condition."""
        if direction in [DirectionType.BULLISH, DirectionType.POTENTIAL_BULLISH]:
            ref_low = key_levels.nearest_support or key_levels.swing_low or key_levels.ema_50
            hard_tier = (
                f"Hard Structural: Bullish bias invalidated if price closes below "
                f"key structural level at {ref_low:.2f} USDT."
                if ref_low
                else "Hard Structural: Bullish bias invalidated if price breaks below recent swing low."
            )
            soft_tier = "Soft Momentum Warning: 1H RSI crosses below 50.0 or EMA20 crosses below EMA50."
            return f"{hard_tier} | {soft_tier}"

        if direction in [DirectionType.BEARISH, DirectionType.POTENTIAL_BEARISH]:
            ref_high = key_levels.nearest_resistance or key_levels.swing_high or key_levels.ema_50
            hard_tier = (
                f"Hard Structural: Bearish bias invalidated if price closes above "
                f"key structural level at {ref_high:.2f} USDT."
                if ref_high
                else "Hard Structural: Bearish bias invalidated if price breaks above recent swing high."
            )
            soft_tier = "Soft Momentum Warning: 1H RSI crosses above 50.0 or EMA20 crosses above EMA50."
            return f"{hard_tier} | {soft_tier}"

        return "Neutral market regime. No active directional invalidation level."
