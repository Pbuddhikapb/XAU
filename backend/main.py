"""
FastAPI application entrypoint for Binance XAUUSDT Market Intelligence System.
Provides versioned REST endpoints as mandated by Section 10 of PROJECT_SPECIFICATION.md.
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.data.session_tracker import SessionTracker
from backend.database import get_db_session, init_db
from backend.models.tables import (
    LiveMarketState,
    MarketMetadata,
    OHLCVCandle,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager initializing tables and dependencies."""
    init_db()
    yield


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
        "live_state": {
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
        if state
        else None,
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
