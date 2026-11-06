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
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.config import settings
from backend.data.candle_validator import TIMEFRAME_SECONDS_MAP, CandleValidator

logger = logging.getLogger(__name__)

CME_TIMEZONE = ZoneInfo("America/New_York")

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
    "1d_cme": "1D_CME",
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

        # Check for CME Session Day aggregation (18:00 ET to 17:00 ET)
        if target_timeframe.lower() in ("1d_cme", "cme_1d"):
            return CandleResampler.resample_cme_session_day(
                df_1m, symbol=symbol, only_confirmed=only_confirmed, recover_gaps=recover_gaps
            )

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

    @staticmethod
    def resample_cme_session_day(
        df_1m: pd.DataFrame,
        symbol: str = "XAUUSDT",
        only_confirmed: bool = True,
        recover_gaps: bool = False,
    ) -> pd.DataFrame:
        """
        Resample 1-minute OHLCV candles into CME Session Day (1d_cme) bars:
        - Operating window: 18:00 ET (prior evening) to 17:00 ET (current business day).
        - 23 trading hours = 1,380 constituent 1m bars per full session.
        - Monday session opens Sunday 18:00 ET and closes Monday 17:00 ET.
        - Tuesday through Friday sessions open 18:00 ET the prior day and close 17:00 ET.
        - Excludes weekend closures (Friday 17:00 ET to Sunday 18:00 ET) and daily maintenance (17:00-18:00 ET).
        """
        if not getattr(settings, "ENABLE_CME_SESSION_DAILY_CANDLES", True):
            logger.warning("CME Session Daily candle generation is disabled in settings.")
            return pd.DataFrame()

        if df_1m.empty:
            return pd.DataFrame()

        missing_cols = [c for c in REQUIRED_OHLCV_COLUMNS if c not in df_1m.columns]
        if missing_cols:
            raise ValueError(f"Missing required OHLCV columns for resampling: {missing_cols}")

        df = df_1m.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["open_time"]):
            df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        elif df["open_time"].dt.tz is None:
            df["open_time"] = df["open_time"].dt.tz_localize("UTC")
        else:
            df["open_time"] = df["open_time"].dt.tz_convert("UTC")

        if df["open_time"].duplicated().any():
            df = df.drop_duplicates(subset=["open_time"], keep="last")

        if recover_gaps:
            df = CandleValidator.recover_missing_candles(df, timeframe="1m", symbol=symbol)

        df = df.sort_values("open_time").reset_index(drop=True)

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

        local_times = df["open_time"].dt.tz_convert(CME_TIMEZONE)
        w = local_times.dt.weekday
        h = local_times.dt.hour

        # Filter out weekend closed period and daily settlement break
        is_weekend = ((w == 4) & (h >= 17)) | (w == 5) | ((w == 6) & (h < 18))
        is_daily_break = (w.isin([0, 1, 2, 3])) & (h == 17)
        active_df = df[~(is_weekend | is_daily_break)].copy()
        if active_df.empty:
            return pd.DataFrame()

        act_local = active_df["open_time"].dt.tz_convert(CME_TIMEZONE)
        act_w = act_local.dt.weekday
        act_h = act_local.dt.hour
        act_date = act_local.dt.date

        # Assign session date:
        # Sunday >= 18:00 ET -> Monday session date
        # Mon-Thu >= 18:00 ET -> Next day session date
        # Mon-Fri < 17:00 ET -> Today session date
        next_day = (pd.to_datetime(act_date) + pd.Timedelta(days=1)).dt.date
        is_next = (act_w == 6) | ((act_w < 4) & (act_h >= 18))
        cme_dates = act_date.where(~is_next, next_day)
        active_df["session_date"] = cme_dates

        grouped = active_df.groupby("session_date", sort=True)
        agg_rows = []

        for s_date, group in grouped:
            bars_count = len(group)
            is_confirmed = bars_count >= 1380

            if only_confirmed and not is_confirmed:
                continue

            open_p = float(group["open"].iloc[0])
            close_p = float(group["close"].iloc[-1])
            high_p = float(group["high"].max())
            low_p = float(group["low"].min())
            vol = float(group["volume"].sum())
            q_vol = float(group["quote_volume"].sum()) if "quote_volume" in group.columns else 0.0
            trades = int(group["trades_count"].sum()) if "trades_count" in group.columns else 0
            tb_vol = float(group["taker_buy_volume"].sum()) if "taker_buy_volume" in group.columns else 0.0
            tb_q_vol = (
                float(group["taker_buy_quote_volume"].sum())
                if "taker_buy_quote_volume" in group.columns
                else 0.0
            )

            prev_cal_date = (pd.to_datetime(s_date) - pd.Timedelta(days=1)).date()
            open_dt_local = pd.Timestamp(
                year=prev_cal_date.year,
                month=prev_cal_date.month,
                day=prev_cal_date.day,
                hour=18,
                minute=0,
                second=0,
                tz=CME_TIMEZONE,
            )
            open_time_utc = open_dt_local.tz_convert("UTC")

            close_dt_local = pd.Timestamp(
                year=s_date.year,
                month=s_date.month,
                day=s_date.day,
                hour=16,
                minute=59,
                second=59,
                microsecond=999000,
                tz=CME_TIMEZONE,
            )
            close_time_utc = close_dt_local.tz_convert("UTC")

            agg_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": "1d_cme",
                    "open_time": open_time_utc,
                    "close_time": close_time_utc,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "volume": vol,
                    "quote_volume": q_vol,
                    "trades_count": trades,
                    "taker_buy_volume": tb_vol,
                    "taker_buy_quote_volume": tb_q_vol,
                    "bars_count": bars_count,
                    "is_confirmed": is_confirmed,
                    "session_date": str(s_date),
                }
            )

        if not agg_rows:
            return pd.DataFrame()

        return pd.DataFrame(agg_rows)

    @staticmethod
    def reconcile_cme_vs_binance_1d(
        cme_1d_df: pd.DataFrame,
        native_1d_df: pd.DataFrame,
        price_tolerance: float = 10.0,
    ) -> dict[str, Any]:
        """
        Reconcile synthetic CME Session Day (1d_cme) against Binance Native Daily (1d).
        Quantifies time shifts, constituent coverage, and price/volume variations.
        """
        if cme_1d_df.empty or native_1d_df.empty:
            return {"matched_sessions": 0, "is_reconciled": False, "error": "Empty dataset provided"}

        c_df = cme_1d_df.copy()
        n_df = native_1d_df.copy()

        if "session_date" not in c_df.columns:
            c_df["session_date"] = c_df["close_time"].dt.tz_convert(CME_TIMEZONE).dt.date.astype(str)
        else:
            c_df["session_date"] = c_df["session_date"].astype(str)

        if not pd.api.types.is_datetime64_any_dtype(n_df["open_time"]):
            n_df["open_time"] = pd.to_datetime(n_df["open_time"], utc=True)

        n_df["session_date"] = n_df["open_time"].dt.strftime("%Y-%m-%d")

        merged = pd.merge(c_df, n_df, on="session_date", suffixes=("_cme", "_native"))
        if merged.empty:
            return {"matched_sessions": 0, "is_reconciled": False, "error": "Zero overlapping session dates"}

        open_diffs = (merged["open_cme"] - merged["open_native"]).abs()
        close_diffs = (merged["close_cme"] - merged["close_native"]).abs()
        high_diffs = (merged["high_cme"] - merged["high_native"]).abs()
        low_diffs = (merged["low_cme"] - merged["low_native"]).abs()

        safe_native_vol = np.where(merged["volume_native"] > 0, merged["volume_native"], 1.0)
        vol_ratios = merged["volume_cme"] / safe_native_vol

        documentation = (
            "CME Session Day (1d_cme) vs Binance Native Daily (1d) Structural Discrepancies:\n"
            "1. Boundary Shift: 1d_cme opens at 18:00 America/New_York (22:00 or 23:00 UTC prior day) "
            "and closes at 17:00 America/New_York (21:00 or 22:00 UTC), reflecting traditional Gold CME Globex hours.\n"
            "2. Constituent Bars: Full 1d_cme session spans 23 hours (1,380 active 1m bars), whereas Binance "
            "native 1d spans 24 hours (1,440 1m bars), excluding the 17:00-18:00 ET daily settlement break.\n"
            "3. Sunday Asia Open Allocation: 1d_cme attributes Sunday 18:00 ET opening action to Monday's session, "
            "whereas Binance native 1d includes Sunday 18:00-24:00 UTC in Sunday's UTC calendar bar.\n"
            "4. Weekend & Break Exclusion: 1d_cme excludes Friday 17:00-24:00 UTC and weekend hours where CME physical "
            "gold trading is closed and Binance index price is frozen or in orderbook EWMA mode."
        )

        return {
            "matched_sessions": len(merged),
            "mean_open_diff": float(open_diffs.mean()),
            "max_open_diff": float(open_diffs.max()),
            "mean_close_diff": float(close_diffs.mean()),
            "max_close_diff": float(close_diffs.max()),
            "mean_high_diff": float(high_diffs.mean()),
            "mean_low_diff": float(low_diffs.max()),
            "mean_volume_coverage_ratio": float(vol_ratios.mean()),
            "price_tolerance": price_tolerance,
            "documentation": documentation,
        }
