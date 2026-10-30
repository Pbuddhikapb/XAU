"""
Multi-timeframe Resampling Module.
Enforces Section 4 & Section 6 of PROJECT_SPECIFICATION.md:
- Generates 5m, 15m, 1h, 4h, 1d higher timeframes from canonical 1m foundation.
- Strict candle boundary alignment (4h boundaries at 00, 04, 08, 12, 16, 20 UTC).
- Discards unfinished/incomplete higher timeframe candles to prevent repainting.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd

from backend.data.candle_validator import TIMEFRAME_SECONDS_MAP

PANDAS_OFFSET_MAP = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1D",
}


class CandleResampler:
    """Resamples canonical 1-minute candles into higher timeframe bars."""

    @staticmethod
    def resample_ohlcv(
        df_1m: pd.DataFrame,
        target_timeframe: str,
        symbol: str = "XAUUSDT",
        only_confirmed: bool = True
    ) -> pd.DataFrame:
        """
        Resample 1-minute OHLCV DataFrame into target timeframe.
        df_1m must have: open_time, open, high, low, close, volume, quote_volume,
        trades_count, taker_buy_volume, taker_buy_quote_volume.
        """
        if df_1m.empty:
            return pd.DataFrame()

        target_offset = PANDAS_OFFSET_MAP.get(target_timeframe)
        if not target_offset:
            raise ValueError(f"Unsupported target timeframe: {target_timeframe}")

        df = df_1m.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["open_time"]):
            df["open_time"] = pd.to_datetime(df["open_time"], utc=True)

        df = df.sort_values("open_time").set_index("open_time")

        # Explicit numeric conversion
        numeric_cols = [
            "open", "high", "low", "close", "volume",
            "quote_volume", "trades_count", "taker_buy_volume", "taker_buy_quote_volume"
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "quote_volume": "sum",
            "trades_count": "sum",
            "taker_buy_volume": "sum",
            "taker_buy_quote_volume": "sum",
        }

        # Resample on UTC boundaries
        resampled = df.resample(target_offset, origin="epoch", closed="left", label="left").agg(agg_dict)
        resampled = resampled.dropna(subset=["open", "close"])

        # Calculate expected 1m candle count per target bar
        target_seconds = TIMEFRAME_SECONDS_MAP.get(target_timeframe, 60)
        expected_1m_bars = target_seconds // 60

        # Count 1m bars in each target bar to ensure bar is fully confirmed
        bar_counts = df["close"].resample(target_offset, origin="epoch", closed="left", label="left").count()
        resampled["bars_count"] = bar_counts

        if only_confirmed:
            # Drop any incomplete bars (e.g. current in-progress bar or partial bars)
            resampled = resampled[resampled["bars_count"] == expected_1m_bars].copy()

        resampled = resampled.reset_index()
        resampled["symbol"] = symbol
        resampled["timeframe"] = target_timeframe
        resampled["is_confirmed"] = True

        # Calculate close_time = open_time + target_seconds - 1 millisecond
        delta = pd.Timedelta(seconds=target_seconds) - pd.Timedelta(milliseconds=1)
        resampled["close_time"] = resampled["open_time"] + delta

        # Reorder columns
        output_cols = [
            "symbol", "timeframe", "open_time", "close_time",
            "open", "high", "low", "close", "volume",
            "quote_volume", "trades_count", "taker_buy_volume",
            "taker_buy_quote_volume", "is_confirmed"
        ]
        return resampled[output_cols]
