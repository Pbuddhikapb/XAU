"""
Data integrity and quality validator for financial time-series inputs.
Strictly audit OHLCV data without silent repair or data discarding.
"""

import numpy as np
import pandas as pd

from analytical_engine.models.inputs import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


class DataValidator:
    """Performs rigorous mathematical and structural auditing of input time-series."""

    def __init__(self, expected_timeframe: str = "1m"):
        self.expected_timeframe = expected_timeframe

    def validate(self, df: pd.DataFrame) -> ValidationReport:
        """
        Validate input DataFrame across all data integrity rules.
        Returns a comprehensive ValidationReport without mutating or silently modifying data.
        """
        issues: list[ValidationIssue] = []
        total_rows = len(df)

        if total_rows == 0:
            issues.append(
                ValidationIssue(
                    issue_type="EMPTY_DATASET",
                    severity=ValidationSeverity.FATAL,
                    timestamp=None,
                    row_index=None,
                    description="The input DataFrame contains zero rows.",
                )
            )
            return ValidationReport(
                is_valid=False,
                calculations_permitted=False,
                total_rows=0,
                valid_rows=0,
                invalid_rows=0,
                duplicate_rows=0,
                non_monotonic_rows=0,
                issues=issues,
            )

        # 1. Required Columns Check
        required = ["open_time", "open", "high", "low", "close", "volume"]
        missing_cols = [c for c in required if c not in df.columns]
        if missing_cols:
            issues.append(
                ValidationIssue(
                    issue_type="MISSING_COLUMNS",
                    severity=ValidationSeverity.FATAL,
                    timestamp=None,
                    row_index=None,
                    description=f"DataFrame is missing required columns: {missing_cols}",
                )
            )
            return ValidationReport(
                is_valid=False,
                calculations_permitted=False,
                total_rows=total_rows,
                valid_rows=0,
                invalid_rows=total_rows,
                duplicate_rows=0,
                non_monotonic_rows=0,
                issues=issues,
            )

        # 2. Check for Non-Finite values (NaN, Inf) in essential columns
        invalid_mask = pd.Series(False, index=df.index)
        for col in ["open", "high", "low", "close", "volume"]:
            non_finite = ~np.isfinite(df[col])
            if non_finite.any():
                invalid_mask |= non_finite
                bad_indices = df.index[non_finite].tolist()
                for idx in bad_indices[:10]:  # Limit individual issue reporting to top 10
                    ts = df.loc[idx, "open_time"]
                    dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                    issues.append(
                        ValidationIssue(
                            issue_type="NON_FINITE_VALUE",
                            severity=ValidationSeverity.ERROR,
                            timestamp=dt_ts,
                            row_index=idx,
                            description=f"Non-finite value (NaN/Inf) detected in column '{col}' at row {idx}.",
                            details={"column": col, "value": str(df.loc[idx, col])},
                        )
                    )
                if len(bad_indices) > 10:
                    issues.append(
                        ValidationIssue(
                            issue_type="NON_FINITE_VALUE_TRUNCATED",
                            severity=ValidationSeverity.ERROR,
                            timestamp=None,
                            row_index=None,
                            description=f"Total of {len(bad_indices)} non-finite values in column '{col}'.",
                        )
                    )

        # 3. Check for Non-Positive Prices (price <= 0)
        for col in ["open", "high", "low", "close"]:
            non_pos = df[col] <= 0
            if non_pos.any():
                invalid_mask |= non_pos
                bad_indices = df.index[non_pos].tolist()
                for idx in bad_indices[:10]:
                    ts = df.loc[idx, "open_time"]
                    dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                    issues.append(
                        ValidationIssue(
                            issue_type="NON_POSITIVE_PRICE",
                            severity=ValidationSeverity.ERROR,
                            timestamp=dt_ts,
                            row_index=idx,
                            description=f"Non-positive price ({df.loc[idx, col]}) in column '{col}' at row {idx}.",
                        )
                    )

        # 4. Check for Negative Volume (volume < 0)
        neg_vol = df["volume"] < 0
        if neg_vol.any():
            invalid_mask |= neg_vol
            bad_indices = df.index[neg_vol].tolist()
            for idx in bad_indices[:10]:
                ts = df.loc[idx, "open_time"]
                dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                issues.append(
                    ValidationIssue(
                        issue_type="NEGATIVE_VOLUME",
                        severity=ValidationSeverity.ERROR,
                        timestamp=dt_ts,
                        row_index=idx,
                        description=f"Negative volume ({df.loc[idx, 'volume']}) at row {idx}.",
                    )
                )

        # 5. Check OHLC Physical Relationships:
        # High >= Low
        hi_lt_lo = df["high"] < df["low"]
        if hi_lt_lo.any():
            invalid_mask |= hi_lt_lo
            bad_indices = df.index[hi_lt_lo].tolist()
            for idx in bad_indices[:10]:
                ts = df.loc[idx, "open_time"]
                dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                issues.append(
                    ValidationIssue(
                        issue_type="HIGH_LESS_THAN_LOW",
                        severity=ValidationSeverity.ERROR,
                        timestamp=dt_ts,
                        row_index=idx,
                        description=(
                            f"High ({df.loc[idx, 'high']}) is lower than Low ({df.loc[idx, 'low']}) at row {idx}."
                        ),
                    )
                )

        # High >= Open and High >= Close
        hi_lt_open = df["high"] < df["open"]
        hi_lt_close = df["high"] < df["close"]
        hi_invalid = hi_lt_open | hi_lt_close
        if hi_invalid.any():
            invalid_mask |= hi_invalid
            bad_indices = df.index[hi_invalid].tolist()
            for idx in bad_indices[:10]:
                ts = df.loc[idx, "open_time"]
                dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                issues.append(
                    ValidationIssue(
                        issue_type="HIGH_NOT_MAXIMUM",
                        severity=ValidationSeverity.ERROR,
                        timestamp=dt_ts,
                        row_index=idx,
                        description=(
                            f"High ({df.loc[idx, 'high']}) is lower than Open ({df.loc[idx, 'open']}) or "
                            f"Close ({df.loc[idx, 'close']}) at row {idx}."
                        ),
                    )
                )

        # Low <= Open and Low <= Close
        lo_gt_open = df["low"] > df["open"]
        lo_gt_close = df["low"] > df["close"]
        lo_invalid = lo_gt_open | lo_gt_close
        if lo_invalid.any():
            invalid_mask |= lo_invalid
            bad_indices = df.index[lo_invalid].tolist()
            for idx in bad_indices[:10]:
                ts = df.loc[idx, "open_time"]
                dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                issues.append(
                    ValidationIssue(
                        issue_type="LOW_NOT_MINIMUM",
                        severity=ValidationSeverity.ERROR,
                        timestamp=dt_ts,
                        row_index=idx,
                        description=(
                            f"Low ({df.loc[idx, 'low']}) is higher than Open ({df.loc[idx, 'open']}) or "
                            f"Close ({df.loc[idx, 'close']}) at row {idx}."
                        ),
                    )
                )

        # 6. Check for Duplicate Timestamps
        dup_mask = df.duplicated(subset=["open_time"], keep=False)
        duplicate_rows = int(dup_mask.sum())
        if duplicate_rows > 0:
            invalid_mask |= dup_mask
            bad_indices = df.index[dup_mask].tolist()
            for idx in bad_indices[:10]:
                ts = df.loc[idx, "open_time"]
                dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                issues.append(
                    ValidationIssue(
                        issue_type="DUPLICATE_TIMESTAMP",
                        severity=ValidationSeverity.ERROR,
                        timestamp=dt_ts,
                        row_index=idx,
                        description=f"Duplicate open_time '{ts}' detected at row {idx}.",
                    )
                )

        # 7. Check for Chronological Monotonicity (Unsorted timestamps)
        time_diffs = df["open_time"].diff()
        non_monotonic = (time_diffs <= pd.Timedelta(0)) & (time_diffs.notna())
        non_monotonic_rows = int(non_monotonic.sum())
        if non_monotonic_rows > 0:
            bad_indices = df.index[non_monotonic].tolist()
            for idx in bad_indices[:10]:
                ts = df.loc[idx, "open_time"]
                prev_ts = df.loc[idx - 1, "open_time"]
                dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                issues.append(
                    ValidationIssue(
                        issue_type="NON_MONOTONIC_TIMESTAMPS",
                        severity=ValidationSeverity.ERROR,
                        timestamp=dt_ts,
                        row_index=idx,
                        description=f"Timestamp at row {idx} ({ts}) is not strictly after row {idx - 1} ({prev_ts}).",
                    )
                )

        # 8. Check Optional Taker Volumes consistency
        if "taker_buy_volume" in df.columns and "volume" in df.columns:
            taker_exceeds = df["taker_buy_volume"] > (df["volume"] + 1e-6)
            if taker_exceeds.any():
                bad_indices = df.index[taker_exceeds].tolist()
                for idx in bad_indices[:5]:
                    ts = df.loc[idx, "open_time"]
                    dt_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                    issues.append(
                        ValidationIssue(
                            issue_type="TAKER_VOLUME_EXCEEDS_TOTAL",
                            severity=ValidationSeverity.WARNING,
                            timestamp=dt_ts,
                            row_index=idx,
                            description=(
                                f"Taker buy volume ({df.loc[idx, 'taker_buy_volume']}) exceeds "
                                f"total volume ({df.loc[idx, 'volume']}) at row {idx}."
                            ),
                        )
                    )

        invalid_rows = int(invalid_mask.sum())
        valid_rows = total_rows - invalid_rows
        has_fatal_or_error = any(
            i.severity in (ValidationSeverity.FATAL, ValidationSeverity.ERROR)
            for i in issues
        )

        is_valid = not has_fatal_or_error
        # Calculations permitted only if zero fatal or error severity issues exist
        calculations_permitted = is_valid

        return ValidationReport(
            is_valid=is_valid,
            calculations_permitted=calculations_permitted,
            total_rows=total_rows,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            duplicate_rows=duplicate_rows,
            non_monotonic_rows=non_monotonic_rows,
            issues=issues,
        )
