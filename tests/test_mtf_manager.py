"""
Unit tests for Multi-Timeframe Alignment Manager.
"""

from backend.structure.mtf_manager import MTFManager


def test_mtf_aligned_bullish():
    directions = {
        "1d": {"direction": "BULLISH", "strength": 80.0, "structure": "HH_HL"},
        "4h": {"direction": "BULLISH", "strength": 75.0, "structure": "HH_HL"},
        "1h": {"direction": "BULLISH", "strength": 70.0, "structure": "BOS_BULL"},
        "15m": {"direction": "BULLISH", "strength": 65.0, "structure": "HH_HL"},
        "5m": {"direction": "BULLISH", "strength": 60.0, "structure": "HH_HL"},
    }

    result = MTFManager.evaluate_alignment(directions)
    assert result.alignment_state == "ALIGNED_BULLISH"
    assert result.overall_bias == "BULLISH"
    assert result.compound_score == 1.0
    assert result.macro_trend == "BULLISH"
    assert result.micro_trend == "BULLISH"
    assert result.timeframes["1h"].is_countertrend is False


def test_mtf_countertrend_pullback():
    # Macro bullish (1D/4H), but micro (15M/5M) pulling back bearishly
    directions = {
        "1d": {"direction": "BULLISH", "strength": 85.0, "structure": "HH_HL"},
        "4h": {"direction": "BULLISH", "strength": 80.0, "structure": "HH_HL"},
        "1h": {"direction": "NEUTRAL", "strength": 40.0, "structure": "CHOP"},
        "15m": {"direction": "BEARISH", "strength": 60.0, "structure": "LH_LL"},
        "5m": {"direction": "BEARISH", "strength": 70.0, "structure": "LH_LL"},
    }

    result = MTFManager.evaluate_alignment(directions)
    assert result.macro_trend == "BULLISH"
    assert result.micro_trend == "BEARISH"
    assert result.alignment_state == "COUNTERTREND_PULLBACK"
    assert result.timeframes["15m"].is_countertrend is True
    assert result.timeframes["5m"].is_countertrend is True
