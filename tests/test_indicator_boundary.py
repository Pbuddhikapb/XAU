"""
Architectural Boundary Test: Indicator Implementation Isolation.
Enforces the strict rule that all mathematical indicators must be implemented
exclusively within analytical_engine, and that backend/analytics functions must be
thin adapters/delegators with zero duplicate math (no .ewm() or .rolling()).
"""

import ast
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import backend.analytics.divergence as be_divergence
import backend.analytics.momentum as be_momentum
import backend.analytics.trend as be_trend
import backend.analytics.volatility as be_volatility
import backend.analytics.volume as be_volume
import backend.analytics.vwap as be_vwap


def test_no_ewm_or_rolling_in_backend():
    """Fail if any file under backend/ uses pandas .ewm() or .rolling()."""
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    violations = []

    for py_file in backend_dir.rglob("*.py"):
        if py_file.name == "__pycache__":
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".ewm(" in line or ".rolling(" in line:
                violations.append(f"{py_file.relative_to(backend_dir.parent)}:{line_no} -> {stripped}")

    assert not violations, "Found duplicate mathematical operations (.ewm / .rolling) in backend/:\n" + "\n".join(
        violations
    )


def test_indicator_ast_import_verification():
    """Verify via AST that every indicator module in backend/analytics imports from analytical_engine."""
    backend_analytics = Path(__file__).resolve().parent.parent / "backend" / "analytics"
    indicator_files = [
        backend_analytics / "momentum.py",
        backend_analytics / "trend.py",
        backend_analytics / "volatility.py",
        backend_analytics / "volume.py",
        backend_analytics / "vwap.py",
        backend_analytics / "divergence.py",
    ]

    for file_path in indicator_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        imports_ae = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("analytical_engine"):
                imports_ae = True
                break
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("analytical_engine"):
                        imports_ae = True
                        break
        assert imports_ae, f"{file_path.name} does not import from analytical_engine!"


def test_all_backend_indicators_delegate_to_analytical_engine():
    """
    Verify that every indicator calculation in backend/analytics delegates to analytical_engine
    by checking mock invocations on the underlying analytical_engine functions.
    """
    dummy_series = pd.Series([100.0 + i for i in range(50)], dtype=np.float64)
    dummy_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=50, freq="1min", tz="UTC"),
            "open_time": pd.date_range("2026-01-01", periods=50, freq="1min", tz="UTC"),
            "open": dummy_series,
            "high": dummy_series + 1.0,
            "low": dummy_series - 1.0,
            "close": dummy_series,
            "volume": pd.Series([10.0] * 50, dtype=np.float64),
            "taker_buy_volume": pd.Series([5.0] * 50, dtype=np.float64),
        }
    )

    # 1. Momentum: RSI
    with patch("backend.analytics.momentum.ae_rsi", return_value=np.full(50, 50.0)) as mock_rsi:
        be_momentum.calculate_rsi(dummy_series, period=14)
        assert mock_rsi.called, "calculate_rsi did not delegate to analytical_engine!"

    # 2. Momentum: MACD
    with patch(
        "backend.analytics.momentum.ae_macd",
        return_value={"macd_line": np.zeros(50), "signal_line": np.zeros(50), "histogram": np.zeros(50)},
    ) as mock_macd:
        be_momentum.calculate_macd(dummy_series)
        assert mock_macd.called, "calculate_macd did not delegate to analytical_engine!"

    # 3. Momentum: ROC
    with patch("backend.analytics.momentum.ae_roc", return_value=np.zeros(50)) as mock_roc:
        be_momentum.calculate_roc(dummy_series, period=14)
        assert mock_roc.called, "calculate_roc did not delegate to analytical_engine!"

    # 4. Trend: EMA
    with patch("backend.analytics.trend.calculate_ema_series", return_value=np.full(50, 100.0)) as mock_ema:
        be_trend.calculate_ema(dummy_series, period=20)
        assert mock_ema.called, "calculate_ema did not delegate to analytical_engine!"

    # 5. Trend: ADX / DMI
    with patch(
        "backend.analytics.trend.ae_adx",
        return_value={"plus_di": np.zeros(50), "minus_di": np.zeros(50), "dx": np.zeros(50), "adx": np.zeros(50)},
    ) as mock_adx:
        be_trend.calculate_adx_dmi(dummy_df["high"], dummy_df["low"], dummy_df["close"], period=14)
        assert mock_adx.called, "calculate_adx_dmi did not delegate to analytical_engine!"

    # 6. Volatility: ATR
    with patch("backend.analytics.volatility.ae_atr", return_value=np.ones(50)) as mock_atr:
        be_volatility.calculate_atr(dummy_df["high"], dummy_df["low"], dummy_df["close"], period=14)
        assert mock_atr.called, "calculate_atr did not delegate to analytical_engine!"

    # 7. Volatility: Bollinger Bands
    with patch(
        "backend.analytics.volatility.ae_bb",
        return_value={
            "upper": np.ones(50),
            "middle": np.ones(50),
            "lower": np.ones(50),
            "bandwidth": np.ones(50),
            "percent_b": np.ones(50),
        },
    ) as mock_bb:
        be_volatility.calculate_bollinger_bands(dummy_df["close"], period=20)
        assert mock_bb.called, "calculate_bollinger_bands did not delegate to analytical_engine!"

    # 8. Volatility: Historical Percentile
    with patch("backend.analytics.volatility.ae_pct", return_value=np.full(50, 50.0)) as mock_pct:
        be_volatility.calculate_historical_volatility_percentile(dummy_series, lookback=100)
        assert mock_pct.called, "calculate_historical_volatility_percentile did not delegate to analytical_engine!"

    # 9. Volume: RVOL
    with patch("backend.analytics.volume.ae_rvol", return_value=np.ones(50)) as mock_rvol:
        be_volume.calculate_rvol(dummy_df["volume"], period=20)
        assert mock_rvol.called, "calculate_rvol did not delegate to analytical_engine!"

    # 10. Volume: Taker Buy Ratio
    with patch(
        "backend.analytics.volume.ae_taker_ratios",
        return_value={
            "taker_buy_ratio": np.full(50, 0.5),
            "taker_sell_ratio": np.full(50, 0.5),
            "taker_imbalance": np.zeros(50),
        },
    ) as mock_taker:
        be_volume.calculate_taker_buy_ratio(dummy_df["volume"], dummy_df["taker_buy_volume"])
        assert mock_taker.called, "calculate_taker_buy_ratio did not delegate to analytical_engine!"

    # 11. VWAP: Session-anchored VWAP & UTC Daily VWAP (direct re-exports from analytical_engine)
    from analytical_engine.indicators.vwap import (
        calculate_session_anchored_vwap as ae_session_vwap,
    )
    from analytical_engine.indicators.vwap import (
        calculate_utc_daily_vwap as ae_utc_vwap,
    )

    assert be_vwap.calculate_session_anchored_vwap is ae_session_vwap, (
        "backend.analytics.vwap.calculate_session_anchored_vwap is not re-exported from analytical_engine!"
    )
    assert be_vwap.calculate_utc_daily_vwap is ae_utc_vwap, (
        "backend.analytics.vwap.calculate_utc_daily_vwap is not re-exported from analytical_engine!"
    )

    # 13. Divergence: find_swings delegates to PivotDetector
    with patch("backend.analytics.divergence.PivotDetector") as mock_pivot:
        be_divergence.find_swings(dummy_series, window=4)
        assert mock_pivot.called, "find_swings did not delegate to analytical_engine PivotDetector!"
