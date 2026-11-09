"""
FastAPI application entrypoint for Binance XAUUSDT Market Intelligence System.
Provides versioned REST endpoints as mandated by Section 10 of PROJECT_SPECIFICATION.md.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analytics.divergence import detect_divergences
from backend.analytics.indicator_engine import IndicatorEngine
from backend.analytics.momentum import evaluate_momentum
from backend.analytics.trend import evaluate_trend_direction_and_strength
from backend.analytics.volatility import evaluate_volatility_regime
from backend.analytics.volume import evaluate_volume_profile
from backend.analytics.vwap import evaluate_vwap_position
from backend.backtest.models import BacktestRunRequest
from backend.backtest.persistence import BacktestPersistence
from backend.backtest.runner import BacktestRunner
from backend.config import settings
from backend.data.session_tracker import SessionTracker
from backend.database import get_db_session, init_db
from backend.decision.orchestrator import DecisionOrchestrator
from backend.logging_config import setup_production_logging
from backend.models.tables import (
    IndicatorSnapshot,
    LiveMarketState,
    MarketMetadata,
    OHLCVCandle,
    StructureEvent,
)
from backend.security import verify_admin_key
from backend.structure.structure_engine import StructureEngine
from backend.structure.support_resistance import detect_support_resistance_zones
from backend.telemetry.websocket_hub import telemetry_hub

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager initializing tables and dependencies."""
    setup_production_logging()
    init_db()
    await telemetry_hub.start_heartbeat(interval_seconds=10.0)
    yield
    await telemetry_hub.stop_heartbeat()


app = FastAPI(
    title="Binance XAUUSDT Market Intelligence System",
    description="Dedicated market intelligence, directional analysis, and trade setup identification.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/system/health")
