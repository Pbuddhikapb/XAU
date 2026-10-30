"""
Market Structure Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.E of PROJECT_SPECIFICATION.md:
- Sequence Classification: Higher High (HH), Higher Low (HL), Lower High (LH), Lower Low (LL).
- Break of Structure (BOS): Trend continuation confirmed by candle close.
- Change of Character (CHoCH): Trend reversal signal confirmed by counter-trend candle close.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backend.structure.swings import SwingPoint, detect_swings


@dataclass
class MarketStructureEvent:
    event_type: str  # HH, HL, LH, LL, BOS_BULL, BOS_BEAR, CHOCH_BULL, CHOCH_BEAR
    price: float
    event_time: datetime
    confirmed_candle_time: datetime
    invalidated_level: float | None
    timeframe: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_time"] = self.event_time.isoformat()
        d["confirmed_candle_time"] = self.confirmed_candle_time.isoformat()
        return d


def analyze_market_structure(
    df: pd.DataFrame,
    timeframe: str = "1h",
    swing_window: int = 3,
    time_col: str = "open_time",
) -> tuple[list[MarketStructureEvent], str]:
    """
    Analyze sequential swings to identify HH/HL/LH/LL, BOS, and CHoCH.
    Returns:
        events: Chronological list of MarketStructureEvents
        current_trend: "BULLISH" | "BEARISH" | "NEUTRAL"
    """
    if len(df) < (2 * swing_window) + 2:
        return [], "NEUTRAL"

    swings = detect_swings(df, window=swing_window, time_col=time_col)
    if not swings:
        return [], "NEUTRAL"

    events: list[MarketStructureEvent] = []
    current_trend = "NEUTRAL"

    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None

    # Track candle closes for breakout confirmation
    closes = df["close"].astype(float).to_numpy()
    close_times = df[time_col].tolist()

    for s in swings:
        if s.swing_type == "SWING_HIGH":
            if last_high is not None:
                if s.price > last_high.price:
                    # Higher High
                    events.append(
                        MarketStructureEvent(
                            event_type="HH",
                            price=s.price,
                            event_time=s.time,
                            confirmed_candle_time=s.confirmed_time,
                            invalidated_level=last_high.price,
                            timeframe=timeframe,
                            metadata={"previous_high": last_high.price, "diff": round(s.price - last_high.price, 4)},
                        )
                    )
                else:
                    # Lower High
                    events.append(
                        MarketStructureEvent(
                            event_type="LH",
                            price=s.price,
                            event_time=s.time,
                            confirmed_candle_time=s.confirmed_time,
                            invalidated_level=last_high.price,
                            timeframe=timeframe,
                            metadata={"previous_high": last_high.price, "diff": round(s.price - last_high.price, 4)},
                        )
                    )
            last_high = s

        elif s.swing_type == "SWING_LOW":
            if last_low is not None:
                if s.price > last_low.price:
                    # Higher Low
                    events.append(
                        MarketStructureEvent(
                            event_type="HL",
                            price=s.price,
                            event_time=s.time,
                            confirmed_candle_time=s.confirmed_time,
                            invalidated_level=last_low.price,
                            timeframe=timeframe,
                            metadata={"previous_low": last_low.price, "diff": round(s.price - last_low.price, 4)},
                        )
                    )
                else:
                    # Lower Low
                    events.append(
                        MarketStructureEvent(
                            event_type="LL",
                            price=s.price,
                            event_time=s.time,
                            confirmed_candle_time=s.confirmed_time,
                            invalidated_level=last_low.price,
                            timeframe=timeframe,
                            metadata={"previous_low": last_low.price, "diff": round(s.price - last_low.price, 4)},
                        )
                    )
            last_low = s

    # Evaluate BOS and CHoCH between consecutive confirmed swings
    # Scan through candles chronologically
    confirmed_bull_breaks: set[int] = set()
    confirmed_bear_breaks: set[int] = set()

    for idx in range(len(df)):
        c_p = closes[idx]
        c_time = close_times[idx]
        if hasattr(c_time, "to_pydatetime"):
            c_time = c_time.to_pydatetime()

        # Check for confirmed breaks of swings that were ALREADY CONFIRMED at or before idx
        active_highs = [s for s in swings if s.swing_type == "SWING_HIGH" and s.confirmed_index < idx]
        active_lows = [s for s in swings if s.swing_type == "SWING_LOW" and s.confirmed_index < idx]

        if active_highs:
            latest_high = active_highs[-1]
            if c_p > latest_high.price and latest_high.index not in confirmed_bull_breaks:
                confirmed_bull_breaks.add(latest_high.index)
                # If current trend was BEARISH, this is a Bullish CHoCH (reversal)
                # If current trend was BULLISH or NEUTRAL, this is a Bullish BOS (continuation)
                if current_trend == "BEARISH":
                    event_type = "CHOCH_BULL"
                    current_trend = "BULLISH"
                else:
                    event_type = "BOS_BULL"
                    current_trend = "BULLISH"

                events.append(
                    MarketStructureEvent(
                        event_type=event_type,
                        price=float(c_p),
                        event_time=latest_high.time,
                        confirmed_candle_time=c_time,
                        invalidated_level=latest_high.price,
                        timeframe=timeframe,
                        metadata={
                            "broken_swing_index": latest_high.index,
                            "broken_level": latest_high.price,
                            "breakout_close": float(c_p),
                        },
                    )
                )

        if active_lows:
            latest_low = active_lows[-1]
            if c_p < latest_low.price and latest_low.index not in confirmed_bear_breaks:
                confirmed_bear_breaks.add(latest_low.index)
                # If current trend was BULLISH, this is a Bearish CHoCH (reversal)
                # If current trend was BEARISH or NEUTRAL, this is a Bearish BOS (continuation)
                if current_trend == "BULLISH":
                    event_type = "CHOCH_BEAR"
                    current_trend = "BEARISH"
                else:
                    event_type = "BOS_BEAR"
                    current_trend = "BEARISH"

                events.append(
                    MarketStructureEvent(
                        event_type=event_type,
                        price=float(c_p),
                        event_time=latest_low.time,
                        confirmed_candle_time=c_time,
                        invalidated_level=latest_low.price,
                        timeframe=timeframe,
                        metadata={
                            "broken_swing_index": latest_low.index,
                            "broken_level": latest_low.price,
                            "breakout_close": float(c_p),
                        },
                    )
                )

    # Sort all events chronologically by confirmed_candle_time
    events.sort(key=lambda e: e.confirmed_candle_time)

    # Final trend determination if still NEUTRAL
    if current_trend == "NEUTRAL" and events:
        last_evt = events[-1]
        if last_evt.event_type in ("BOS_BULL", "CHOCH_BULL", "HH", "HL"):
            current_trend = "BULLISH"
        elif last_evt.event_type in ("BOS_BEAR", "CHOCH_BEAR", "LH", "LL"):
            current_trend = "BEARISH"

    return events, current_trend
