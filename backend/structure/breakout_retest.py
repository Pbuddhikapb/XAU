"""
Breakout and Retest Analytical Event Detection Module for Binance XAUUSDT.
Strictly conforms to Section 5.E & 5.G of PROJECT_SPECIFICATION.md and Phase 3 Remediation:
- Detects structural breakouts confirmed by candle close beyond confirmed swing levels.
- Tracks subsequent retests of broken levels within a defined causal lookback window.
- Classifies retest outcomes:
    * SUCCESSFUL: Price retests the broken level and rejects it in the breakout direction.
    * FAILED: Price closes back inside the prior range, invalidating the breakout.
    * PENDING: Breakout confirmed, awaiting retest within the validity window.
    * EXPIRED: Validity window elapsed without a retest touch.
- Enforces strict no-lookahead: does not confirm a retest before the confirming candle closes.
- Delegates to authoritative analytical_engine.structure.breakout_retest.
- Pure analytical event detection — does NOT generate trade setups, entry/exit orders, or R:R scores.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from analytical_engine.structure.breakout_retest import (
    detect_breakout_retests as ae_detect_breakout,
)


@dataclass(frozen=True)
class BreakoutRetestEvent:
    direction: str  # "BULLISH" | "BEARISH"
    level_price: float
    level_time: datetime
    breakout_time: datetime
    breakout_price: float
    retest_time: datetime | None
    retest_price: float | None
    confirmed_time: datetime
    status: str  # "SUCCESSFUL" | "FAILED" | "PENDING" | "EXPIRED"
    timeframe: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["level_time"] = self.level_time.isoformat()
        d["breakout_time"] = self.breakout_time.isoformat()
        d["retest_time"] = self.retest_time.isoformat() if self.retest_time else None
        d["confirmed_time"] = self.confirmed_time.isoformat()
        return d


def detect_breakout_retests(
    df: pd.DataFrame,
    timeframe: str = "1h",
    swing_window: int = 3,
    max_retest_bars: int = 20,
    retest_tolerance_pct: float = 0.0015,  # 0.15% zone tolerance (~$3.75 on $2500 gold)
    time_col: str = "open_time",
    close_time_col: str = "close_time",
) -> list[BreakoutRetestEvent]:
    """
    Detect causal breakout and retest events from confirmed swings.
    Delegates to analytical_engine.structure.breakout_retest.
    """
    records = ae_detect_breakout(
        df=df,
        timeframe=timeframe,
        swing_window=swing_window,
        max_retest_bars=max_retest_bars,
        retest_tolerance_pct=retest_tolerance_pct,
        time_col=time_col,
        close_time_col=close_time_col,
    )

    events: list[BreakoutRetestEvent] = []
    for r in records:
        events.append(
            BreakoutRetestEvent(
                direction=r.direction,
                level_price=r.level_price,
                level_time=r.level_pivot_time,
                breakout_time=r.breakout_time,
                breakout_price=r.breakout_price,
                retest_time=r.retest_time,
                retest_price=r.retest_price,
                confirmed_time=r.confirmed_time if r.confirmed_time else r.breakout_time,
                status=r.status,
                timeframe=r.timeframe,
                details=r.details,
            )
        )
    return events
