"""
Automated verification tests for Phase 8 Institutional Decision Enhancements:
1. Economic Calendar Provider & Macro Event Blackout Gating
2. Regime-Adaptive Weighting & ADX Hysteresis
3. Basis Dislocation Factor
4. Volatility-Scaled Dynamic Structural Buffers
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.config import settings
from backend.data.economic_calendar import EconomicCalendarProvider, EconomicEvent
from backend.decision.models import DirectionAssessment, DirectionType, MarketRegime
from backend.decision.scoring_engine import DirectionalScoringEngine
from backend.decision.setup_engine import TradeSetupEngine

# -----------------------------------------------------------------------------
# 1. Economic Calendar & News Blackout Tests
# -----------------------------------------------------------------------------


def test_economic_calendar_blackout_boundaries():
    """Verify exact minute-by-minute temporal boundaries for news blackout windows."""
    event_time = datetime(2026, 1, 9, 13, 30, tzinfo=UTC)  # US NFP
    test_events = [EconomicEvent("TEST_NFP", "US NFP", "USD", event_time, "HIGH")]

    # 16 minutes before: outside 15m blackout
    t_16m_before = event_time - timedelta(minutes=16)
    is_blackout, _ = EconomicCalendarProvider.is_in_blackout_window(
        t_16m_before, pre_minutes=15, post_minutes=30, custom_events=test_events
    )
    assert not is_blackout

    # 14 minutes before: inside 15m blackout
    t_14m_before = event_time - timedelta(minutes=14)
    is_blackout, reason = EconomicCalendarProvider.is_in_blackout_window(
        t_14m_before, pre_minutes=15, post_minutes=30, custom_events=test_events
    )
    assert is_blackout
    assert "US NFP" in (reason or "")

    # Exactly at event time: inside blackout
    is_blackout, _ = EconomicCalendarProvider.is_in_blackout_window(
        event_time, pre_minutes=15, post_minutes=30, custom_events=test_events
    )
    assert is_blackout

    # 29 minutes after: inside 30m blackout
    t_29m_after = event_time + timedelta(minutes=29)
    is_blackout, _ = EconomicCalendarProvider.is_in_blackout_window(
        t_29m_after, pre_minutes=15, post_minutes=30, custom_events=test_events
    )
    assert is_blackout

    # 31 minutes after: outside 30m blackout
    t_31m_after = event_time + timedelta(minutes=31)
    is_blackout, _ = EconomicCalendarProvider.is_in_blackout_window(
        t_31m_after, pre_minutes=15, post_minutes=30, custom_events=test_events
    )
    assert not is_blackout


def test_setup_engine_blocks_setups_during_news_blackout():
    """Verify Engine B produces NoSetupResponse with HIGH_IMPACT_NEWS_BLACKOUT during news events."""
    event_time = datetime(2026, 1, 9, 13, 30, tzinfo=UTC)
    mock_assessment = DirectionAssessment(
        symbol="XAUUSDT",
        assessment_time=event_time,
        direction=DirectionType.BULLISH,
        bullish_score=85.0,
        bearish_score=15.0,
        breakdown=None,
        supporting_evidence=[],
        contradicting_evidence=[],
        timeframe_alignment={},
        key_levels={},
        invalidation_conditions="",
        data_quality_score=95.0,
        market_regime="TRENDING_BULLISH",
    )

    # Calling during NFP release time
    resp = TradeSetupEngine.identify_setups(
        assessment=mock_assessment,
        timeframe_data={},
        as_of_time=event_time,
    )
    assert resp.reason == "HIGH_IMPACT_NEWS_BLACKOUT"


# -----------------------------------------------------------------------------
# 2. Regime-Adaptive Weighting & Hysteresis Tests
# -----------------------------------------------------------------------------


def test_regime_weights_allocation():
    """Verify weight matrices match institutional specifications."""
    trending_weights = DirectionalScoringEngine._get_regime_weights(MarketRegime.TRENDING_BULLISH)
    assert trending_weights["weight_mtf_trend"] == 30.0
    assert trending_weights["weight_momentum"] == 25.0
    assert trending_weights["weight_volatility_pa"] == 5.0
    assert trending_weights["max_struct_trend"] == settings.MAX_STRUCTURE_TREND_COMBINED

    range_weights = DirectionalScoringEngine._get_regime_weights(MarketRegime.RANGE_BOUND)
    assert range_weights["weight_structure"] == 35.0
    assert range_weights["weight_mtf_trend"] == 5.0
    assert range_weights["weight_liquidity"] == 20.0
    assert range_weights["max_struct_trend"] == 35.0

    vol_weights = DirectionalScoringEngine._get_regime_weights(MarketRegime.VOLATILE_EXPANSION)
    assert vol_weights["min_confirm_score"] == 75.0


def test_regime_hysteresis():
    """Verify ADX hysteresis: enters trend >= 25.0, stays in trend in [20, 25), exits < 20.0."""
    # 1. ADX = 26.0 -> Enters TRENDING_BULLISH
    df_trend = pd.DataFrame({"adx": [26.0], "close": [2700.0], "ema_50": [2650.0], "volatility_percentile": [50.0]})
    regime = DirectionalScoringEngine._determine_baseline_regime(
        df_1h=df_trend,
        tf_data={"1h": {"df": df_trend, "structure": {"current_trend": "BULLISH"}}},
        session_is_active=True,
        data_quality=95.0,
        prev_regime=MarketRegime.RANGE_BOUND,
    )
    assert regime == MarketRegime.TRENDING_BULLISH

    # 2. ADX drops to 23.0 (in buffer) with prev_regime=TRENDING_BULLISH -> Remains TRENDING_BULLISH
    df_buffer = pd.DataFrame({"adx": [23.0], "close": [2700.0], "ema_50": [2650.0], "volatility_percentile": [50.0]})
    regime = DirectionalScoringEngine._determine_baseline_regime(
        df_1h=df_buffer,
        tf_data={"1h": {"df": df_buffer, "structure": {"current_trend": "BULLISH"}}},
        session_is_active=True,
        data_quality=95.0,
        prev_regime=MarketRegime.TRENDING_BULLISH,
    )
    assert regime == MarketRegime.TRENDING_BULLISH

    # 3. ADX drops below 20.0 (18.5) -> Transitions to RANGE_BOUND
    df_range = pd.DataFrame({"adx": [18.5], "close": [2700.0], "ema_50": [2650.0], "volatility_percentile": [50.0]})
    regime = DirectionalScoringEngine._determine_baseline_regime(
        df_1h=df_range,
        tf_data={"1h": {"df": df_range, "structure": {"current_trend": "BULLISH"}}},
        session_is_active=True,
        data_quality=95.0,
        prev_regime=MarketRegime.TRENDING_BULLISH,
    )
    assert regime == MarketRegime.RANGE_BOUND


# -----------------------------------------------------------------------------
# 3. Basis Dislocation Tests
# -----------------------------------------------------------------------------


def test_basis_dislocation_premium_and_discount():
    """Verify extreme basis premium (+30 bps) adds bear points, and discount (-30 bps) adds bull points."""
    # Basis = +8.5 on 2700 price = +31.5 bps
    df_1h = pd.DataFrame({"close": [2700.0], "open": [2700.0], "volume": [100.0], "relative_volume": [1.0]})
    tf_data = {"1h": {"df": df_1h}}

    # Premium test (+8.5 USDT basis)
    bull_pts, bear_pts, ev = DirectionalScoringEngine._score_volume(
        tf_data, max_wt=15.0, basis=8.5
    )
    assert bear_pts > 0
    assert any("retail euphoria / exhaustion risk" in e.description for e in ev)

    # Discount test (-8.5 USDT basis)
    bull_pts_disc, bear_pts_disc, ev_disc = DirectionalScoringEngine._score_volume(
        tf_data, max_wt=15.0, basis=-8.5
    )
    assert bull_pts_disc > 0
    assert any("retail liquidation / exhaustion bounce risk" in e.description for e in ev_disc)


# -----------------------------------------------------------------------------
# 4. Volatility-Scaled Dynamic Buffers Tests
# -----------------------------------------------------------------------------


def test_dynamic_buffer_scaling():
    """Verify buffer multiplier scales wider in compression (low VP) and tighter in expansion (high VP)."""
    # Compression: VP = 10 -> wider cushion
    df_squeeze = pd.DataFrame({"volatility_percentile": [10.0]})
    mult_squeeze = TradeSetupEngine._calculate_dynamic_buffer_multiple(df_squeeze, base_multiple=0.5)
    assert mult_squeeze > 0.50
    assert mult_squeeze >= 0.60

    # Normal: VP = 50 -> close to baseline
    df_normal = pd.DataFrame({"volatility_percentile": [50.0]})
    mult_normal = TradeSetupEngine._calculate_dynamic_buffer_multiple(df_normal, base_multiple=0.5)
    assert 0.45 <= mult_normal <= 0.55

    # Expansion: VP = 90 -> tighter buffer
    df_expansion = pd.DataFrame({"volatility_percentile": [90.0]})
    mult_expansion = TradeSetupEngine._calculate_dynamic_buffer_multiple(df_expansion, base_multiple=0.5)
    assert mult_expansion < 0.45
    assert mult_expansion < mult_squeeze
