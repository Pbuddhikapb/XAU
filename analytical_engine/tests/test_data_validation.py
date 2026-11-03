"""
Tests for Data Normalization, Validation, and Continuity.
"""

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from analytical_engine.data.continuity import ContinuityDetector
from analytical_engine.data.normalization import normalize_input_dataframe
from analytical_engine.data.validation import DataValidator


def create_sample_df(n: int = 10, start_epoch: int = 1765440300) -> pd.DataFrame:
    """Helper to generate a clean, valid 1-minute DataFrame."""
    records = []
    base_price = 4200.0
    for i in range(n):
        ts = datetime.fromtimestamp(start_epoch + i * 60, tz=UTC)
        records.append({
            "open_time": ts,
            "open": base_price + i,
            "high": base_price + i + 2.0,
            "low": base_price + i - 1.0,
            "close": base_price + i + 1.0,
            "volume": 100.0 + i * 5.0,
            "close_time": datetime.fromtimestamp(start_epoch + (i + 1) * 60, tz=UTC),
            "quote_volume": 420000.0,
            "trades_count": 50,
            "taker_buy_volume": 60.0,
            "taker_buy_quote_volume": 252000.0,
        })
    return pd.DataFrame(records)


def test_normalization_formats():
    """Test normalization across DataFrame, list of dicts, and tuple inputs."""
    # 1. Dict input
    raw_dicts = [
        {"t": 1765440300000, "o": 4200.0, "h": 4205.0, "l": 4195.0, "c": 4202.0, "v": 50.0},
        {"t": 1765440360000, "o": 4202.0, "h": 4208.0, "l": 4200.0, "c": 4207.0, "v": 60.0},
    ]
    df_norm = normalize_input_dataframe(raw_dicts)
    assert len(df_norm) == 2
    assert "open_time" in df_norm.columns
    assert df_norm["open_time"].iloc[0].tzinfo == UTC
    assert df_norm["open"].dtype == np.float64

    # 2. Tuples
    raw_tuples = [
        (1765440300000, 4200.0, 4205.0, 4195.0, 4202.0, 50.0),
        (1765440360000, 4202.0, 4208.0, 4200.0, 4207.0, 60.0),
    ]
    df_tuples = normalize_input_dataframe(raw_tuples)
    assert len(df_tuples) == 2
    assert df_tuples["close"].iloc[1] == 4207.0


def test_validation_clean_data():
    """Verify that a completely valid dataset returns is_valid=True and no errors."""
    df = create_sample_df(20)
    validator = DataValidator(expected_timeframe="1m")
    report = validator.validate(df)

    assert report.is_valid is True
    assert report.calculations_permitted is True
    assert report.total_rows == 20
    assert report.valid_rows == 20
    assert report.invalid_rows == 0
    assert report.has_errors is False


def test_validation_missing_columns():
    """Verify fatal error when required columns are absent."""
    df = pd.DataFrame({"open_time": [datetime.now(UTC)], "open": [100.0]})
    validator = DataValidator()
    report = validator.validate(df)

    assert report.is_valid is False
    assert report.calculations_permitted is False
    assert any(i.issue_type == "MISSING_COLUMNS" for i in report.issues)


def test_validation_physical_ohlc_violations():
    """Verify detection of invalid OHLC relationships (High < Low, High < Open, Low > Close)."""
    df = create_sample_df(5)
    # Row 1: High < Low
    df.loc[1, "high"] = 4100.0
    df.loc[1, "low"] = 4200.0

    # Row 3: Low > Close
    df.loc[3, "low"] = 4300.0
    df.loc[3, "close"] = 4200.0

    validator = DataValidator()
    report = validator.validate(df)

    assert report.is_valid is False
    assert report.invalid_rows >= 2
    issue_types = [i.issue_type for i in report.issues]
    assert "HIGH_LESS_THAN_LOW" in issue_types
    assert "LOW_NOT_MINIMUM" in issue_types


def test_validation_non_finite_and_negative():
    """Verify detection of NaN, Inf, non-positive price, and negative volume."""
    df = create_sample_df(6)
    df.loc[1, "open"] = np.nan
    df.loc[2, "close"] = -10.0
    df.loc[3, "volume"] = -5.0

    validator = DataValidator()
    report = validator.validate(df)

    assert report.is_valid is False
    issue_types = [i.issue_type for i in report.issues]
    assert "NON_FINITE_VALUE" in issue_types
    assert "NON_POSITIVE_PRICE" in issue_types
    assert "NEGATIVE_VOLUME" in issue_types


def test_validation_duplicates_and_unsorted():
    """Verify detection of duplicate and unsorted timestamps."""
    df = create_sample_df(5)
    # Duplicate timestamp
    df.loc[2, "open_time"] = df.loc[1, "open_time"]

    validator = DataValidator()
    report = validator.validate(df)

    assert report.is_valid is False
    assert report.duplicate_rows >= 2
    assert any(i.issue_type == "DUPLICATE_TIMESTAMP" for i in report.issues)


def test_continuity_detection():
    """Verify that gaps between consecutive candles are properly identified without interpolation."""
    df = create_sample_df(10)
    # Create a 5-minute gap between row 3 and row 4
    # Normal interval: 60s. Here jump 300s
    t3 = df.loc[3, "open_time"]
    for i in range(4, 10):
        df.loc[i, "open_time"] = t3 + pd.Timedelta(seconds=300 + (i - 4) * 60)

    detector = ContinuityDetector(timeframe="1m")
    report = detector.detect_discontinuities(df)

    assert report.total_discontinuities == 1
    assert report.total_missing_candles == 4
    event = report.events[0]
    assert event.missing_intervals == 4
    assert event.duration_seconds == 300.0
