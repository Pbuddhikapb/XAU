"""
Integration and Historical Dataset Validation Tests.
Tests the complete analytical engine against authentic Binance Vision historical data.
"""

import io
import urllib.request
import zipfile

import pandas as pd
import pytest

from analytical_engine.data.continuity import ContinuityDetector
from analytical_engine.data.normalization import normalize_input_dataframe
from analytical_engine.data.validation import DataValidator
from analytical_engine.indicators.momentum import calculate_macd, calculate_rsi
from analytical_engine.indicators.trend import calculate_adx, calculate_ema_ribbon
from analytical_engine.indicators.volatility import calculate_atr, calculate_bollinger_bands
from analytical_engine.indicators.volume import calculate_rvol, calculate_taker_ratios
from analytical_engine.indicators.vwap import calculate_daily_vwap
from analytical_engine.multi_timeframe.aggregation import CandleAggregator
from analytical_engine.structure.divergence import DivergenceDetector
from analytical_engine.structure.pivots import PivotDetector
from analytical_engine.structure.swings import MarketStructureClassifier


@pytest.fixture(scope="module")
def historical_oct29_df():
    """Load authentic 2026-10-29 archive from S3 in memory."""
    url = "https://data.binance.vision/data/futures/um/daily/klines/XAUUSDT/1m/XAUUSDT-1m-2026-10-29.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-IntegrationTest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        z = zipfile.ZipFile(io.BytesIO(resp.read()))
        with z.open(z.namelist()[0]) as f:
            df_raw = pd.read_csv(f, header=None)

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades_count",
        "taker_buy_volume", "taker_buy_quote_volume", "ignore"
    ]
    df_raw.columns = cols[:len(df_raw.columns)]
    return normalize_input_dataframe(df_raw, symbol="XAUUSDT", timeframe="1m")


def test_historical_dataset_pipeline(historical_oct29_df):
    """Verify that all pipeline stages execute cleanly on 1,440 real historical candles."""
    df = historical_oct29_df

    # 1. Validation
    validator = DataValidator(expected_timeframe="1m")
    v_report = validator.validate(df)
    assert v_report.is_valid is True
    assert v_report.calculations_permitted is True
    assert v_report.total_rows == 1440
    assert v_report.valid_rows == 1440
    assert v_report.invalid_rows == 0
    assert v_report.duplicate_rows == 0

    # 2. Continuity
    continuity = ContinuityDetector(timeframe="1m")
    c_report = continuity.detect_discontinuities(df)
    assert c_report.total_discontinuities == 0
    assert c_report.total_missing_candles == 0

    # 3. Indicators
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values
    tb_vol = df["taker_buy_volume"].values

    ribbon = calculate_ema_ribbon(close)
    adx = calculate_adx(high, low, close)
    rsi = calculate_rsi(close)
    macd = calculate_macd(close)
    atr = calculate_atr(high, low, close)
    bb = calculate_bollinger_bands(close)
    rvol = calculate_rvol(vol)
    taker = calculate_taker_ratios(vol, tb_vol)
    vwap = calculate_daily_vwap(df)

    assert len(ribbon["ema_20"]) == 1440
    assert len(adx["adx"]) == 1440
    assert len(rsi) == 1440
    assert len(macd["macd_line"]) == 1440
    assert len(atr) == 1440
    assert len(bb["upper"]) == 1440
    assert len(rvol) == 1440
    assert len(taker["taker_buy_ratio"]) == 1440
    assert len(vwap["vwap"]) == 1440

    # 4. Structure & Divergence
    pivots = PivotDetector(left_bars=3, right_bars=3).find_pivots(df)
    assert len(pivots) > 50

    classifier = MarketStructureClassifier()
    swings = classifier.classify_swings(pivots)
    assert len(swings) > 0

    breaks = classifier.detect_structural_breaks(df, pivots)
    assert len(breaks) > 0

    divs = DivergenceDetector().detect_divergences(df, rsi, indicator_name="RSI", pivots=pivots)
    assert len(divs) > 0

    # 5. Multi-timeframe aggregation
    agg_5m = CandleAggregator("5m").aggregate(df)
    agg_15m = CandleAggregator("15m").aggregate(df)
    agg_1h = CandleAggregator("1h").aggregate(df)

    assert len(agg_5m) == 288
    assert len(agg_15m) == 96
    assert len(agg_1h) == 24
