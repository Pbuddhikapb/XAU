"""
Strictly causal multi-timeframe feature alignment engine.
Merges higher-timeframe confirmed indicator features onto lower-timeframe evaluation
timestamps without future leakage, lookahead bias, or unconfirmed candle propagation.
"""

import pandas as pd


class MultiTimeframeAligner:
    """
    Causally aligns higher-timeframe analytical features to a base timeframe time-series.
    Enforces that higher-timeframe data is accessible ONLY after its candle has fully closed.
    """

    def __init__(self, evaluation_point: str = "BAR_CLOSE"):
        """
        Parameters:
            evaluation_point: Either 'BAR_CLOSE' (features aligned when base bar closes)
                              or 'BAR_OPEN' (features aligned at base bar open).
        """
        if evaluation_point not in ("BAR_CLOSE", "BAR_OPEN"):
            raise ValueError(f"Invalid evaluation_point '{evaluation_point}'. Must be 'BAR_CLOSE' or 'BAR_OPEN'.")
        self.evaluation_point = evaluation_point

    def align(
        self,
        base_df: pd.DataFrame,
        htf_data: dict[str, pd.DataFrame],
        feature_prefixes: bool = True,
    ) -> pd.DataFrame:
        """
        Align multiple higher-timeframe DataFrames to base_df.

        Parameters:
            base_df: Canonical DataFrame for the base/target timeframe (e.g., 5m or 15m).
                     Must contain 'open_time' and 'close_time'.
            htf_data: Dictionary mapping timeframe name (e.g., '1h', '4h', '1d')
                      to the corresponding confirmed indicator DataFrame.
                      Each HTF DataFrame MUST contain 'close_time' as the availability boundary.
            feature_prefixes: If True, prefixes HTF column names with '{timeframe}_' to avoid collisions.

        Returns:
            Merged DataFrame preserving all base rows, with HTF features strictly aligned backward.
        """
        if base_df.empty:
            return base_df.copy()

        aligned = base_df.copy()

        # Define the exact evaluation key for the merge
        if self.evaluation_point == "BAR_CLOSE":
            if "close_time" not in aligned.columns:
                raise ValueError("base_df must contain 'close_time' column for BAR_CLOSE alignment.")
            aligned["_asof_key"] = aligned["close_time"]
        else:
            aligned["_asof_key"] = aligned["open_time"]

        # Ensure _asof_key is timezone-aware UTC datetime
        if not pd.api.types.is_datetime64_any_dtype(aligned["_asof_key"]):
            aligned["_asof_key"] = pd.to_datetime(aligned["_asof_key"], utc=True)
        elif aligned["_asof_key"].dt.tz is None:
            aligned["_asof_key"] = aligned["_asof_key"].dt.tz_localize("UTC")

        # Sort base_df by _asof_key for merge_asof
        aligned = aligned.sort_values(by="_asof_key").reset_index(drop=True)

        for tf_name, htf_df in htf_data.items():
            if htf_df.empty:
                continue

            htf = htf_df.copy()
            if "close_time" not in htf.columns:
                raise ValueError(f"HTF DataFrame for '{tf_name}' must contain 'close_time' column.")

            # Ensure htf close_time is UTC datetime
            if not pd.api.types.is_datetime64_any_dtype(htf["close_time"]):
                htf["close_time"] = pd.to_datetime(htf["close_time"], utc=True)
            elif htf["close_time"].dt.tz is None:
                htf["close_time"] = htf["close_time"].dt.tz_localize("UTC")

            # Sort HTF by close_time
            htf = htf.sort_values(by="close_time").reset_index(drop=True)

            # Drop duplicate close_times if any exist in HTF
            htf = htf.drop_duplicates(subset=["close_time"], keep="last")

            # Rename columns to avoid collisions, preserving HTF source_close_time
            prefix = f"{tf_name}_" if feature_prefixes else ""
            htf["_htf_asof_key"] = htf["close_time"]
            cols_to_rename = {}
            for col in htf.columns:
                if col not in ("_htf_asof_key",):
                    cols_to_rename[col] = f"{prefix}source_{col}" if col == "close_time" else f"{prefix}{col}"
            htf = htf.rename(columns=cols_to_rename)

            # Perform strictly backward merge_asof:
            # A higher-timeframe candle is merged if and only if htf._htf_asof_key <= aligned._asof_key.
            aligned = pd.merge_asof(
                aligned,
                htf,
                left_on="_asof_key",
                right_on="_htf_asof_key",
                direction="backward",
            )

            # Drop temporary HTF merge key
            aligned = aligned.drop(columns=["_htf_asof_key"])

        # Drop temporary merge key
        aligned = aligned.drop(columns=["_asof_key"])

        return aligned
