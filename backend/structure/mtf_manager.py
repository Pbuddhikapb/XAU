"""
Multi-Timeframe (MTF) Alignment Manager for Binance XAUUSDT.
Strictly conforms to Section 6 of PROJECT_SPECIFICATION.md:
- Primary timeframes: 1D, 4H, 1H, 15M, 5M.
- Assigns specific responsibilities to each timeframe.
- Calculates compound MTF directional score and detects countertrend alignments.
"""

from dataclasses import asdict, dataclass
from typing import Any

TIMEFRAME_WEIGHTS = {
    "1d": 0.30,  # Major market direction
    "4h": 0.25,  # Primary trend
    "1h": 0.20,  # Setup identification
    "15m": 0.15,  # Confirmation
    "5m": 0.10,  # Entry refinement
}

DIRECTION_SCORE_MAP = {
    "BULLISH": 1.0,
    "POTENTIAL_BULLISH": 0.5,
    "NEUTRAL": 0.0,
    "POTENTIAL_BEARISH": -0.5,
    "BEARISH": -1.0,
}


@dataclass
class TimeframeState:
    timeframe: str
    direction: str  # BULLISH, POTENTIAL_BULLISH, NEUTRAL, POTENTIAL_BEARISH, BEARISH
    trend_strength: float
    structure_type: str  # e.g., "HH_HL" | "LH_LL" | "CHOP"
    is_countertrend: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MTFAlignmentResult:
    compound_score: float  # -1.0 (strongly bearish) to +1.0 (strongly bullish)
    overall_bias: str  # BULLISH | BEARISH | NEUTRAL | CONFLICTING
    alignment_state: str  # ALIGNED_BULLISH, ALIGNED_BEARISH, COUNTERTREND_PULLBACK, COUNTERTREND_RALLY, CONFLICTING
    macro_trend: str  # 1D/4H consensus
    micro_trend: str  # 15M/5M consensus
    timeframes: dict[str, TimeframeState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "compound_score": round(self.compound_score, 4),
            "overall_bias": self.overall_bias,
            "alignment_state": self.alignment_state,
            "macro_trend": self.macro_trend,
            "micro_trend": self.micro_trend,
            "timeframes": {tf: state.to_dict() for tf, state in self.timeframes.items()},
        }


class MTFManager:
    """Evaluates multi-timeframe alignment across 1D, 4H, 1H, 15M, and 5M."""

    @staticmethod
    def evaluate_alignment(timeframe_directions: dict[str, dict[str, Any]]) -> MTFAlignmentResult:
        """
        Evaluate compound multi-timeframe directional alignment.
        timeframe_directions: dict mapping timeframe ('1d', '4h', etc.) to:
            {'direction': 'BULLISH', 'strength': 75.0, 'structure': 'HH_HL'}
        """
        states: dict[str, TimeframeState] = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for tf, weight in TIMEFRAME_WEIGHTS.items():
            tf_data = timeframe_directions.get(tf, {})
            direction = tf_data.get("direction", "NEUTRAL").upper()
            strength = float(tf_data.get("strength", 0.0))
            structure = tf_data.get("structure", "CHOP")

            score = DIRECTION_SCORE_MAP.get(direction, 0.0)
            weighted_sum += score * weight
            total_weight += weight

            states[tf] = TimeframeState(
                timeframe=tf,
                direction=direction,
                trend_strength=strength,
                structure_type=structure,
                is_countertrend=False,  # Evaluated below against macro
            )

        compound_score = weighted_sum / (total_weight if total_weight > 0 else 1.0)

        # Macro trend: weighted consensus of 1D and 4H
        d1_dir = states["1d"].direction if "1d" in states else "NEUTRAL"
        h4_dir = states["4h"].direction if "4h" in states else "NEUTRAL"

        if d1_dir in ("BULLISH", "POTENTIAL_BULLISH") and h4_dir in ("BULLISH", "POTENTIAL_BULLISH"):
            macro_trend = "BULLISH"
        elif d1_dir in ("BEARISH", "POTENTIAL_BEARISH") and h4_dir in ("BEARISH", "POTENTIAL_BEARISH"):
            macro_trend = "BEARISH"
        elif d1_dir in ("BULLISH", "POTENTIAL_BULLISH") or h4_dir in ("BULLISH", "POTENTIAL_BULLISH"):
            macro_trend = "POTENTIAL_BULLISH"
        elif d1_dir in ("BEARISH", "POTENTIAL_BEARISH") or h4_dir in ("BEARISH", "POTENTIAL_BEARISH"):
            macro_trend = "POTENTIAL_BEARISH"
        else:
            macro_trend = "NEUTRAL"

        # Micro trend: 15M and 5M
        m15_dir = states["15m"].direction if "15m" in states else "NEUTRAL"
        m5_dir = states["5m"].direction if "5m" in states else "NEUTRAL"

        if m15_dir in ("BULLISH", "POTENTIAL_BULLISH") and m5_dir in ("BULLISH", "POTENTIAL_BULLISH"):
            micro_trend = "BULLISH"
        elif m15_dir in ("BEARISH", "POTENTIAL_BEARISH") and m5_dir in ("BEARISH", "POTENTIAL_BEARISH"):
            micro_trend = "BEARISH"
        else:
            micro_trend = "NEUTRAL"

        # Mark countertrend timeframes
        for state in states.values():
            if macro_trend == "BULLISH" and state.direction in ("BEARISH", "POTENTIAL_BEARISH"):
                state.is_countertrend = True
            elif macro_trend == "BEARISH" and state.direction in ("BULLISH", "POTENTIAL_BULLISH"):
                state.is_countertrend = True

        # Classify compound alignment state
        if compound_score >= 0.50:
            overall_bias = "BULLISH"
            alignment_state = "ALIGNED_BULLISH"
        elif compound_score <= -0.50:
            overall_bias = "BEARISH"
            alignment_state = "ALIGNED_BEARISH"
        elif macro_trend == "BULLISH" and micro_trend == "BEARISH":
            overall_bias = "POTENTIAL_BULLISH"
            alignment_state = "COUNTERTREND_PULLBACK"
        elif macro_trend == "BEARISH" and micro_trend == "BULLISH":
            overall_bias = "POTENTIAL_BEARISH"
            alignment_state = "COUNTERTREND_RALLY"
        else:
            overall_bias = "NEUTRAL"
            alignment_state = "CONFLICTING"

        return MTFAlignmentResult(
            compound_score=compound_score,
            overall_bias=overall_bias,
            alignment_state=alignment_state,
            macro_trend=macro_trend,
            micro_trend=micro_trend,
            timeframes=states,
        )
