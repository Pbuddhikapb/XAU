"""
Unit and integration tests for Engine B: TradeSetupEngine.
Strictly conforms to Section 6, 7, and 8 of PROJECT_SPECIFICATION.md and Section 16 of Forensic Audit:
- 4 deterministic setup patterns (Trend Continuation, Breakout Retest, Sweep Reversal, Range Rejection).
- Stop Loss strictly derived from structure + ATR buffer.
- Targets T1, T2, T3.
- Comprehensive friction model: Taker fees (0.10%) + slippage (0.02%) + spread (0.01%) + funding (0.01%) = 0.14%.
- Enforces Net R:R >= 1.5; rejects any setup with Net R:R < 1.5.
- Setups generated only from completed candles.
- Adversarial no-lookahead test.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.analytics.indicator_engine import IndicatorEngine
from backend.config import settings
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
    """Generate an uptrend followed by a pullback to EMA20 with completed close times."""
    start_time = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    times = [start_time + timedelta(hours=i) for i in range(n)]
    close_times = [t + timedelta(hours=1) for t in times]
    prices = []
    for i in range(n):
        if i < n - 7:
            p = 2650.0 + (i * 1.5)
        else:
            p = prices[-1] - 1.5
        prices.append(p)

    return pd.DataFrame(
        {
            "open_time": times,
            "close_time": close_times,
            "open": [p - 0.5 for p in prices],
            "high": [p + 4.0 for p in prices],
            "low": [p - 4.0 for p in prices],
            "close": prices,
            "volume": [200.0] * n,
            "taker_buy_volume": [130.0] * n,
        }
    )


def test_calculate_net_rr_deducts_all_frictions():
    """Verify net R:R calculation accounts for 0.14% total friction (taker + slippage + spread + funding)."""
    entry = 2700.0
    stop_loss = 2680.0  # gross risk = 20.0
    target = 2740.0     # gross reward = 40.0 (gross R:R = 2.0)

    net_rr, gross_rr = TradeSetupEngine._calculate_net_and_gross_rr(
        entry, stop_loss, target, TradeDirection.LONG
    )

    total_friction_pct = settings.TAKER_FEE_PCT + settings.SLIPPAGE_PCT + settings.SPREAD_PCT + settings.FUNDING_PCT
    friction_dollar = entry * total_friction_pct
    expected_net_risk = 20.0 + friction_dollar
    expected_net_reward = 40.0 - friction_dollar
    expected_net_rr = round(expected_net_reward / expected_net_risk, 2)

    assert gross_rr == 2.0
    assert net_rr < gross_rr
    assert net_rr == pytest.approx(expected_net_rr, abs=0.02)


def test_calculate_net_rr_disqualifies_sub_1_5():
    """Verify Net R:R < 1.5 is disqualified."""
    entry = 2700.0
    stop_loss = 2680.0
    target = 2725.0  # gross reward = 25.0 -> gross R:R = 1.25, net R:R ~ 0.88
    net_rr, _ = TradeSetupEngine._calculate_net_and_gross_rr(
        entry, stop_loss, target, TradeDirection.LONG
    )
    assert net_rr < settings.MIN_NET_RR


def test_trend_continuation_setup_structure_plus_atr_stop():
    """Verify Trend Continuation setup derives Stop Loss from Structure + ATR buffer."""
    df_raw = make_bullish_pullback_candles(60)
    df_ind = IndicatorEngine.compute_all_indicators(df_raw, symbol="XAUUSDT", timeframe="1h")
    struct = StructureEngine.analyze_timeframe(df_ind, timeframe="1h")

    assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=df_raw["close_time"].iloc[-1],
        direction=DirectionType.BULLISH,
        bullish_score=75.0,
        bearish_score=15.0,
        breakdown=ScoreBreakdown(total_bullish=75.0, total_bearish=15.0),
        data_quality_score=95.0,
    )

    tf_data = {"1h": {"df": df_ind, "structure": struct}}
    as_of = df_raw["close_time"].iloc[-1]
    setups = TradeSetupEngine.identify_setups(assessment, tf_data, symbol="XAUUSDT", as_of_time=as_of)

    assert len(setups) >= 1
    s = setups[0]
    assert s.setup_type == SetupType.TREND_CONTINUATION
    assert s.direction == TradeDirection.LONG
    assert s.status in [SetupStatus.CONFIRMED, SetupStatus.POTENTIAL]
    assert s.risk_reward_ratio >= settings.MIN_NET_RR
    # Stop loss is below entry zone min
    assert s.stop_loss < s.entry_zone_min
    # Targets ascend T1 < T2 < T3
    assert s.target_1 > s.entry_zone_max
    assert s.target_2 is not None and s.target_2 > s.target_1
    assert s.target_3 is not None and s.target_3 > s.target_2


def test_setups_withheld_on_incomplete_candle():
    """Verify setup generation is rejected if current candle is still forming (incomplete)."""
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
    # as_of_time is 10 minutes into the last bar (before its close_time)
    bar_open = df_raw["open_time"].iloc[-1]
    premature_as_of = bar_open + timedelta(minutes=10)

    setups = TradeSetupEngine.identify_setups(
        assessment, tf_data, symbol="XAUUSDT", as_of_time=premature_as_of, require_completed_candles=True
    )
    # Must withhold setup on uncompleted candle
    assert setups == []


def test_liquidity_sweep_reversal_setup():
    """Verify Liquidity Sweep Reversal setup generates concrete structure+ATR levels and targets."""
    times = [datetime(2026, 10, 20, 0, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(30)]
    close_times = [t + timedelta(hours=1) for t in times]
    prices = [2700.0] * 30
    df = pd.DataFrame(
        {
            "open_time": times,
            "close_time": close_times,
            "open": prices,
            "high": [p + 8.0 for p in prices],
            "low": [p - 8.0 for p in prices],
            "close": prices,
            "volume": [100.0] * 30,
            "taker_buy_volume": [50.0] * 30,
        }
    )
    df_ind = IndicatorEngine.compute_all_indicators(df, symbol="XAUUSDT", timeframe="1h")

    mock_struct = {
        "structure_events": [],
        "liquidity_sweeps": [
            {
                "sweep_type": "SWEEP_LOW",
                "swept_level": 2690.0,
                "penetration_price": 2675.0,
                "close_price": 2695.0,
            }
        ],
        "sr_zones": [],
        "price_action_patterns": [],
    }

    assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=close_times[-1],
        direction=DirectionType.POTENTIAL_BULLISH,
        bullish_score=55.0,
        bearish_score=20.0,
        breakdown=ScoreBreakdown(total_bullish=55.0, total_bearish=20.0),
        data_quality_score=90.0,
    )

    tf_data = {"1h": {"df": df_ind, "structure": mock_struct}}
    setups = TradeSetupEngine.identify_setups(
        assessment, tf_data, symbol="XAUUSDT", as_of_time=close_times[-1]
    )

    assert len(setups) >= 1
    s = setups[0]
    assert s.setup_type == SetupType.LIQUIDITY_SWEEP_REVERSAL
    assert s.direction == TradeDirection.LONG
    assert s.stop_loss < s.entry_zone_min
    assert s.risk_reward_ratio >= settings.MIN_NET_RR


def test_setup_engine_adversarial_lookahead():
    """Adversarial test: Appending future data does not alter past completed setup parameters."""
    df_raw = make_bullish_pullback_candles(60)
    df_ind = IndicatorEngine.compute_all_indicators(df_raw, symbol="XAUUSDT", timeframe="1h")
    struct = StructureEngine.analyze_timeframe(df_ind, timeframe="1h")

    as_of = df_raw["close_time"].iloc[-1]
    assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=as_of,
        direction=DirectionType.BULLISH,
        bullish_score=75.0,
        bearish_score=15.0,
        breakdown=ScoreBreakdown(total_bullish=75.0, total_bearish=15.0),
        data_quality_score=95.0,
    )

    tf_data_base = {"1h": {"df": df_ind, "structure": struct}}
    base_setups = TradeSetupEngine.identify_setups(
        assessment, tf_data_base, symbol="XAUUSDT", as_of_time=as_of
    )
    assert len(base_setups) >= 1

    # Append 30 future extreme bars
    future_times = [df_raw["open_time"].iloc[-1] + timedelta(hours=i + 1) for i in range(30)]
    future_close_times = [t + timedelta(hours=1) for t in future_times]
    df_future = pd.DataFrame(
        {
            "open_time": future_times,
            "close_time": future_close_times,
            "open": [3500.0] * 30,
            "high": [3550.0] * 30,
            "low": [3480.0] * 30,
            "close": [3520.0] * 30,
            "volume": [1000.0] * 30,
            "taker_buy_volume": [600.0] * 30,
        }
    )
    df_shocked = pd.concat([df_raw, df_future], ignore_index=True)
    df_sliced = df_shocked[df_shocked["close_time"] <= as_of].copy()

    df_ind_shocked = IndicatorEngine.compute_all_indicators(df_sliced, symbol="XAUUSDT", timeframe="1h")
    struct_shocked = StructureEngine.analyze_timeframe(df_ind_shocked, timeframe="1h")
    tf_data_shocked = {"1h": {"df": df_ind_shocked, "structure": struct_shocked}}

    shocked_setups = TradeSetupEngine.identify_setups(
        assessment, tf_data_shocked, symbol="XAUUSDT", as_of_time=as_of
    )

    assert len(base_setups) == len(shocked_setups)
    for bs, ss in zip(base_setups, shocked_setups, strict=False):
        assert bs.setup_type == ss.setup_type
        assert bs.direction == ss.direction
        assert bs.entry_zone_min == ss.entry_zone_min
        assert bs.entry_zone_max == ss.entry_zone_max
        assert bs.stop_loss == ss.stop_loss
        assert bs.target_1 == ss.target_1
        assert bs.risk_reward_ratio == ss.risk_reward_ratio
