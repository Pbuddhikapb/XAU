"""
Multi-timeframe candle aggregation engine.
Aggregates 1-minute foundational bars into 5M, 15M, 1H, 4H, and 1D bars with
strict UTC boundary alignment and constituent completeness verification.
"""

from datetime import UTC, datetime

import pandas as pd

from analytical_engine.data.timeframe import (
    get_expected_1m_count,
    get_timeframe_seconds,
)


class CandleAggregator:
    """Aggregates validated 1-minute OHLCV candles into higher timeframe bars."""

    def __init__(self, target_timeframe: str, require_full_bars: bool = True):
        self.target_timeframe = target_timeframe.lower()
        self.interval_seconds = get_timeframe_seconds(self.target_timeframe)
        self.expected_count = get_expected_1m_count(self.target_timeframe)
        self.require_full_bars = require_full_bars

    def aggregate(self, df_1m: pd.DataFrame, current_time: datetime | None = None) -> pd.DataFrame:
        """
        Aggregate a validated 1m DataFrame into target_timeframe candles.

        Parameters:
            df_1m: Validated 1m DataFrame with UTC open_time, open, high, low, close, volume.
            current_time: Optional evaluation timestamp to determine if a bar has fully elapsed.
                          If None, uses the last 1m bar's timestamp.

        Returns:
            DataFrame of aggregated candles with audit columns:
            constituent_count, expected_count, is_complete, is_confirmed.
        """
        if df_1m.empty:
            return pd.DataFrame(
                columns=[
                    "open_time", "close_time", "open", "high", "low", "close", "volume",
                    "quote_volume", "trades_count", "taker_buy_volume", "taker_buy_quote_volume",
                    "constituent_count", "expected_count", "is_complete", "is_confirmed"
                ]
            )

        symbol = df_1m.attrs.get("symbol", "XAUUSDT")
        df = df_1m.copy()

        # Compute UTC-aligned target bar start timestamp for each 1m candle
        open_times = pd.to_datetime(df["open_time"])
        if open_times.dt.tz is None:
            open_times = open_times.dt.tz_localize("UTC")
        else:
            open_times = open_times.dt.tz_convert("UTC")

        # Floor epoch seconds by interval_seconds
        epoch_secs = open_times.astype("int64") // 10**9
        floored_secs = (epoch_secs // self.interval_seconds) * self.interval_seconds
        df["bar_open_time"] = pd.to_datetime(floored_secs, unit="s", utc=True)

        # Prepare aggregation rules
        agg_rules = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }

        # Include optional additive columns if present
        if "quote_volume" in df.columns:
            agg_rules["quote_volume"] = "sum"
        if "trades_count" in df.columns:
            agg_rules["trades_count"] = "sum"
        if "taker_buy_volume" in df.columns:
            agg_rules["taker_buy_volume"] = "sum"
        if "taker_buy_quote_volume" in df.columns:
            agg_rules["taker_buy_quote_volume"] = "sum"

        grouped = df.groupby("bar_open_time")
        agg_df = grouped.agg(agg_rules).reset_index()
        counts = grouped["open_time"].count().values
        agg_df["constituent_count"] = counts
        agg_df["expected_count"] = self.expected_count

        # Compute close_time (open_time + interval_seconds)
        agg_open_epoch = agg_df["bar_open_time"].astype("int64") // 10**9
        agg_close_epoch = agg_open_epoch + self.interval_seconds
        agg_df["close_time"] = pd.to_datetime(agg_close_epoch, unit="s", utc=True)
        agg_df.rename(columns={"bar_open_time": "open_time"}, inplace=True)

        # Completeness check: exactly expected_count 1m constituent bars
        agg_df["is_complete"] = agg_df["constituent_count"] == self.expected_count

        # Confirmation check:
        # A candle is confirmed if:
        # 1. Its full time interval has elapsed (close_time <= latest available 1m close or current_time).
        # 2. It meets completeness requirements (if require_full_bars is True, must have all constituent bars).
        latest_time = current_time or open_times.max().to_pydatetime()
        if latest_time.tzinfo is None:
            latest_time = latest_time.replace(tzinfo=UTC)

        # Time elapsed check: close_time <= latest_time (or latest 1m timestamp + 60s)
        time_elapsed = agg_df["close_time"] <= (open_times.max() + pd.Timedelta(seconds=60))
        if self.require_full_bars:
            agg_df["is_confirmed"] = agg_df["is_complete"] & time_elapsed
        else:
            agg_df["is_confirmed"] = time_elapsed

        # Filter out incomplete bars if require_full_bars is True
        if self.require_full_bars:
            agg_df = agg_df[agg_df["is_complete"]].reset_index(drop=True)

        agg_df.attrs["symbol"] = symbol
        agg_df.attrs["timeframe"] = self.target_timeframe

        return agg_df
