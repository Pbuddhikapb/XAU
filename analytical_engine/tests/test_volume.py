"""
Tests for Volume indicators: Volume MA, RVOL, Volume Change, and Taker Ratios.
"""

import numpy as np
import pytest

from analytical_engine.indicators.volume import (
    calculate_rvol,
    calculate_taker_ratios,
    calculate_volume_change,
    calculate_volume_ma,
)


def test_volume_ma():
    """Verify volume moving average."""
    vol = [10.0, 20.0, 30.0, 40.0]
    v_ma = calculate_volume_ma(vol, period=2)
    assert np.isnan(v_ma[0])
    assert v_ma[1] == 15.0
    assert v_ma[2] == 25.0
    assert v_ma[3] == 35.0


def test_rvol_excludes_current_bar():
    """Verify RVOL baseline excludes current candle to prevent self-inflation."""
    # 20 bars of volume 100.0, followed by 1 spike of volume 500.0
    vol = [100.0] * 20 + [500.0]
    rvol = calculate_rvol(vol, period=20)

    # At idx 20, the baseline of the preceding 20 bars is exactly 100.0
    # Current volume is 500.0, so RVOL must be exactly 5.0
    assert pytest.approx(rvol[20], 1e-9) == 5.0


def test_volume_change():
    """Verify volume change calculation."""
    vol = [100.0, 150.0, 75.0]
    change = calculate_volume_change(vol, period=1)

    assert np.isnan(change[0])
    assert pytest.approx(change[1], 1e-9) == 50.0
    assert pytest.approx(change[2], 1e-9) == -50.0


def test_taker_ratios_and_imbalance():
    """Verify taker buy/sell ratios and order flow imbalance."""
    vol = [100.0, 200.0, 0.0]
    taker_buy = [70.0, 100.0, 0.0]

    res = calculate_taker_ratios(vol, taker_buy)

    # Bar 0: total 100, buy 70 -> sell 30 -> buy_ratio=0.7, sell_ratio=0.3, imbalance=0.4
    assert pytest.approx(res["taker_buy_ratio"][0], 1e-9) == 0.7
    assert pytest.approx(res["taker_sell_ratio"][0], 1e-9) == 0.3
    assert pytest.approx(res["taker_imbalance"][0], 1e-9) == 0.4

    # Bar 1: total 200, buy 100 -> sell 100 -> imbalance=0.0
    assert pytest.approx(res["taker_imbalance"][1], 1e-9) == 0.0

    # Bar 2: zero volume -> balanced neutral defaults
    assert res["taker_buy_ratio"][2] == 0.5
    assert res["taker_sell_ratio"][2] == 0.5
    assert res["taker_imbalance"][2] == 0.0
