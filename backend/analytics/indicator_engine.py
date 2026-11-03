"""
Authoritative Indicator Engine for Binance XAUUSDT.
Strictly conforms to Section 5, 7, and 9 of PROJECT_SPECIFICATION.md:
- Orchestrates Trend, Momentum, Volatility, Volume, and VWAP calculations.
- Enforces strict no-lookahead conventions and completed candle requirement.
- Converts calculated indicator series into database-ready IndicatorSnapshot records.
- Shared authoritatively between live engine and historical simulation.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from backend.analytics.momentum import calculate_macd, calculate_rsi
from backend.analytics.trend import calculate_adx_dmi, calculate_trend_emas
from backend.analytics.volatility import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_historical_volatility_percentile,
)
from backend.analytics.volume import calculate_rvol, calculate_taker_buy_ratio
from backend.analytics.vwap import calculate_session_anchored_vwap
from backend.database import get_async_session
from backend.models.tables import IndicatorSnapshot, OHLCVCandle

logger = logging.getLogger(__name__)


class IndicatorEngine:
    """Authoritative Calculation Engine for Technical Indicators."""

    @staticmethod
    def compute_all_indicators(
        df: pd.DataFrame,
        symbol: str = "XAUUSDT",
        timeframe: str = "1h",
        time_col: str = "open_time",
    ) -> pd.DataFrame:
        """
        Compute full matrix of technical indicators on a DataFrame of OHLCV candles.
        Input DataFrame must contain columns: open, high, low, close, volume, taker_buy_volume.
        """
        if df.empty or len(df) < 5:
            return df.copy()

        result = df.copy()

        # Convert open_time to UTC datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(result[time_col]):
            result[time_col] = pd.to_datetime(result[time_col], utc=True)

        close = result["close"].astype(float)
        high = result["high"].astype(float)
        low = result["low"].astype(float)
        volume = result["volume"].astype(float)
        taker_buy_vol = (
            result["taker_buy_volume"].astype(float)
            if "taker_buy_volume" in result.columns
            else pd.Series(0.0, index=result.index)
        )

        # 1. Trend Analysis (EMAs, ADX, Trend Strength)
        emas = calculate_trend_emas(close, periods=(20, 50, 100, 200))
        for name, s in emas.items():
            result[name] = s

        dmi_df = calculate_adx_dmi(high, low, close, period=14)
        result["plus_di"] = dmi_df["plus_di"]
        result["minus_di"] = dmi_df["minus_di"]
        result["adx"] = dmi_df["adx"]
        result["trend_strength"] = (dmi_df["adx"].fillna(20.0) / 50.0).clip(lower=0.0, upper=1.0) * 100.0

        # 2. Momentum Analysis (RSI 14, MACD 12/26/9)
        result["rsi_14"] = calculate_rsi(close, period=14)
        macd_df = calculate_macd(close, 12, 26, 9)
        result["macd_val"] = macd_df["macd"]
        result["macd_signal"] = macd_df["signal"]
        result["macd_hist"] = macd_df["hist"]

        # 3. Volatility Analysis (ATR 14, Bollinger Bands, Percentile)
        atr_s = calculate_atr(high, low, close, period=14)
        result["atr_14"] = atr_s
        bb_df = calculate_bollinger_bands(close, period=20, num_std=2.0)
        result["bb_upper"] = bb_df["upper"]
        result["bb_middle"] = bb_df["middle"]
        result["bb_lower"] = bb_df["lower"]
        result["volatility_percentile"] = calculate_historical_volatility_percentile(atr_s, lookback=100)

        # 4. Volume Analysis (RVOL 20, Taker Buy Ratio)
        result["relative_volume"] = calculate_rvol(volume, period=20)
        result["taker_buy_ratio"] = calculate_taker_buy_ratio(volume, taker_buy_vol)

        # 5. Session-Anchored VWAP (Dynamic NY 18:00 TradFi Gold CME Session Reset)
        vwap_df = calculate_session_anchored_vwap(result, session_reset_hour_utc=None, time_col=time_col)
        result["vwap"] = vwap_df["vwap"]

        return result

    @staticmethod
    def extract_latest_snapshot(
        df_with_indicators: pd.DataFrame,
        symbol: str = "XAUUSDT",
        timeframe: str = "1h",
        time_col: str = "open_time",
    ) -> dict[str, Any] | None:
        """
        Extract the latest completed candle row as an IndicatorSnapshot record.
        """
        if df_with_indicators.empty:
            return None

        last_row = df_with_indicators.iloc[-1]

        def clean_val(val: Any, decimals: int = 4) -> float | None:
            if val is None or pd.isna(val) or np.isnan(val):
                return None
            return round(float(val), decimals)

        candle_time = last_row[time_col]
        if isinstance(candle_time, str):
            c_time = pd.to_datetime(candle_time, utc=True).to_pydatetime()
        elif hasattr(candle_time, "to_pydatetime"):
            c_time = candle_time.to_pydatetime()
        else:
            c_time = datetime.now(UTC)

        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe.lower(),
            "candle_time": c_time,
            "ema_20": clean_val(last_row.get("ema_20")),
            "ema_50": clean_val(last_row.get("ema_50")),
            "ema_100": clean_val(last_row.get("ema_100")),
            "ema_200": clean_val(last_row.get("ema_200")),
            "adx": clean_val(last_row.get("adx")),
            "trend_strength": clean_val(last_row.get("trend_strength")),
            "rsi_14": clean_val(last_row.get("rsi_14")),
            "macd_val": clean_val(last_row.get("macd_val")),
            "macd_signal": clean_val(last_row.get("macd_signal")),
            "macd_hist": clean_val(last_row.get("macd_hist")),
            "atr_14": clean_val(last_row.get("atr_14")),
            "bb_upper": clean_val(last_row.get("bb_upper")),
            "bb_middle": clean_val(last_row.get("bb_middle")),
            "bb_lower": clean_val(last_row.get("bb_lower")),
            "volatility_percentile": clean_val(last_row.get("volatility_percentile")),
            "relative_volume": clean_val(last_row.get("relative_volume")),
            "taker_buy_ratio": clean_val(last_row.get("taker_buy_ratio")),
            "vwap": clean_val(last_row.get("vwap")),
        }

    @staticmethod
    async def persist_indicator_snapshot(snapshot: dict[str, Any]) -> None:
        """Upsert an IndicatorSnapshot into PostgreSQL indicator_snapshots."""
        try:
            stmt = (
                insert(IndicatorSnapshot)
                .values(**snapshot)
                .on_conflict_do_update(
                    index_elements=["symbol", "timeframe", "candle_time"],
                    set_={
                        "ema_20": snapshot["ema_20"],
                        "ema_50": snapshot["ema_50"],
                        "ema_100": snapshot["ema_100"],
                        "ema_200": snapshot["ema_200"],
                        "adx": snapshot["adx"],
                        "trend_strength": snapshot["trend_strength"],
                        "rsi_14": snapshot["rsi_14"],
                        "macd_val": snapshot["macd_val"],
                        "macd_signal": snapshot["macd_signal"],
                        "macd_hist": snapshot["macd_hist"],
                        "atr_14": snapshot["atr_14"],
                        "bb_upper": snapshot["bb_upper"],
                        "bb_middle": snapshot["bb_middle"],
                        "bb_lower": snapshot["bb_lower"],
                        "volatility_percentile": snapshot["volatility_percentile"],
                        "relative_volume": snapshot["relative_volume"],
                        "taker_buy_ratio": snapshot["taker_buy_ratio"],
                        "vwap": snapshot["vwap"],
                    },
                )
            )
            async with get_async_session() as session:
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error("Failed to persist indicator snapshot: %s", e)
            raise

    @staticmethod
    async def process_and_persist_candle_close(
        candle: dict[str, Any],
        symbol: str = "XAUUSDT",
        timeframe: str = "1m",
    ) -> dict[str, Any] | None:
        """
        Real-time pipeline handler triggered upon confirmed candle close.
        1. Loads historical window of confirmed candles from DB.
        2. Combines with current candle.
        3. Computes full indicator matrix.
        4. Extracts and persists IndicatorSnapshot record.
        """
        try:
            async with get_async_session() as session:
                stmt = (
                    select(OHLCVCandle)
                    .where(OHLCVCandle.symbol == symbol.upper(), OHLCVCandle.timeframe == timeframe.lower())
                    .order_by(OHLCVCandle.open_time.desc())
                    .limit(249)
                )
                res = await session.execute(stmt)
                past_candles = list(reversed(res.scalars().all()))

            rows = [
                {
                    "open_time": c.open_time,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                    "taker_buy_volume": float(c.taker_buy_volume),
                }
                for c in past_candles
            ]

            # Append the newly closed candle if not already present
            c_time = candle["open_time"]
            if not rows or rows[-1]["open_time"] != c_time:
                rows.append(
                    {
                        "open_time": c_time,
                        "open": float(candle["open"]),
                        "high": float(candle["high"]),
                        "low": float(candle["low"]),
                        "close": float(candle["close"]),
                        "volume": float(candle["volume"]),
                        "taker_buy_volume": float(candle.get("taker_buy_volume", 0.0)),
                    }
                )

            df = pd.DataFrame(rows)
            if len(df) < 5:
                return None

            computed = IndicatorEngine.compute_all_indicators(df, symbol=symbol, timeframe=timeframe)
            snapshot = IndicatorEngine.extract_latest_snapshot(computed, symbol=symbol, timeframe=timeframe)
            if snapshot:
                await IndicatorEngine.persist_indicator_snapshot(snapshot)
            return snapshot
        except (SQLAlchemyError, ValueError, KeyError, TypeError, OSError) as e:
            logger.error("Error in process_and_persist_candle_close: %s", e)
            return None
