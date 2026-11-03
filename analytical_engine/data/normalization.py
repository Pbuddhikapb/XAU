"""
Input normalization for time-series market data.
Converts heterogeneous candle inputs into a clean, canonical UTC DataFrame.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = [
    "close_time",
    "quote_volume",
    "trades_count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
]


def normalize_input_dataframe(
    data: pd.DataFrame | Sequence[dict] | Sequence[Sequence[Any]],
    symbol: str = "XAUUSDT",
    timeframe: str = "1m",
) -> pd.DataFrame:
    """
    Standardize market data into canonical pandas DataFrame with validated types and UTC indexing.

    Supported input formats:
    1. pandas.DataFrame with standard column names.
    2. List of dicts with standard keys ('open_time'/'t', 'open'/'o', etc.).
    3. List of tuples/lists: (open_time, open, high, low, close, volume, ...) or
       Binance raw 12-tuple.
    """
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, (list, tuple)):
        if len(data) == 0:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)
        first = data[0]
        if isinstance(first, dict):
            # Dict normalization
            records: list[dict] = []
            for item in data:
                ot = item.get("open_time") or item.get("t") or item.get("timestamp")
                open_val = item.get("open") if "open" in item else item.get("o")
                high_val = item.get("high") if "high" in item else item.get("h")
                low_val = item.get("low") if "low" in item else item.get("l")
                close_val = item.get("close") if "close" in item else item.get("c")
                vol_val = item.get("volume") if "volume" in item else item.get("v", 0.0)
                rec = {
                    "open_time": ot,
                    "open": open_val,
                    "high": high_val,
                    "low": low_val,
                    "close": close_val,
                    "volume": vol_val,
                    "close_time": item.get("close_time") or item.get("T"),
                    "quote_volume": item.get("quote_volume") or item.get("q", 0.0),
                    "trades_count": item.get("trades_count") or item.get("n", 0),
                    "taker_buy_volume": item.get("taker_buy_volume") or item.get("V", 0.0),
                    "taker_buy_quote_volume": item.get("taker_buy_quote_volume") or item.get("Q", 0.0),
                }
                records.append(rec)
            df = pd.DataFrame.from_records(records)
        elif isinstance(first, (list, tuple)):
            # Tuple normalization
            if len(first) >= 11:
                # Standard Binance Kline format
                cols = [
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades_count",
                    "taker_buy_volume", "taker_buy_quote_volume"
                ]
                df = pd.DataFrame([row[:11] for row in data], columns=cols)
            elif len(first) >= 6:
                cols = ["open_time", "open", "high", "low", "close", "volume"]
                df = pd.DataFrame([row[:6] for row in data], columns=cols)
            elif len(first) == 5:
                # (open, high, low, close, volume) without timestamp
                raise ValueError("Candle tuples must include open_time as first element for temporal integrity.")
            else:
                raise ValueError(f"Unrecognized candle sequence with {len(first)} elements.")
        else:
            raise TypeError(f"Unsupported sequence element type: {type(first)}")
    else:
        raise TypeError(f"Unsupported data input type: {type(data)}")

    # Check for presence of required columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Input is missing required columns: {missing_cols}")

    # Strip header row if accidentally passed as data (e.g. string 'open_time')
    if not df.empty and str(df["open_time"].iloc[0]).strip().lower() == "open_time":
        df = df.iloc[1:].reset_index(drop=True)

    # Standardize open_time to UTC Timestamp
    if not pd.api.types.is_datetime64_any_dtype(df["open_time"]):
        num_s = pd.to_numeric(df["open_time"], errors="coerce")
        if num_s.notna().all() and (num_s > 1e8).any():
            max_val = num_s.max()
            unit = "ms" if max_val > 1e11 else "s"
            df["open_time"] = pd.to_datetime(num_s, unit=unit, utc=True)
        else:
            df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    elif df["open_time"].dt.tz is None:
        df["open_time"] = df["open_time"].dt.tz_localize("UTC")
    else:
        df["open_time"] = df["open_time"].dt.tz_convert("UTC")

    # Standardize close_time if present
    if "close_time" in df.columns and df["close_time"].notna().any():
        if not pd.api.types.is_datetime64_any_dtype(df["close_time"]):
            num_close = pd.to_numeric(df["close_time"], errors="coerce")
            if num_close.notna().all() and (num_close > 1e8).any():
                max_val = num_close.max()
                unit = "ms" if max_val > 1e11 else "s"
                df["close_time"] = pd.to_datetime(num_close, unit=unit, utc=True)
            else:
                df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
        elif df["close_time"].dt.tz is None:
            df["close_time"] = df["close_time"].dt.tz_localize("UTC")
        else:
            df["close_time"] = df["close_time"].dt.tz_convert("UTC")

    # Enforce float64 precision for price and volume columns
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)

    for col in ["quote_volume", "taker_buy_volume", "taker_buy_quote_volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)

    if "trades_count" in df.columns:
        df["trades_count"] = pd.to_numeric(df["trades_count"], errors="coerce").fillna(0).astype(np.int64)

    # Sort strictly by open_time ascending
    df = df.sort_values(by="open_time").reset_index(drop=True)

    # Attach symbol and timeframe metadata
    df.attrs["symbol"] = symbol
    df.attrs["timeframe"] = timeframe

    return df
