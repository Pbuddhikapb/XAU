"""
Unit tests for SetupLifecycleTracker (State Machine & Outcome Evaluation).
Strictly tests Section 7 and 8 of PROJECT_SPECIFICATION.md:
- State transitions: IDENTIFIED -> TRIGGERED -> TARGET_HIT / STOPPED_OUT / INVALIDATED / EXPIRED.
- Conservative collision resolution (adverse-first touch rule when candle hits both SL and TP).
- Immutable historical transition tracking and realized R:R calculation.
"""

import uuid
from datetime import UTC, datetime, timedelta

from backend.decision.lifecycle import SetupLifecycleTracker
from backend.decision.models import (
    SetupStatus,
    SetupType,
    TradeDirection,
    TradeSetupModel,
)


def create_sample_setup() -> TradeSetupModel:
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    return TradeSetupModel(
        setup_id=uuid.uuid4(),
        symbol="XAUUSDT",
        created_at=now,
        status=SetupStatus.IDENTIFIED,
        setup_type=SetupType.TREND_CONTINUATION,
        direction=TradeDirection.LONG,
        timeframe="1h",
        entry_zone_min=2700.0,
        entry_zone_max=2705.0,
        stop_loss=2685.0,
        target_1=2735.0,
        target_2=2755.0,
        target_3=2780.0,
        risk_reward_ratio=1.75,
        expiration_time=now + timedelta(hours=10),
        invalidation_conditions="Close below 2685.0",
        supporting_evidence=[{"test": True}],
    )


def test_lifecycle_entry_trigger():
    """Verify setup transitions from IDENTIFIED to TRIGGERED when price enters entry zone."""
    setup = create_sample_setup()

    # Candle touching [2700, 2705]
    bar = {
        "open": 2710.0,
        "high": 2712.0,
        "low": 2702.0,  # Enters entry zone
        "close": 2704.0,
        "open_time": datetime(2026, 10, 25, 13, 0, tzinfo=UTC),
    }

    res = SetupLifecycleTracker.evaluate_bar(setup, bar)
    assert res.status == SetupStatus.TRIGGERED
    assert res.triggered_at is not None


def test_lifecycle_target_hit():
    """Verify triggered setup transitions to TARGET_HIT when price touches target_1."""
    setup = create_sample_setup()
    setup.status = SetupStatus.TRIGGERED
    setup.triggered_at = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)

    # Candle touching target 2735.0
    bar = {
        "open": 2720.0,
        "high": 2740.0,  # Above 2735.0
        "low": 2718.0,
        "close": 2738.0,
        "open_time": datetime(2026, 10, 25, 14, 0, tzinfo=UTC),
    }

    res = SetupLifecycleTracker.evaluate_bar(setup, bar)
    assert res.status == SetupStatus.TARGET_HIT
    assert res.closed_at is not None
    assert res.outcome == "TARGET_1_HIT"
    assert res.realized_rr == setup.risk_reward_ratio


def test_lifecycle_stopped_out():
    """Verify triggered setup transitions to STOPPED_OUT when price touches stop_loss."""
    setup = create_sample_setup()
    setup.status = SetupStatus.TRIGGERED
    setup.triggered_at = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)

    # Candle hitting SL 2685.0
    bar = {
        "open": 2690.0,
        "high": 2692.0,
        "low": 2680.0,  # Below 2685.0
        "close": 2682.0,
        "open_time": datetime(2026, 10, 25, 14, 0, tzinfo=UTC),
    }

    res = SetupLifecycleTracker.evaluate_bar(setup, bar)
    assert res.status == SetupStatus.STOPPED_OUT
    assert res.realized_rr == -1.0


def test_lifecycle_conservative_collision():
    """Verify conservative collision rule: single bar hitting both SL and TP must resolve to STOPPED_OUT."""
    setup = create_sample_setup()
    setup.status = SetupStatus.TRIGGERED
    setup.triggered_at = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)

    # Wide bar touching both SL (2685.0) and TP (2735.0)
    bar = {
        "open": 2710.0,
        "high": 2745.0,  # Hits TP
        "low": 2680.0,  # Hits SL
        "close": 2730.0,
        "open_time": datetime(2026, 10, 25, 14, 0, tzinfo=UTC),
    }

    res = SetupLifecycleTracker.evaluate_bar(setup, bar)
    assert res.status == SetupStatus.STOPPED_OUT
    assert res.outcome == "STOPPED_OUT_CONSERVATIVE_COLLISION"
    assert res.realized_rr == -1.0


def test_lifecycle_invalidated_before_entry():
    """Verify setup is INVALIDATED if price hits Stop Loss before entering entry zone."""
    setup = create_sample_setup()

    bar = {
        "open": 2690.0,
        "high": 2695.0,
        "low": 2680.0,  # Breaks SL 2685.0 before entry zone
        "close": 2682.0,
        "open_time": datetime(2026, 10, 25, 13, 0, tzinfo=UTC),
    }

    res = SetupLifecycleTracker.evaluate_bar(setup, bar)
    assert res.status == SetupStatus.INVALIDATED
    assert "SL_HIT_BEFORE_ENTRY" in res.outcome


def test_lifecycle_expired_without_fill():
    """Verify setup expires if time exceeds expiration without being triggered."""
    setup = create_sample_setup()

    bar = {
        "open": 2715.0,
        "high": 2720.0,
        "low": 2710.0,
        "close": 2715.0,
        "open_time": datetime(2026, 10, 26, 0, 0, tzinfo=UTC),  # Beyond expiration
    }

    res = SetupLifecycleTracker.evaluate_bar(setup, bar)
    assert res.status == SetupStatus.EXPIRED
    assert res.outcome == "EXPIRED_WITHOUT_FILL"
