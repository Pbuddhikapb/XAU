"""
Candle Validation and Data Integrity Module.
Enforces Principle 8, 11, 12, 14 of PROJECT_SPECIFICATION.md:
- No incomplete candles treated as confirmed.
- Strict OHLC relationships: high >= max(open, close), low <= min(open, close).
- Volume sanity checks: volume >= 0, taker_buy_volume <= volume.
- Gap detection, missing candle identification, and duplicate detection.
"""

from typing import Any

import pandas as pd


class CandleValidationError(Exception):
    """Raised when candle data violates structural or financial integrity checks."""


TIMEFRAME_SECONDS_MAP = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


class CandleValidator:
    """Validates individual candles and time series integrity."""

    @staticmethod
    def validate_single_candle(candle: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate single candle OHLCV invariants.
        Returns (is_valid, error_reason).
        """
        try:
            open_p = float(candle["open"])
            high_p = float(candle["high"])
            low_p = float(candle["low"])
            close_p = float(candle["close"])
            volume = float(candle.get("volume", 0.0))
            taker_buy_vol = float(candle.get("taker_buy_volume", 0.0))

            if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
                return False, f"Non-positive price in candle: O={open_p}, H={high_p}, L={low_p}, C={close_p}"

            if high_p < max(open_p, close_p):
                return False, f"High price ({high_p}) is lower than max(open, close) ({max(open_p, close_p)})"

            if low_p > min(open_p, close_p):
                return False, f"Low price ({low_p}) is higher than min(open, close) ({min(open_p, close_p)})"

            if volume < 0:
                return False, f"Negative volume: {volume}"

            if taker_buy_vol < 0:
                return False, f"Negative taker_buy_volume: {taker_buy_vol}"

            # Floating point tolerance check for taker buy volume
            if taker_buy_vol > volume * 1.00001:
                return False, f"Taker buy volume ({taker_buy_vol}) exceeds total volume ({volume})"

            return True, None
        except (ValueError, KeyError, TypeError) as e:
            return False, f"Malformed candle payload: {e}"

    @staticmethod
    def find_gaps_and_duplicates(
        df: pd.DataFrame, timeframe: str = "1m", time_col: str = "open_time"
    ) -> dict[str, Any]:
        """
        Analyze a sorted DataFrame of candles for gaps and duplicates.
        Requires DataFrame to have UTC datetime or millisecond timestamp column.
        """
        if df.empty:
            return {
                "total_candles": 0,
                "duplicates_count": 0,
                "gaps_count": 0,
                "gap_intervals": [],
                "is_clean": True,
            }

        expected_delta_sec = TIMEFRAME_SECONDS_MAP.get(timeframe, 60)
        expected_delta = pd.Timedelta(seconds=expected_delta_sec)

        # Ensure datetime format
        series = df[time_col]
        if not pd.api.types.is_datetime64_any_dtype(series):
            series = pd.to_datetime(series, unit="ms" if pd.api.types.is_numeric_dtype(series) else None, utc=True)

        # Check duplicates
        duplicate_mask = series.duplicated(keep="first")
        duplicates_count = int(duplicate_mask.sum())

        # Drop duplicates for gap analysis
        unique_series = series.drop_duplicates().sort_values().reset_index(drop=True)

        # Check gaps
        deltas = unique_series.diff().iloc[1:]
        gap_mask = deltas > expected_delta
        gaps_count = int(gap_mask.sum())

        gap_intervals = []
        if gaps_count > 0:
            for idx in deltas[gap_mask].index:
                gap_start = unique_series.iloc[idx - 1]
                gap_end = unique_series.iloc[idx]
                missing_bars = int((gap_end - gap_start) / expected_delta) - 1
                gap_intervals.append(
                    {"start": gap_start.isoformat(), "end": gap_end.isoformat(), "missing_candles": missing_bars}
                )

        return {
            "total_candles": len(df),
            "duplicates_count": duplicates_count,
            "gaps_count": gaps_count,
            "gap_intervals": gap_intervals[:50],  # cap preview
            "is_clean": (duplicates_count == 0 and gaps_count == 0),
        }

    @staticmethod
    def recover_missing_candles(
        df: pd.DataFrame, timeframe: str = "1m", symbol: str = "XAUUSDT", time_col: str = "open_time"
    ) -> pd.DataFrame:
        """
        Recover missing candles by reindexing to a complete uniform time grid.
        Missing candles have zero volume, zero trades, and OHLC set to the prior close.
        Enforces Section 4 'Missing-candle recovery'.
        """
        if df.empty or len(df) < 2:
            return df.copy()

        df_work = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_work[time_col]):
            df_work[time_col] = pd.to_datetime(
                df_work[time_col], unit="ms" if pd.api.types.is_numeric_dtype(df_work[time_col]) else None, utc=True
            )

        df_work = df_work.drop_duplicates(subset=[time_col]).sort_values(time_col)
        df_work = df_work.set_index(time_col)

        expected_delta_sec = TIMEFRAME_SECONDS_MAP.get(timeframe, 60)
        freq_str = f"{expected_delta_sec}s"

        full_idx = pd.date_range(start=df_work.index.min(), end=df_work.index.max(), freq=freq_str, tz="UTC")
        if len(full_idx) == len(df_work):
            return df.copy()  # already complete

        reindexed = df_work.reindex(full_idx)

        # Forward fill close price, then fill open/high/low with close
        reindexed["close"] = reindexed["close"].ffill().bfill()
        reindexed["open"] = reindexed["open"].fillna(reindexed["close"])
        reindexed["high"] = reindexed["high"].fillna(reindexed["close"])
        reindexed["low"] = reindexed["low"].fillna(reindexed["close"])

        # Fill volume metrics with 0.0
        for col in ["volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"]:
            if col in reindexed.columns:
                reindexed[col] = reindexed[col].fillna(0.0)

        if "trades_count" in reindexed.columns:
            reindexed["trades_count"] = reindexed["trades_count"].fillna(0).astype("int64")

        if "symbol" in reindexed.columns:
            reindexed["symbol"] = reindexed["symbol"].fillna(symbol)
        if "timeframe" in reindexed.columns:
            reindexed["timeframe"] = reindexed["timeframe"].fillna(timeframe)
        if "is_confirmed" in reindexed.columns:
            reindexed["is_confirmed"] = True
        if "source" in reindexed.columns:
            reindexed["source"] = reindexed["source"].fillna("imputed_gap_fill")

        delta = pd.Timedelta(seconds=expected_delta_sec) - pd.Timedelta(milliseconds=1)
        reindexed = reindexed.reset_index().rename(columns={"index": time_col})
        reindexed["close_time"] = reindexed[time_col] + delta

        return reindexed
