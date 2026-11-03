"""
Multi-timeframe Resampling Module.
Enforces Section 4 & Section 6 of PROJECT_SPECIFICATION.md and Phase 3 Remediation:
- Generates 5m, 15m, 1h, 4h, 1d higher timeframes from canonical 1m foundation.
- Strict candle boundary alignment (4h boundaries at 00, 04, 08, 12, 16, 20 UTC).
- Discards unfinished/incomplete higher timeframe candles to prevent repainting.
- Strict input column validation and dynamic handling of optional exchange metadata.
- Gaps remain strictly identifiable without synthetic price fabrication.
"""

import logging
from typing import Any

import pandas as pd

from backend.data.candle_validator import TIMEFRAME_SECONDS_MAP, CandleValidator

logger = logging.getLogger(__name__)

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

REQUIRED_OHLCV_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]


class CandleResampler:
    """Resamples canonical 1-minute candles into higher timeframe bars and reconciles against native candles."""

    @staticmethod
    def resample_ohlcv(
        df_1m: pd.DataFrame,
        target_timeframe: str,
        symbol: str = "XAUUSDT",
        only_confirmed: bool = True,
        recover_gaps: bool = False,
    ) -> pd.DataFrame:
        """
        Resample 1-minute OHLCV DataFrame into target timeframe.
        df_1m must contain required columns: open_time, open, high, low, close, volume.
        Optional columns (quote_volume, trades_count, taker_buy_volume, etc.) are handled dynamically.
        """
        if df_1m.empty:
            return pd.DataFrame()

        # 1. Input Column Validation
        missing_cols = [c for c in REQUIRED_OHLCV_COLUMNS if c not in df_1m.columns]
        if missing_cols:
            raise ValueError(f"Missing required OHLCV columns for resampling: {missing_cols}")

        target_offset = PANDAS_OFFSET_MAP.get(target_timeframe)
        if not target_offset:
            raise ValueError(f"Unsupported target timeframe: {target_timeframe}")

        df = df_1m.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["open_time"]):
            df["open_time"] = pd.to_datetime(df["open_time"], utc=True)

        # Detect and clean duplicate timestamps
        if df["open_time"].duplicated().any():
            dup_count = int(df["open_time"].duplicated().sum())
            logger.warning(f"Detected {dup_count} duplicate open_time timestamps during resampling; deduplicating.")
            df = df.drop_duplicates(subset=["open_time"], keep="last")

        # Recover missing 1m gaps if explicitly requested
        if recover_gaps:
            df = CandleValidator.recover_missing_candles(df, timeframe="1m", symbol=symbol)

        df = df.sort_values("open_time").set_index("open_time")

        # Explicit numeric coercion for all numeric fields
        numeric_cols = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades_count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        full_agg_dict = {
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
        agg_dict = {k: v for k, v in full_agg_dict.items() if k in df.columns}

        # Resample on UTC boundaries aligned to epoch
        resampled = df.resample(target_offset, origin="epoch", closed="left", label="left").agg(agg_dict)
        resampled = resampled.dropna(subset=["open", "close"])

        # Calculate expected 1m candle count per target bar
        target_seconds = TIMEFRAME_SECONDS_MAP.get(target_timeframe, 60)
        expected_1m_bars = target_seconds // 60

        # Count 1m bars in each target bar to ensure bar is fully confirmed
        bar_counts = df["close"].resample(target_offset, origin="epoch", closed="left", label="left").count()
        resampled["bars_count"] = bar_counts

        # Determine confirmation status strictly based on full constituent completeness
        resampled["is_confirmed"] = resampled["bars_count"] == expected_1m_bars

        if only_confirmed:
            # Drop any incomplete bars (e.g. current in-progress bar or bars with data gaps)
            resampled = resampled[resampled["is_confirmed"]].copy()

        resampled = resampled.reset_index()
        resampled["symbol"] = symbol
        resampled["timeframe"] = target_timeframe

        # Calculate close_time = open_time + target_seconds - 1 millisecond
        delta = pd.Timedelta(seconds=target_seconds) - pd.Timedelta(milliseconds=1)
        resampled["close_time"] = resampled["open_time"] + delta

        # Reorder columns preserving available fields
        output_cols = [
            "symbol",
            "timeframe",
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades_count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "bars_count",
            "is_confirmed",
        ]
        actual_output_cols = [c for c in output_cols if c in resampled.columns]
        return resampled[actual_output_cols]

    @staticmethod
    def reconcile_with_native(
        resampled_df: pd.DataFrame, native_df: pd.DataFrame, price_tolerance: float = 0.05
    ) -> dict[str, Any]:
        """
        Reconcile synthetic resampled candles against native Binance exchange candles.
        Enforces Section 4 'reconcile against native exchange candles'.
        """
        if resampled_df.empty or native_df.empty:
            return {"matched_bars": 0, "is_reconciled": False, "error": "Empty dataset provided for reconciliation"}

        r_df = resampled_df.copy()
        n_df = native_df.copy()

        if not pd.api.types.is_datetime64_any_dtype(r_df["open_time"]):
            r_df["open_time"] = pd.to_datetime(r_df["open_time"], utc=True)
        if not pd.api.types.is_datetime64_any_dtype(n_df["open_time"]):
            n_df["open_time"] = pd.to_datetime(n_df["open_time"], utc=True)

        merged = pd.merge(r_df, n_df, on="open_time", suffixes=("_resampled", "_native"))
        if merged.empty:
            return {"matched_bars": 0, "is_reconciled": False, "error": "Zero overlapping timestamps"}

        open_diff = (merged["open_resampled"] - merged["open_native"]).abs().max()
        high_diff = (merged["high_resampled"] - merged["high_native"]).abs().max()
        low_diff = (merged["low_resampled"] - merged["low_native"]).abs().max()
        close_diff = (merged["close_resampled"] - merged["close_native"]).abs().max()
        volume_diff = (merged["volume_resampled"] - merged["volume_native"]).abs().max()

        max_price_diff = max(open_diff, high_diff, low_diff, close_diff)
        is_reconciled = bool(max_price_diff <= price_tolerance)

        return {
            "matched_bars": len(merged),
            "is_reconciled": is_reconciled,
            "max_price_diff": float(max_price_diff),
            "max_volume_diff": float(volume_diff),
            "price_tolerance": price_tolerance,
        }
