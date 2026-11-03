"""
Tests for Market Structure: Pivot Detection, HH/HL/LH/LL classification, BOS, and CHoCH.
"""

from datetime import UTC, datetime

import pandas as pd

from analytical_engine.structure.pivots import PivotDetector
from analytical_engine.structure.swings import MarketStructureClassifier


def create_structure_candles() -> pd.DataFrame:
    """
    Build a known synthetic price pattern with distinct swing points:
    Bar 0: 100
    Bar 1: 105
    Bar 2: 110 (Swing High 1)
    Bar 3: 104
    Bar 4: 100 (Swing Low 1)
    Bar 5: 108
    Bar 6: 115 (Swing High 2 -> Higher High)
    Bar 7: 107
    Bar 8: 103 (Swing Low 2 -> Higher Low)
    Bar 9: 112
    Bar 10: 120 (BOS Bull break above High 2)
    """
    prices = [
        (100.0, 101.0, 99.0, 100.0),    # 0
        (101.0, 106.0, 101.0, 105.0),   # 1
        (105.0, 110.0, 104.0, 108.0),   # 2 (Swing High 1 at 110)
        (108.0, 109.0, 103.0, 104.0),   # 3
        (104.0, 105.0, 99.0, 100.0),    # 4 (Swing Low 1 at 99)
        (100.0, 109.0, 100.0, 108.0),   # 5
        (108.0, 116.0, 107.0, 115.0),   # 6 (Swing High 2 at 116)
        (115.0, 115.0, 106.0, 107.0),   # 7
        (107.0, 108.0, 102.0, 103.0),   # 8 (Swing Low 2 at 102)
        (103.0, 113.0, 103.0, 112.0),   # 9
        (112.0, 121.0, 111.0, 120.0),   # 10 (Close 120 breaks High 2 at 116)
    ]

    records = []
    base_epoch = 1765440000
    for i, (op, hi, lo, cl) in enumerate(prices):
        records.append({
            "open_time": datetime.fromtimestamp(base_epoch + i * 60, tz=UTC),
            "close_time": datetime.fromtimestamp(base_epoch + (i + 1) * 60, tz=UTC),
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": 100.0,
        })
    df = pd.DataFrame(records)
    df.attrs["timeframe"] = "1m"
    return df


def test_pivot_detection_and_confirmation_lag():
    """Verify pivots are detected at the correct candle but confirmed only after right-shoulder elapsed."""
    df = create_structure_candles()
    detector = PivotDetector(left_bars=2, right_bars=2)
    pivots = detector.find_pivots(df)

    # We expect:
    # Swing High 1 at Bar 2 (High = 110.0), confirmed at Bar 4 close
    # Swing Low 1 at Bar 4 (Low = 99.0), confirmed at Bar 6 close
    # Swing High 2 at Bar 6 (High = 116.0), confirmed at Bar 8 close
    # Swing Low 2 at Bar 8 (Low = 102.0), confirmed at Bar 10 close
    highs = [p for p in pivots if p.pivot_type == "HIGH"]
    lows = [p for p in pivots if p.pivot_type == "LOW"]

    assert len(highs) >= 2
    assert len(lows) >= 2
    assert highs[0].pivot_price == 110.0
    assert highs[0].confirmation_lag_bars == 2
    # Pivot occurred at bar 2 open time, confirmed at bar 4 close time
    assert highs[0].pivot_time == df.loc[2, "open_time"]
    assert highs[0].confirmation_time == df.loc[4, "close_time"]

    assert highs[1].pivot_price == 116.0
    assert highs[1].pivot_time == df.loc[6, "open_time"]
    assert highs[1].confirmation_time == df.loc[8, "close_time"]


def test_swing_classification_hh_hl():
    """Verify classification of Higher Highs (HH) and Higher Lows (HL)."""
    df = create_structure_candles()
    detector = PivotDetector(left_bars=2, right_bars=2)
    pivots = detector.find_pivots(df)

    classifier = MarketStructureClassifier()
    events = classifier.classify_swings(pivots)

    event_types = [e.event_type for e in events]
    # High 2 (116) > High 1 (110) -> "HH"
    assert "HH" in event_types
    # Low 2 (102) > Low 1 (99) -> "HL"
    assert "HL" in event_types


def test_structural_breaks_bos_and_choch():
    """Verify Break of Structure (BOS) is detected only after level was confirmed."""
    df = create_structure_candles()
    detector = PivotDetector(left_bars=2, right_bars=2)
    pivots = detector.find_pivots(df)

    classifier = MarketStructureClassifier(break_by_close=True)
    breaks = classifier.detect_structural_breaks(df, pivots)

    # Bar 10 closes at 120.0, which breaks High 2 (116.0)
    # High 2 was confirmed at bar 8 close.
    # Therefore, at bar 10, the level was active and valid.
    assert len(breaks) >= 1
    last_break = breaks[-1]
    assert last_break.price == 120.0
    assert last_break.broken_level == 116.0
    assert last_break.event_type in ("BOS_BULL", "CHOCH_BULL")
    assert last_break.confirmed_candle_time == df.loc[10, "close_time"]
