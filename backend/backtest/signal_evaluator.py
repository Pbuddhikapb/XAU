"""
Directional Signal Evaluator.
Strictly conforms to Section 8 of PROJECT_SPECIFICATION.md:
- Evaluates directional signals over predefined future horizons: 5, 10, 20, 50 candles.
- Evaluates whether favorable movement occurred before adverse movement (MFE vs MAE).
- Keeps directional prediction accuracy separate from simulated trade profitability.
"""

import uuid
from datetime import UTC, datetime

import pandas as pd

from backend.backtest.models import HorizonSignalRecord
from backend.decision.models import DirectionAssessment, DirectionType


class DirectionalSignalEvaluator:
    """Evaluates prediction performance across fixed candle horizons."""

    HORIZONS: list[int] = [5, 10, 20, 50]

    @classmethod
    def evaluate_signal_horizons(
        cls,
        assessment: DirectionAssessment,
        future_candles_1h: pd.DataFrame,
        setup_id: uuid.UUID | None = None,
        atr_threshold_multiplier: float = 1.0,
    ) -> list[HorizonSignalRecord]:
        """
        Evaluate directional accuracy and excursion profiles across 5, 10, 20, and 50 future candles.
        """
        if future_candles_1h.empty:
            return []

        direction_str = (
            assessment.direction.value
            if isinstance(assessment.direction, DirectionType)
            else str(assessment.direction)
        )
        if direction_str == "NEUTRAL":
            return []

        is_long = direction_str in ("BULLISH", "POTENTIAL_BULLISH")
        effective_setup_id = setup_id if setup_id is not None else uuid.uuid4()

        # Entry price is current assessment candle close
        entry_price = float(future_candles_1h["open"].iloc[0])
        if "atr_14" in future_candles_1h.columns and pd.notna(future_candles_1h["atr_14"].iloc[0]):
            atr = float(future_candles_1h["atr_14"].iloc[0])
        else:
            atr = 5.0
        threshold = max(atr * atr_threshold_multiplier, 1.0)

        records: list[HorizonSignalRecord] = []

        for h in cls.HORIZONS:
            if len(future_candles_1h) < h:
                continue

            window = future_candles_1h.iloc[:h]
            eval_time = window["open_time"].iloc[-1]
            if hasattr(eval_time, "to_pydatetime"):
                eval_time = eval_time.to_pydatetime()
            if isinstance(eval_time, datetime) and eval_time.tzinfo is None:
                eval_time = eval_time.replace(tzinfo=UTC)

            # Highs and Lows in window
            highs = window["high"].astype(float).values
            lows = window["low"].astype(float).values
            final_close = float(window["close"].iloc[-1])

            # Calculate MFE & MAE
            if is_long:
                mfe = float(max(highs) - entry_price)
                mae = float(entry_price - min(lows))
                pnl_pct = float((final_close - entry_price) / entry_price * 100.0)
            else:
                mfe = float(entry_price - min(lows))
                mae = float(max(highs) - entry_price)
                pnl_pct = float((entry_price - final_close) / entry_price * 100.0)

            # Determine whether favorable movement occurred before adverse movement
            outcome = "NEUTRAL_RANGE"
            fav_hit_idx: int | None = None
            adv_hit_idx: int | None = None

            for idx in range(h):
                bar_high = highs[idx]
                bar_low = lows[idx]

                if is_long:
                    fav_condition = (bar_high - entry_price) >= threshold
                    adv_condition = (entry_price - bar_low) >= threshold
                else:
                    fav_condition = (entry_price - bar_low) >= threshold
                    adv_condition = (bar_high - entry_price) >= threshold

                if fav_hit_idx is None and fav_condition:
                    fav_hit_idx = idx
                if adv_hit_idx is None and adv_condition:
                    adv_hit_idx = idx

                if fav_hit_idx is not None and adv_hit_idx is not None:
                    break

            if fav_hit_idx is not None and adv_hit_idx is not None:
                if fav_hit_idx < adv_hit_idx:
                    outcome = "FAVORABLE_FIRST"
                elif adv_hit_idx < fav_hit_idx:
                    outcome = "ADVERSE_FIRST"
                else:
                    # Same bar: conservative rule - adverse wins
                    outcome = "ADVERSE_FIRST"
            elif fav_hit_idx is not None:
                outcome = "FAVORABLE_FIRST"
            elif adv_hit_idx is not None:
                outcome = "ADVERSE_FIRST"
            else:
                outcome = "NEUTRAL_RANGE"

            realized_rr = round(pnl_pct / (threshold / entry_price * 100.0), 2) if threshold > 0 else 0.0

            record = HorizonSignalRecord(
                signal_id=uuid.uuid4(),
                setup_id=effective_setup_id,
                symbol=assessment.symbol,
                direction=direction_str,
                assessment_time=assessment.assessment_time,
                horizon_candles=h,
                evaluated_at=eval_time,
                outcome=outcome,
                max_favorable_excursion=round(mfe, 4),
                max_adverse_excursion=round(mae, 4),
                realized_rr=realized_rr,
                pnl_percent=round(pnl_pct, 4),
            )
            records.append(record)

        return records
