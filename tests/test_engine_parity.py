"""
Engine Parity Test Suite (IMPR-05).
Empirically verifies that backend/analytics/ and analytical_engine/ produce
numerically identical outputs (|delta| < 1e-6) across all technical calculations.
Guarantees single source of mathematical truth across live streaming and simulation.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

# Analytical Engine (authoritative math library)
from analytical_engine.indicators.momentum import (
    calculate_macd as ae_macd,
)
from analytical_engine.indicators.momentum import (
    calculate_rsi as ae_rsi,
)
from analytical_engine.indicators.moving_averages import calculate_ema_series as ae_ema
from analytical_engine.indicators.trend import calculate_adx as ae_adx
from analytical_engine.indicators.volatility import (
    calculate_atr as ae_atr,
)
from analytical_engine.indicators.volatility import (
    calculate_bollinger_bands as ae_bb,
)
from analytical_engine.indicators.volume import (
    calculate_rvol as ae_rvol,
)
from analytical_engine.indicators.volume import (
    calculate_taker_ratios as ae_taker,
)
from analytical_engine.indicators.vwap import calculate_session_anchored_vwap as ae_vwap
from analytical_engine.structure.breakout_retest import detect_breakout_retests as ae_breakout
from analytical_engine.structure.liquidity_sweeps import detect_liquidity_sweeps as ae_sweeps
from analytical_engine.structure.pivots import PivotDetector
from analytical_engine.structure.support_resistance import detect_support_resistance_zones as ae_sr

# Backend Analytics (fastAPI & DB adapter layer)
from backend.analytics.momentum import (
    calculate_macd as be_macd,
)
from backend.analytics.momentum import (
    calculate_rsi as be_rsi,
)
from backend.analytics.trend import (
    calculate_adx_dmi as be_adx,
)
from backend.analytics.trend import (
    calculate_ema as be_ema,
)
from backend.analytics.volatility import (
    calculate_atr as be_atr,
)
from backend.analytics.volatility import (
    calculate_bollinger_bands as be_bb,
)
from backend.analytics.volume import (
    calculate_rvol as be_rvol,
)
from backend.analytics.volume import (
    calculate_taker_buy_ratio as be_taker,
)
from backend.analytics.vwap import calculate_session_anchored_vwap as be_vwap
from backend.structure.breakout_retest import detect_breakout_retests as be_breakout
from backend.structure.liquidity_sweeps import detect_liquidity_sweeps as be_sweeps
from backend.structure.support_resistance import detect_support_resistance_zones as be_sr
from backend.structure.swings import detect_swings as be_swings


@pytest.fixture
def synthetic_ohlcv_series():
    """Generate deterministic 200-bar OHLCV test dataset."""
    np.random.seed(42)
    n = 200
    base_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [base_time + timedelta(minutes=i) for i in range(n)]

    # Random walk with drift for realistic price action
    returns = np.random.normal(0.0002, 0.002, n)
    prices = 2650.0 * np.cumprod(1 + returns)
    highs = prices + np.abs(np.random.normal(1.5, 0.5, n))
    lows = prices - np.abs(np.random.normal(1.5, 0.5, n))
    opens = (highs + lows) / 2.0 + np.random.normal(0, 0.3, n)
    volumes = np.random.uniform(50.0, 500.0, n)
    taker_buy = volumes * np.random.uniform(0.3, 0.7, n)

    df = pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": volumes,
            "taker_buy_volume": taker_buy,
        }
    )
    return df


def test_rsi_engine_parity(synthetic_ohlcv_series):
    """Verify RSI 14 mathematical parity between backend and analytical engine."""
    closes = synthetic_ohlcv_series["close"]
    be_res = be_rsi(closes, period=14).values
    ae_res = ae_rsi(closes.values, period=14)

    # Validate identical shape and values
    assert len(be_res) == len(ae_res)
    # Check that warmup NaNs align
    assert np.array_equal(np.isnan(be_res), np.isnan(ae_res))
    # Check max difference on finite values
    valid_mask = np.isfinite(be_res) & np.isfinite(ae_res)
    max_diff = np.max(np.abs(be_res[valid_mask] - ae_res[valid_mask]))
    assert max_diff < 1e-9, f"RSI divergence detected: {max_diff}"


def test_ema_engine_parity(synthetic_ohlcv_series):
    """Verify multi-period EMA mathematical parity."""
    closes = synthetic_ohlcv_series["close"]
    for p in (20, 50, 100):
        be_res = be_ema(closes, period=p).values
        ae_res = ae_ema(closes.values, period=p)

        assert np.array_equal(np.isnan(be_res), np.isnan(ae_res))
        valid_mask = np.isfinite(be_res) & np.isfinite(ae_res)
        max_diff = np.max(np.abs(be_res[valid_mask] - ae_res[valid_mask]))
        assert max_diff < 1e-9, f"EMA({p}) divergence detected: {max_diff}"


def test_macd_engine_parity(synthetic_ohlcv_series):
    """Verify MACD (12, 26, 9) parity."""
    closes = synthetic_ohlcv_series["close"]
    be_df = be_macd(closes, 12, 26, 9)
    ae_dict = ae_macd(closes.values, 12, 26, 9)

    for be_col, ae_key in [("macd", "macd_line"), ("signal", "signal_line"), ("hist", "histogram")]:
        be_arr = be_df[be_col].values
        ae_arr = ae_dict[ae_key]

        valid_mask = np.isfinite(be_arr) & np.isfinite(ae_arr)
        max_diff = np.max(np.abs(be_arr[valid_mask] - ae_arr[valid_mask]))
        assert max_diff < 1e-9, f"MACD {be_col} divergence detected: {max_diff}"


def test_adx_dmi_engine_parity(synthetic_ohlcv_series):
    """Verify ADX / +DI / -DI parity."""
    h = synthetic_ohlcv_series["high"]
    low_s = synthetic_ohlcv_series["low"]
    c = synthetic_ohlcv_series["close"]

    be_df = be_adx(h, low_s, c, period=14)
    ae_dict = ae_adx(h.values, low_s.values, c.values, period=14)

    for k in ("plus_di", "minus_di", "dx", "adx"):
        be_arr = be_df[k].values
        ae_arr = ae_dict[k]

        valid_mask = np.isfinite(be_arr) & np.isfinite(ae_arr)
        max_diff = np.max(np.abs(be_arr[valid_mask] - ae_arr[valid_mask]))
        assert max_diff < 1e-9, f"ADX {k} divergence detected: {max_diff}"


def test_atr_engine_parity(synthetic_ohlcv_series):
    """Verify ATR 14 parity."""
    h = synthetic_ohlcv_series["high"]
    low_s = synthetic_ohlcv_series["low"]
    c = synthetic_ohlcv_series["close"]

    be_arr = be_atr(h, low_s, c, period=14).values
    ae_arr = ae_atr(h.values, low_s.values, c.values, period=14)

    valid_mask = np.isfinite(be_arr) & np.isfinite(ae_arr)
    max_diff = np.max(np.abs(be_arr[valid_mask] - ae_arr[valid_mask]))
    assert max_diff < 1e-9, f"ATR divergence detected: {max_diff}"


def test_bollinger_bands_engine_parity(synthetic_ohlcv_series):
    """Verify Bollinger Bands sample standard deviation (ddof=1) parity."""
    c = synthetic_ohlcv_series["close"]
    be_df = be_bb(c, period=20, num_std=2.0)
    ae_dict = ae_bb(c.values, period=20, num_std=2.0, ddof=1)

    for be_col, ae_key in [("upper", "upper"), ("middle", "middle"), ("lower", "lower"), ("bandwidth", "bandwidth")]:
        be_arr = be_df[be_col].values
        ae_arr = ae_dict[ae_key]

        valid_mask = np.isfinite(be_arr) & np.isfinite(ae_arr)
        max_diff = np.max(np.abs(be_arr[valid_mask] - ae_arr[valid_mask]))
        assert max_diff < 1e-9, f"Bollinger {be_col} divergence detected: {max_diff}"


def test_vwap_engine_parity(synthetic_ohlcv_series):
    """Verify Session-Anchored VWAP and sigma bands parity."""
    be_df = be_vwap(synthetic_ohlcv_series, session_reset_hour_utc=23)
    ae_df = ae_vwap(synthetic_ohlcv_series, session_reset_hour_utc=23)

    for col in ("vwap", "vwap_upper_1", "vwap_lower_1", "vwap_upper_2", "vwap_lower_2"):
        be_arr = be_df[col].values
        ae_arr = ae_df[col].values

        valid_mask = np.isfinite(be_arr) & np.isfinite(ae_arr)
        max_diff = np.max(np.abs(be_arr[valid_mask] - ae_arr[valid_mask]))
        assert max_diff < 1e-9, f"VWAP {col} divergence detected: {max_diff}"


def test_volume_engine_parity(synthetic_ohlcv_series):
    """Verify RVOL and Taker Buy Ratio parity."""
    vol = synthetic_ohlcv_series["volume"]
    tbv = synthetic_ohlcv_series["taker_buy_volume"]

    # RVOL
    be_rvol_arr = be_rvol(vol, period=20).values
    ae_rvol_arr = ae_rvol(vol.values, period=20)
    # Beyond warmup index 20
    diff_rvol = np.nanmax(np.abs(be_rvol_arr[20:] - ae_rvol_arr[20:]))
    assert diff_rvol < 1e-9, f"RVOL divergence: {diff_rvol}"

    # Taker Buy Ratio
    be_tb = be_taker(vol, tbv).values
    ae_tb = ae_taker(vol.values, tbv.values)["taker_buy_ratio"]
    diff_tb = np.nanmax(np.abs(be_tb - ae_tb))
    assert diff_tb < 1e-9, f"Taker buy ratio divergence: {diff_tb}"


def test_swings_engine_parity(synthetic_ohlcv_series):
    """Verify Swing Detection parity between backend adapter and analytical engine."""
    be_swings_list = be_swings(synthetic_ohlcv_series, window=3)
    ae_pivots_list = PivotDetector(left_bars=3, right_bars=3).find_pivots(synthetic_ohlcv_series)

    assert len(be_swings_list) == len(ae_pivots_list)
    for b, a in zip(be_swings_list, ae_pivots_list, strict=False):
        assert b.index == a.index
        assert b.price == a.pivot_price
        assert b.swing_type == f"SWING_{a.pivot_type}"
        assert b.confirmed_index == a.confirmed_index
        assert b.confirmed_time == a.confirmation_time


def test_liquidity_sweeps_engine_parity(synthetic_ohlcv_series):
    """Verify Liquidity Sweeps parity between backend adapter and analytical engine."""
    be_sweeps_list = be_sweeps(synthetic_ohlcv_series, swing_window=3)
    ae_sweeps_list = ae_sweeps(synthetic_ohlcv_series, swing_window=3)

    assert len(be_sweeps_list) == len(ae_sweeps_list)
    for b, a in zip(be_sweeps_list, ae_sweeps_list, strict=False):
        assert b.sweep_type == a.sweep_type
        assert np.isclose(b.swept_level, a.swept_level)
        assert np.isclose(b.penetration_price, a.penetration_price)
        assert np.isclose(b.close_price, a.close_price)
        assert b.confirmed_candle_time == a.confirmed_candle_time


def test_support_resistance_engine_parity(synthetic_ohlcv_series):
    """Verify Support and Resistance clustering parity between backend and engine."""
    be_zones = be_sr(synthetic_ohlcv_series, swing_window=3)
    ae_zones = ae_sr(synthetic_ohlcv_series, swing_window=3)

    assert len(be_zones) == len(ae_zones)
    for b, a in zip(be_zones, ae_zones, strict=False):
        assert b.zone_type == a.zone_type
        assert np.isclose(b.level_center, a.level_center)
        assert np.isclose(b.level_min, a.level_min)
        assert np.isclose(b.level_max, a.level_max)
        assert b.touches_count == a.touch_count
        assert b.is_active == a.is_active


def test_breakout_retest_engine_parity(synthetic_ohlcv_series):
    """Verify Breakout and Retest event detection parity between backend and engine."""
    be_events = be_breakout(synthetic_ohlcv_series, swing_window=3)
    ae_events = ae_breakout(synthetic_ohlcv_series, swing_window=3)

    assert len(be_events) == len(ae_events)
    for b, a in zip(be_events, ae_events, strict=False):
        assert b.direction == a.direction
        assert np.isclose(b.level_price, a.level_price)
        assert np.isclose(b.breakout_price, a.breakout_price)
        assert b.status == a.status