async def get_system_health(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Retrieve system health status, DB connectivity, and current TradFi session state."""
    db_ok = False
    try:
        res = await session.execute(text("SELECT 1"))
        db_ok = res.scalar() == 1
    except (SQLAlchemyError, OSError) as e:
        logger.warning("Database connectivity check failed: %s", e)
        db_ok = False

    session_state = SessionTracker.get_session_state()

    # Data freshness monitoring (Section 4)
    latest_candle_time = None
    candle_lag_seconds = None
    try:
        ts_res = await session.execute(
            select(func.max(OHLCVCandle.open_time)).where(
                OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == "1m"
            )
        )
        latest_candle_time = ts_res.scalar()
        if latest_candle_time:
            now = datetime.now(UTC)
            candle_lag_seconds = int((now - latest_candle_time).total_seconds())
    except (SQLAlchemyError, OSError) as e:
        logger.warning("Data freshness query failed: %s", e)

    return {
        "status": "HEALTHY" if db_ok else "DEGRADED",
        "symbol": settings.SYMBOL,
        "database_connected": db_ok,
        "tradfi_session_state": session_state.value,
        "underlying_active": SessionTracker.is_underlying_active(),
        "data_freshness": {
            "latest_candle_time": latest_candle_time.isoformat() if latest_candle_time else None,
            "candle_lag_seconds": candle_lag_seconds,
            "is_fresh": candle_lag_seconds is not None and candle_lag_seconds <= 120,
        },
        "server_time_utc": datetime.now(UTC).isoformat(),
        "environment": settings.ENVIRONMENT,
    }


@app.get("/api/v1/market/overview")
async def get_market_overview(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Retrieve contract metadata and latest live market state."""
    # Fetch metadata
    meta_res = await session.execute(select(MarketMetadata).where(MarketMetadata.symbol == settings.SYMBOL))
    meta = meta_res.scalar_one_or_none()

    # Fetch live state
    state_res = await session.execute(select(LiveMarketState).where(LiveMarketState.symbol == settings.SYMBOL))
    state = state_res.scalar_one_or_none()

    if not meta and not state:
        raise HTTPException(
            status_code=404, detail=f"No market data initialized yet for {settings.SYMBOL}. Run verification first."
        )

    live_state_dict = None
    if state:
        live_state_dict = {
            "last_price": float(state.last_price),
            "mark_price": float(state.mark_price),
            "index_price": float(state.index_price),
            "basis": float(state.basis),
            "funding_rate": float(state.funding_rate),
            "next_funding_time": state.next_funding_time.isoformat(),
            "best_bid": float(state.best_bid),
            "best_ask": float(state.best_ask),
            "spread": float(state.spread),
            "tradfi_session_state": state.tradfi_session_state,
            "last_update": state.last_update.isoformat(),
        }
    else:
        c_stmt = (
            select(OHLCVCandle)
            .where(OHLCVCandle.symbol == settings.SYMBOL)
            .order_by(OHLCVCandle.open_time.desc())
            .limit(1)
        )
        c_res = await session.execute(c_stmt)
        latest_c = c_res.scalar_one_or_none()
        if latest_c:
            price = float(latest_c.close)
            live_state_dict = {
                "last_price": price,
                "mark_price": price,
                "index_price": price,
                "basis": 0.0,
                "funding_rate": 0.0001,
                "next_funding_time": datetime.now(UTC).isoformat(),
                "best_bid": round(price - 0.05, 2),
                "best_ask": round(price + 0.05, 2),
                "spread": 0.10,
                "tradfi_session_state": SessionTracker.get_session_state(datetime.now(UTC)),
                "last_update": latest_c.close_time.isoformat(),
            }

    return {
        "symbol": settings.SYMBOL,
        "metadata": {
            "pair": meta.pair if meta else "XAUUSDT",
            "contract_type": meta.contract_type if meta else settings.CONTRACT_TYPE,
            "tick_size": float(meta.tick_size) if meta else 0.01,
            "step_size": float(meta.step_size) if meta else 0.001,
            "min_notional": float(meta.min_notional) if meta else 5.0,
            "is_active": meta.is_active if meta else True,
        }
        if meta
        else None,
        "live_state": live_state_dict,
    }


@app.get("/api/v1/market/candles")
async def get_market_candles(
    timeframe: str = Query("1h", description="Candle timeframe (e.g. 1m, 5m, 15m, 1h, 4h, 1d)"),
    limit: int = Query(250, ge=1, le=1500, description="Number of candles to return"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Retrieve validated historical OHLCV candles."""
    stmt = (
        select(OHLCVCandle)
        .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == timeframe)
        .order_by(OHLCVCandle.open_time.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    candles = result.scalars().all()

    # Return chronological order (oldest to newest)
    candles = list(reversed(candles))

    return [
        {
            "open_time": int(c.open_time.timestamp() * 1000),
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": float(c.volume),
            "quote_volume": float(c.quote_volume),
            "trades_count": int(c.trades_count),
            "taker_buy_volume": float(c.taker_buy_volume),
            "close_time": int(c.close_time.timestamp() * 1000),
            "is_confirmed": c.is_confirmed,
        }
        for c in candles
    ]


@app.get("/api/v1/market/prices")
async def get_market_prices(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Retrieve current contract price, mark price, and index price."""
    stmt = select(LiveMarketState).where(LiveMarketState.symbol == settings.SYMBOL)
    res = await session.execute(stmt)
    state = res.scalar_one_or_none()

    if not state:
        return {
            "symbol": settings.SYMBOL,
            "status": "DATA_UNAVAILABLE",
            "message": "Live market state not initialized",
        }

    return {
        "symbol": settings.SYMBOL,
        "contract_price": float(state.last_price),
        "mark_price": float(state.mark_price),
        "index_price": float(state.index_price),
        "basis": float(state.basis),
        "spread": float(state.spread),
        "last_update": state.last_update.isoformat(),
    }


@app.get("/api/v1/analytics/indicators")
async def get_analytics_indicators(
    timeframe: str = Query("1h", description="Candle timeframe"),
    limit: int = Query(100, ge=1, le=500, description="Number of snapshot records"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Retrieve historical indicator calculation records."""
    stmt = (
        select(IndicatorSnapshot)
        .where(IndicatorSnapshot.symbol == settings.SYMBOL, IndicatorSnapshot.timeframe == timeframe.lower())
        .order_by(IndicatorSnapshot.candle_time.desc())
        .limit(limit)
    )
    res = await session.execute(stmt)
    records = res.scalars().all()

    if records:
        return [
            {
                "candle_time": r.candle_time.isoformat(),
                "timeframe": r.timeframe,
                "ema_20": float(r.ema_20) if r.ema_20 is not None else None,
                "ema_50": float(r.ema_50) if r.ema_50 is not None else None,
                "ema_100": float(r.ema_100) if r.ema_100 is not None else None,
                "ema_200": float(r.ema_200) if r.ema_200 is not None else None,
                "adx": float(r.adx) if r.adx is not None else None,
                "trend_strength": float(r.trend_strength) if r.trend_strength is not None else None,
                "rsi_14": float(r.rsi_14) if r.rsi_14 is not None else None,
                "macd_val": float(r.macd_val) if r.macd_val is not None else None,
                "macd_signal": float(r.macd_signal) if r.macd_signal is not None else None,
                "macd_hist": float(r.macd_hist) if r.macd_hist is not None else None,
                "atr_14": float(r.atr_14) if r.atr_14 is not None else None,
                "bb_upper": float(r.bb_upper) if r.bb_upper is not None else None,
                "bb_middle": float(r.bb_middle) if r.bb_middle is not None else None,
                "bb_lower": float(r.bb_lower) if r.bb_lower is not None else None,
                "volatility_percentile": float(r.volatility_percentile)
                if r.volatility_percentile is not None
                else None,
                "relative_volume": float(r.relative_volume) if r.relative_volume is not None else None,
                "taker_buy_ratio": float(r.taker_buy_ratio) if r.taker_buy_ratio is not None else None,
                "vwap": float(r.vwap) if r.vwap is not None else None,
            }
            for r in reversed(records)
        ]

    # If DB table has not accumulated records yet, compute on recent candles
    c_stmt = (
        select(OHLCVCandle)
        .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == timeframe.lower())
        .order_by(OHLCVCandle.open_time.desc())
        .limit(max(limit + 200, 250))
    )
    c_res = await session.execute(c_stmt)
    candles = list(reversed(c_res.scalars().all()))

    if not candles:
        return []

    df = pd.DataFrame(
        [
            {
                "open_time": c.open_time,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
                "taker_buy_volume": float(c.taker_buy_volume),
            }
            for c in candles
        ]
    )
    computed = IndicatorEngine.compute_all_indicators(df, symbol=settings.SYMBOL, timeframe=timeframe)
    output = []
    for _, row in computed.tail(limit).iterrows():
        snap = IndicatorEngine.extract_latest_snapshot(pd.DataFrame([row]), symbol=settings.SYMBOL, timeframe=timeframe)
        if snap:
            snap["candle_time"] = snap["candle_time"].isoformat()
            output.append(snap)
    return output


@app.get("/api/v1/analytics/divergences")
async def get_analytics_divergences(
    timeframe: str = Query("1h", description="Candle timeframe"),
    indicator: str = Query("RSI", description="Indicator: RSI or MACD_HIST"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Detect active momentum divergences."""
    c_stmt = (
        select(OHLCVCandle)
        .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == timeframe.lower())
        .order_by(OHLCVCandle.open_time.desc())
        .limit(100)
    )
    c_res = await session.execute(c_stmt)
    candles = list(reversed(c_res.scalars().all()))

    if len(candles) < 35:
        return []

    df = pd.DataFrame(
        [
            {
                "open_time": c.open_time,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
                "taker_buy_volume": float(c.taker_buy_volume),
            }
            for c in candles
        ]
    )

    divs = detect_divergences(df, indicator_name=indicator)
    return [d.to_dict() for d in divs]


@app.get("/api/v1/analytics/regime")
async def get_analytics_regime(
    timeframe: str = Query("1h", description="Candle timeframe"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Retrieve consolidated regime analysis (Trend, Momentum, Volatility, Volume, VWAP)."""
    c_stmt = (
        select(OHLCVCandle)
        .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == timeframe.lower())
        .order_by(OHLCVCandle.open_time.desc())
        .limit(250)
    )
    c_res = await session.execute(c_stmt)
    candles = list(reversed(c_res.scalars().all()))

    if len(candles) < 20:
        return {
            "symbol": settings.SYMBOL,
            "timeframe": timeframe,
            "status": "DATA_UNAVAILABLE",
            "message": "Insufficient candle history to calculate market regime",
        }

    df = pd.DataFrame(
        [
            {
                "open_time": c.open_time,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
                "taker_buy_volume": float(c.taker_buy_volume),
            }
            for c in candles
        ]
    )

    trend_eval = evaluate_trend_direction_and_strength(df["close"], df["high"], df["low"])
    momentum_eval = evaluate_momentum(df["close"])
    volatility_eval = evaluate_volatility_regime(df["high"], df["low"], df["close"])
    volume_eval = evaluate_volume_profile(
        df["open"], df["high"], df["low"], df["close"], df["volume"], df["taker_buy_volume"]
    )
    vwap_eval = evaluate_vwap_position(df)

    return {
        "symbol": settings.SYMBOL,
        "timeframe": timeframe,
        "trend": trend_eval,
        "momentum": momentum_eval,
        "volatility": volatility_eval,
        "volume": volume_eval,
        "vwap": vwap_eval,
    }


@app.get("/api/v1/structure/events")
async def get_structure_events(
    timeframe: str = Query("1h", description="Candle timeframe"),
    limit: int = Query(50, ge=1, le=200, description="Number of events"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Retrieve market structure events (BOS, CHoCH, Sweeps)."""
    stmt = (
        select(StructureEvent)
        .where(StructureEvent.symbol == settings.SYMBOL, StructureEvent.timeframe == timeframe.lower())
        .order_by(StructureEvent.confirmed_candle_time.desc())
        .limit(limit)
    )
    res = await session.execute(stmt)
    records = res.scalars().all()

    if records:
        return [
            {
                "event_type": r.event_type,
                "price": float(r.price),
                "invalidated_level": float(r.invalidated_level) if r.invalidated_level is not None else None,
                "event_time": r.event_time.isoformat(),
                "confirmed_candle_time": r.confirmed_candle_time.isoformat(),
                "timeframe": r.timeframe,
                "metadata": r.metadata_json,
            }
            for r in reversed(records)
        ]

    # Compute on the fly if DB does not have events stored yet
    c_stmt = (
        select(OHLCVCandle)
        .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == timeframe.lower())
        .order_by(OHLCVCandle.open_time.desc())
        .limit(100)
    )
    c_res = await session.execute(c_stmt)
    candles = list(reversed(c_res.scalars().all()))

    if len(candles) < 10:
        return []

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
    analysis = StructureEngine.analyze_timeframe(df, timeframe=timeframe)
    return analysis["structure_events"][-limit:]


@app.get("/api/v1/structure/levels")
async def get_structure_levels(
    timeframe: str = Query("1h", description="Candle timeframe"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Retrieve clustered support and resistance reaction zones."""
    c_stmt = (
        select(OHLCVCandle)
        .where(OHLCVCandle.symbol == settings.SYMBOL, OHLCVCandle.timeframe == timeframe.lower())
        .order_by(OHLCVCandle.open_time.desc())
        .limit(150)
    )
    c_res = await session.execute(c_stmt)
    candles = list(reversed(c_res.scalars().all()))

    if len(candles) < 10:
        return []

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
    zones = detect_support_resistance_zones(df)
    return [z.to_dict() for z in zones]


@app.get("/api/v1/structure/mtf")
async def get_structure_mtf() -> dict[str, Any]:
    """Retrieve multi-timeframe alignment across 1D, 4H, 1H, 15M, and 5M."""
    mtf = await StructureEngine.compute_mtf_alignment(symbol=settings.SYMBOL)
    return mtf.to_dict()


# -----------------------------------------------------------------------------
# Phase 4 Engine A: Market Direction & Evidence Endpoints
# -----------------------------------------------------------------------------


@app.get("/api/v1/analysis/current")
async def get_current_analysis(
    symbol: str = Query(default=settings.SYMBOL, description="Trading instrument symbol"),
    max_age_seconds: int = Query(default=60, ge=5, le=3600, description="Max cache age in seconds"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Retrieve current market direction assessment and heuristic evidence scores.
    Conforms strictly to Section 7 & 10 of PROJECT_SPECIFICATION.md:
    - Bullish and bearish scores are independent heuristic scores (0-100), not probabilities.
    - Gated by CME Gold market hours and data quality (> 70).
    - Includes two-tier invalidation rules and methodology version.
    """
    return await DecisionOrchestrator.get_or_compute_latest_analysis(
        session=session, symbol=symbol, max_age_seconds=max_age_seconds
    )


@app.get("/api/v1/analysis/timeframes")
async def get_analysis_timeframes(
    symbol: str = Query(default=settings.SYMBOL, description="Trading instrument symbol"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Retrieve multi-timeframe directional alignment breakdown across primary timeframes."""
    analysis = await DecisionOrchestrator.get_or_compute_latest_analysis(session=session, symbol=symbol)
    return {
        "symbol": symbol.upper(),
        "assessment_time": analysis["assessment_time"],
        "overall_direction": analysis["direction"],
        "timeframe_alignment": analysis["timeframe_alignment"],
        "methodology_version": analysis["methodology_version"],
    }


@app.get("/api/v1/analysis/evidence")
async def get_analysis_evidence(
    symbol: str = Query(default=settings.SYMBOL, description="Trading instrument symbol"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Retrieve structured supporting evidence, contradicting evidence, and invalidation rules."""
    analysis = await DecisionOrchestrator.get_or_compute_latest_analysis(session=session, symbol=symbol)
    return {
        "symbol": symbol.upper(),
        "assessment_time": analysis["assessment_time"],
        "direction": analysis["direction"],
        "bullish_score": analysis["bullish_score"],
        "bearish_score": analysis["bearish_score"],
        "score_label": analysis["score_label"],
        "breakdown": analysis["breakdown"],
        "supporting_evidence": analysis["supporting_evidence"],
        "contradicting_evidence": analysis["contradicting_evidence"],
        "key_levels": analysis["key_levels"],
        "invalidation_conditions": analysis["invalidation_conditions"],
        "data_quality_score": analysis["data_quality_score"],
        "methodology_version": analysis["methodology_version"],
    }


# -----------------------------------------------------------------------------
# Phase 4 Engine B: Trade Setup Identification & Lifecycle Endpoints
# -----------------------------------------------------------------------------


@app.get("/api/v1/setups/current")
async def get_current_setups(
    symbol: str = Query(default=settings.SYMBOL, description="Trading instrument symbol"),
    max_age_minutes: int = Query(default=5, ge=1, le=60, description="Max cache age in minutes"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Retrieve active trade setups (POTENTIAL, CONFIRMED, TRIGGERED).
    If no setups qualify, returns an explicit NO_SETUP response payload explaining why.
    """
    return await DecisionOrchestrator.get_or_compute_current_setups(
        session=session, symbol=symbol, max_age_minutes=max_age_minutes
    )


@app.get("/api/v1/setups/history")
async def get_setups_history(
    symbol: str = Query(default=settings.SYMBOL, description="Trading instrument symbol"),
    direction: str | None = Query(default=None, description="Filter by direction: LONG or SHORT"),
    status: str | None = Query(
        default=None,
        description="Filter by status (POTENTIAL, CONFIRMED, TRIGGERED, TARGET_HIT, STOPPED_OUT, INVALIDATED, EXPIRED)",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max number of historical setups to return"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Retrieve historical trade setups with optional filtering by direction and status.
    """
    return await DecisionOrchestrator.get_setups_history(
        session=session,
        symbol=symbol,
        direction=direction,
        status=status,
        limit=limit,
    )


# -----------------------------------------------------------------------------
# Phase 5: Backtesting & Historical Validation Endpoints
# -----------------------------------------------------------------------------


@app.get("/api/v1/backtests")
async def get_backtests_list(
    symbol: str = Query(default=settings.SYMBOL, description="Trading instrument symbol"),
    limit: int = Query(default=50, ge=1, le=500, description="Max runs to return"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """List historical backtest runs with summary performance metrics."""
    return await BacktestPersistence.get_backtest_runs(session=session, symbol=symbol, limit=limit)


@app.get("/api/v1/backtests/{run_id}")
async def get_backtest_detail(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Retrieve detailed backtest metrics, trade logs, and walk-forward degradation."""
    detail = await BacktestPersistence.get_backtest_run_detail(session=session, run_id=run_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")
    return detail


@app.post("/api/v1/backtests/run")
async def execute_backtest(
    request: BacktestRunRequest,
    session: AsyncSession = Depends(get_db_session),
    _: bool = Depends(verify_admin_key),
) -> dict[str, Any]:
    """Trigger a backtest simulation and persist results into PostgreSQL."""
    return await BacktestRunner.execute_and_persist(request=request, session=session)


@app.get("/api/v1/signals/history")
async def get_signals_history(
    horizon: int | None = Query(default=None, description="Horizon in candles: 5, 10, 20, or 50"),
    outcome: str | None = Query(default=None, description="Outcome filter: FAVORABLE_FIRST, ADVERSE_FIRST, etc."),
    limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Retrieve historical horizon signal outcomes and MFE/MAE excursions."""
    return await BacktestPersistence.get_signals_history(session=session, horizon=horizon, outcome=outcome, limit=limit)


# -----------------------------------------------------------------------------
# Phase 6: Web Dashboard WebSocket & Static Asset Serving
# -----------------------------------------------------------------------------


@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket) -> None:
    """Multiplexed real-time telemetry stream for the web dashboard."""
    await telemetry_hub.register(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await telemetry_hub.unregister(websocket)
    except (RuntimeError, OSError) as e:
        logger.warning(f"WebSocket client error: {e}")
        await telemetry_hub.unregister(websocket)


# Mount static assets if compiled frontend exists (Single-port production serving)
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.exists(frontend_dist):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Fallback to index.html for client-side React SPA routing."""
        file_path = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))



