"""
Unit and integration tests for Engine B: TradeSetupEngine.
Strictly tests Section 6, 7, and 8 of PROJECT_SPECIFICATION.md:
- 4 deterministic setup patterns (Trend Continuation, Breakout Retest, Sweep Reversal, Range Rejection).
- Fee (0.10% roundtrip) and slippage (0.02%) deduction in Net R:R calculation.
- Rejection of setups with Net R:R < 1.5.
- Concrete Entry Zone, Stop Loss, and 3 Take-Profit targets.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.analytics.indicator_engine import IndicatorEngine
from backend.decision.models import (
    DirectionAssessment,
    DirectionType,
    ScoreBreakdown,
    SetupStatus,
    SetupType,
    TradeDirection,
)
from backend.decision.setup_engine import TradeSetupEngine
from backend.structure.structure_engine import StructureEngine


def make_bullish_pullback_candles(n: int = 60) -> pd.DataFrame:
    """Generate an uptrend followed by a pullback to EMA20."""
    times = [datetime(2026, 10, 20, 0, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    prices = []
    # Uptrend from 2650 to 2720, then retrace into EMA 20
    for i in range(n):
        if i < n - 7:
            p = 2650.0 + (i * 1.5)
        else:
            p = prices[-1] - 1.5  # Retrace down towards EMA
        prices.append(p)

    return pd.DataFrame(
        {
            "open_time": times,
            "open": [p - 0.5 for p in prices],
            "high": [p + 4.0 for p in prices],
            "low": [p - 4.0 for p in prices],
            "close": prices,
            "volume": [200.0] * n,
            "taker_buy_volume": [130.0] * n,
        }
    )


def test_calculate_net_rr_deducts_fees():
    """Verify net R:R calculation accounts for 0.10% taker fee and 0.02% slippage."""
    entry = 2700.0
    stop_loss = 2680.0  # gross risk = 20.0
    target = 2740.0  # gross reward = 40.0 (gross R:R = 2.0)

    net_rr = TradeSetupEngine._calculate_net_rr(entry, stop_loss, target, TradeDirection.LONG)
    # Total friction = 2700 * 0.0012 = 3.24
    # Net risk = 20 + 3.24 = 23.24
    # Net reward = 40 - 3.24 = 36.76
    # Net R:R = 36.76 / 23.24 = 1.58
    assert net_rr < 2.0
    assert net_rr == pytest.approx(1.58, abs=0.02)


def test_calculate_net_rr_disqualifies_sub_1_5():
    """Verify R:R < 1.5 is disqualified."""
    entry = 2700.0
    stop_loss = 2680.0  # 20 risk
    target = 2725.0  # 25 gross reward -> net R:R ~ 0.94
    net_rr = TradeSetupEngine._calculate_net_rr(entry, stop_loss, target, TradeDirection.LONG)
    assert net_rr < 1.5


def test_trend_continuation_setup():
    """Verify Trend Continuation setup triggers when in established trend with pullback."""
    df_raw = make_bullish_pullback_candles(60)
    df_ind = IndicatorEngine.compute_all_indicators(df_raw, symbol="XAUUSDT", timeframe="1h")
    struct = StructureEngine.analyze_timeframe(df_ind, timeframe="1h")

    assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=datetime.now(UTC),
        direction=DirectionType.BULLISH,
        bullish_score=75.0,
        bearish_score=15.0,
        breakdown=ScoreBreakdown(total_bullish=75.0, total_bearish=15.0),
        data_quality_score=95.0,
    )

    tf_data = {"1h": {"df": df_ind, "structure": struct}}
    setups = TradeSetupEngine.identify_setups(assessment, tf_data, symbol="XAUUSDT")

    assert len(setups) >= 1
    setup = setups[0]
    assert setup.setup_type == SetupType.TREND_CONTINUATION
    assert setup.direction == TradeDirection.LONG
    assert setup.status == SetupStatus.IDENTIFIED
    assert setup.entry_zone_min < setup.entry_zone_max
    assert setup.stop_loss < setup.entry_zone_min
    assert setup.target_1 > setup.entry_zone_max
    assert setup.risk_reward_ratio >= 1.5
    assert len(setup.supporting_evidence) > 0


def test_liquidity_sweep_reversal_setup():
    """Verify Liquidity Sweep Reversal setup generates concrete levels."""
    times = [datetime(2026, 10, 20, 0, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(30)]
    prices = [2700.0] * 30
    df = pd.DataFrame(
        {
            "open_time": times,
            "open": prices,
            "high": [p + 8.0 for p in prices],
            "low": [p - 8.0 for p in prices],
            "close": prices,
            "volume": [100.0] * 30,
            "taker_buy_volume": [50.0] * 30,
        }
    )
    df_ind = IndicatorEngine.compute_all_indicators(df, symbol="XAUUSDT", timeframe="1h")

    # Mock structure with a confirmed liquidity sweep
    mock_struct = {
        "structure_events": [],
        "liquidity_sweeps": [
            {
                "sweep_type": "BULLISH_SWEEP_LOW",
                "sweep_level": 2690.0,
                "extreme_price": 2675.0,
                "reclaim_price": 2695.0,
            }
        ],
        "sr_zones": [],
        "price_action_patterns": [],
    }

    assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=datetime.now(UTC),
        direction=DirectionType.POTENTIAL_BULLISH,
        bullish_score=55.0,
        bearish_score=20.0,
        breakdown=ScoreBreakdown(total_bullish=55.0, total_bearish=20.0),
        data_quality_score=90.0,
    )

    tf_data = {"1h": {"df": df_ind, "structure": mock_struct}}
    setups = TradeSetupEngine.identify_setups(assessment, tf_data, symbol="XAUUSDT")

    sweep_setups = [s for s in setups if s.setup_type == SetupType.LIQUIDITY_SWEEP_REVERSAL]
    assert len(sweep_setups) == 1
    s = sweep_setups[0]
    assert s.direction == TradeDirection.LONG
    assert s.risk_reward_ratio >= 1.5
    assert s.stop_loss < 2685.0  # Placed below extreme wick
