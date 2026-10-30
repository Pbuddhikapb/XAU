"""
Edge-case, stress, and numerical boundary tests for Phase 3 Market Structure Modules.
Covers empty dataframes, single-candle frames, flat prices, missing timeframes,
and invalid inputs.
"""

from datetime import UTC, datetime

import pandas as pd
import pytest

from backend.structure.liquidity_sweeps import detect_liquidity_sweeps
from backend.structure.market_structure import analyze_market_structure
from backend.structure.mtf_manager import MTFManager
from backend.structure.price_action import detect_price_action_patterns
from backend.structure.structure_engine import StructureEngine
from backend.structure.support_resistance import detect_support_resistance_zones
from backend.structure.swings import detect_swings


def test_empty_dataframe_structure():
    empty_df = pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])

    assert detect_swings(empty_df) == []
    events, trend = analyze_market_structure(empty_df)
    assert events == [] and trend == "NEUTRAL"
    assert detect_liquidity_sweeps(empty_df) == []
    assert detect_price_action_patterns(empty_df) == []
    assert detect_support_resistance_zones(empty_df) == []

    analysis = StructureEngine.analyze_timeframe(empty_df)
    assert analysis["current_trend"] == "NEUTRAL"
    assert analysis["structure_events"] == []


def test_single_candle_structure():
    single_df = pd.DataFrame(
        {
            "open_time": [datetime.now(UTC)],
            "open": [2650.0],
            "high": [2655.0],
            "low": [2648.0],
            "close": [2652.0],
            "volume": [100.0],
        }
    )

    assert detect_swings(single_df) == []
    events, trend = analyze_market_structure(single_df)
    assert events == [] and trend == "NEUTRAL"
    assert detect_liquidity_sweeps(single_df) == []
    assert detect_price_action_patterns(single_df) == []
    assert detect_support_resistance_zones(single_df) == []

    analysis = StructureEngine.analyze_timeframe(single_df)
    assert analysis["current_trend"] == "NEUTRAL"


def test_flat_prices_structure():
    n = 30
    flat_df = pd.DataFrame(
        {
            "open_time": [datetime.now(UTC)] * n,
            "open": [2650.0] * n,
            "high": [2650.0] * n,
            "low": [2650.0] * n,
            "close": [2650.0] * n,
            "volume": [100.0] * n,
        }
    )

    # Flat prices should not identify swings because strictly greater is required
    swings = detect_swings(flat_df, window=2)
    assert swings == []

    events, trend = analyze_market_structure(flat_df)
    assert events == []
    assert trend == "NEUTRAL"
    assert detect_liquidity_sweeps(flat_df) == []


def test_mtf_manager_empty_and_unknown_directions():
    # Test completely empty dict
    res_empty = MTFManager.evaluate_alignment({})
    assert res_empty.overall_bias == "NEUTRAL"
    assert res_empty.compound_score == 0.0
    assert res_empty.alignment_state == "CONFLICTING"

    # Test unknown direction strings fallback to 0.0
    res_unknown = MTFManager.evaluate_alignment({"1d": {"direction": "RANDOM_STRING"}})
    assert res_unknown.overall_bias == "NEUTRAL"
    assert res_unknown.compound_score == 0.0


@pytest.mark.asyncio
async def test_persist_empty_structure_events():
    count = await StructureEngine.persist_structure_events([], symbol="XAUUSDT")
    assert count == 0
