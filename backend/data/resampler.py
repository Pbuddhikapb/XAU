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

from backend.data.candle_validator import CandleValidator, TIMEFRAME_SECONDS_MAP

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
    """Resamples canonical 1-minute candles into higher timeframe bars and reconciles against native candles."""

    @staticmethod
    def resample_ohlcv(
        df_1m: pd.DataFrame,
        target_timeframe: str,
        symbol: str = "XAUUSDT",
        only_confirmed: bool = True,
        recover_gaps: bool = False
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

        # Recover missing 1m gaps if requested
        if recover_gaps:
            df = CandleValidator.recover_missing_candles(df, timeframe="1m", symbol=symbol)

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

    @staticmethod
    def reconcile_with_native(
        resampled_df: pd.DataFrame,
        native_df: pd.DataFrame,
        price_tolerance: float = 0.05
    ) -> Dict[str, any]:
        """
        Reconcile synthetic resampled candles against native Binance exchange candles.
        Enforces Section 4 'reconcile against native exchange candles'.
        """
        if resampled_df.empty or native_df.empty:
            return {
                "matched_bars": 0,
                "is_reconciled": False,
                "error": "Empty dataset provided for reconciliation"
            }

        r_df = resampled_df.copy()
        n_df = native_df.copy()

        for d in (r_df, n_df):
            if not pd.api.types.is_datetime64_any_dtype(d["open_time"]):
                d["open_time"] = pd.to_datetime(d["open_time"], utc=True)

        merged = pd.merge(
            r_df, n_df,
            on="open_time",
            suffixes=("_resampled", "_native")
        )

        if merged.empty:
            return {
                "matched_bars": 0,
                "is_reconciled": False,
                "error": "No overlapping timestamps between resampled and native datasets"
            }

        # Compare prices
        open_diff = (merged["open_resampled"] - merged["open_native"]).abs()
        high_diff = (merged["high_resampled"] - merged["high_native"]).abs()
        low_diff = (merged["low_resampled"] - merged["low_native"]).abs()
        close_diff = (merged["close_resampled"] - merged["close_native"]).abs()

        max_price_diff = float(max(
            open_diff.max(), high_diff.max(), low_diff.max(), close_diff.max()
        ))

        price_matches = (
            (open_diff <= price_tolerance) &
            (high_diff <= price_tolerance) &
            (low_diff <= price_tolerance) &
            (close_diff <= price_tolerance)
        )

        match_count = int(price_matches.sum())
        total_matched = len(merged)
        price_match_rate = float(match_count / total_matched)

        # Volume comparison (relative diff)
        vol_r = merged["volume_resampled"]
        vol_n = merged["volume_native"]
        vol_diff_pct = ((vol_r - vol_n).abs() / vol_n.replace(0, 1.0)).max()

        is_reconciled = (price_match_rate >= 0.99) and (max_price_diff <= price_tolerance)

        return {
            "matched_bars": total_matched,
            "perfect_price_matches": match_count,
            "price_match_rate": price_match_rate,
            "max_price_diff": max_price_diff,
            "max_volume_diff_pct": float(vol_diff_pct),
            "is_reconciled": is_reconciled,
        }

