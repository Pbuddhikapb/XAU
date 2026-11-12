"""
Market Structure Engine for Binance XAUUSDT.
Strictly conforms to Section 5.E, 5.F, 5.G, 5.H, 6, and 9 of PROJECT_SPECIFICATION.md:
- Orchestrates Swings, BOS/CHoCH, Liquidity Sweeps, Price Action, and S/R Zones.
- Enforces strict no-lookahead confirmation and completed candle boundaries.
- Persists structure events into PostgreSQL table structure_events.
- Computes comprehensive Multi-Timeframe (MTF) alignment matrix.
"""

import logging
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from backend.database import get_async_session
from backend.models.tables import OHLCVCandle, StructureEvent
from backend.structure.liquidity_sweeps import LiquiditySweepEvent, detect_liquidity_sweeps
from backend.structure.market_structure import MarketStructureEvent, analyze_market_structure
from backend.structure.mtf_manager import MTFAlignmentResult, MTFManager
from backend.structure.price_action import detect_price_action_patterns
from backend.structure.support_resistance import detect_support_resistance_zones

logger = logging.getLogger(__name__)


class StructureEngine:
    """Authoritative Engine for Market Structure and Multi-Timeframe Intelligence."""

    @staticmethod
    def analyze_timeframe(
        df: pd.DataFrame,
        timeframe: str = "1h",
        swing_window: int = 3,
        time_col: str = "open_time",
        include_auxiliary: bool = True,
    ) -> dict[str, Any]:
        """
        Run complete structural and price action analysis on a single timeframe's candles.
        """
        if df.empty or len(df) < 5:
            return {
                "timeframe": timeframe,
                "current_trend": "NEUTRAL",
                "structure_events": [],
                "liquidity_sweeps": [],
                "price_action_patterns": [],
                "sr_zones": [],
            }

        # 1. Market structure events (HH, HL, LH, LL, BOS, CHoCH)
        struct_events, trend = analyze_market_structure(
            df, timeframe=timeframe, swing_window=swing_window, time_col=time_col
        )

        if include_auxiliary:
            # 2. Liquidity sweeps (false breakouts / stop runs)
            sweeps = detect_liquidity_sweeps(df, timeframe=timeframe, swing_window=swing_window, time_col=time_col)

            # 3. Price action patterns (rejection wicks, engulfing)
            patterns = detect_price_action_patterns(df, time_col=time_col)

            # 4. Support and Resistance zones
            zones = detect_support_resistance_zones(df, swing_window=swing_window, time_col=time_col)
        else:
            sweeps = []
            patterns = []
            zones = []

        return {
            "timeframe": timeframe,
            "current_trend": trend,
            "structure_events": [e.to_dict() for e in struct_events],
            "liquidity_sweeps": [s.to_dict() for s in sweeps],
            "price_action_patterns": [p.to_dict() for p in patterns],
            "sr_zones": [z.to_dict() for z in zones],
        }

    @staticmethod
    async def persist_structure_events(
        events: list[MarketStructureEvent | LiquiditySweepEvent],
        symbol: str = "XAUUSDT",
    ) -> int:
        """
        Persist detected market structure and sweep events into PostgreSQL structure_events.
        Returns the number of persisted events.
        """
        if not events:
            return 0

        persisted = 0
        try:
            async with get_async_session() as session:
                for ev in events:
                    if isinstance(ev, MarketStructureEvent):
                        evt_type = ev.event_type
                        price = ev.price
                        inval = ev.invalidated_level
                        evt_time = ev.event_time
                        conf_time = ev.confirmed_candle_time
                        tf = ev.timeframe
                        meta = ev.metadata
                    else:
                        evt_type = ev.sweep_type
                        price = ev.penetration_price
                        inval = ev.swept_level
                        evt_time = ev.event_time
                        conf_time = ev.confirmed_candle_time
                        tf = ev.timeframe
                        meta = {"swept_level": ev.swept_level, "sweep_distance": ev.sweep_distance}

                    stmt = insert(StructureEvent).values(
                        symbol=symbol.upper(),
                        timeframe=tf.lower(),
                        event_time=evt_time,
                        event_type=evt_type,
                        price=price,
                        invalidated_level=inval,
                        confirmed_candle_time=conf_time,
                        metadata_json=meta,
                    )
                    await session.execute(stmt)
                    persisted += 1

                await session.commit()
        except (SQLAlchemyError, ValueError, KeyError, TypeError, OSError) as e:
            logger.error("Failed to persist structure events: %s", e)

        return persisted

    @staticmethod
    async def compute_mtf_alignment(symbol: str = "XAUUSDT") -> MTFAlignmentResult:
        """
        Load recent candles from database for 1D, 4H, 1H, 15M, and 5M,
        analyze structure and trend on each, and evaluate MTF alignment.
        """
        timeframes = ["1d", "4h", "1h", "15m", "5m"]
        tf_states: dict[str, dict[str, Any]] = {}

        try:
            async with get_async_session() as session:
                for tf in timeframes:
                    stmt = (
                        select(OHLCVCandle)
                        .where(OHLCVCandle.symbol == symbol.upper(), OHLCVCandle.timeframe == tf)
                        .order_by(OHLCVCandle.open_time.desc())
                        .limit(150)
                    )
                    res = await session.execute(stmt)
                    candles = list(reversed(res.scalars().all()))

                    if len(candles) >= 10:
                        df = pd.DataFrame(
                            [
                                {
                                    "open_time": c.open_time,
                                    "open": float(c.open),
                                    "high": float(c.high),
                                    "low": float(c.low),
                                    "close": float(c.close),
                                    "volume": float(c.volume),
                                }
                                for c in candles
                            ]
                        )
                        analysis = StructureEngine.analyze_timeframe(df, timeframe=tf)
                        trend = analysis["current_trend"]
                        struct_events = analysis["structure_events"]
                        last_struct = struct_events[-1]["event_type"] if struct_events else "CHOP"
                        tf_states[tf] = {
                            "direction": trend,
                            "strength": 70.0 if trend in ("BULLISH", "BEARISH") else 20.0,
                            "structure": last_struct,
                        }
                    else:
                        tf_states[tf] = {"direction": "NEUTRAL", "strength": 0.0, "structure": "CHOP"}
        except (SQLAlchemyError, ValueError, KeyError, TypeError, OSError) as e:
            logger.error("Failed to query candles for MTF alignment: %s", e)
            for tf in timeframes:
                if tf not in tf_states:
                    tf_states[tf] = {"direction": "NEUTRAL", "strength": 0.0, "structure": "CHOP"}

        return MTFManager.evaluate_alignment(tf_states)
