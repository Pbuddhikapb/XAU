"""
Tests for Multi-Timeframe Candle Aggregation and Causal Feature Alignment.
"""

from datetime import UTC, datetime

import pandas as pd

from analytical_engine.multi_timeframe.aggregation import CandleAggregator
from analytical_engine.multi_timeframe.alignment import MultiTimeframeAligner


def create_1m_test_sequence(n_minutes: int = 65) -> pd.DataFrame:
    """Generate n_minutes of continuous 1m bars starting at 00:00:00 UTC."""
    records = []
    base_epoch = 1765440000  # aligned boundary
    for i in range(n_minutes):
        records.append({
            "open_time": datetime.fromtimestamp(base_epoch + i * 60, tz=UTC),
            "close_time": datetime.fromtimestamp(base_epoch + (i + 1) * 60, tz=UTC),
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 10.0,
            "quote_volume": 1000.0,
            "trades_count": 5,
            "taker_buy_volume": 6.0,
            "taker_buy_quote_volume": 600.0,
        })
    df = pd.DataFrame(records)
    df.attrs["symbol"] = "XAUUSDT"
    df.attrs["timeframe"] = "1m"
    return df


def test_5m_aggregation():
    """Verify 1m to 5m aggregation Open, High, Low, Close, and additive volume."""
    df_1m = create_1m_test_sequence(15)  # exactly three 5m bars
    aggregator = CandleAggregator(target_timeframe="5m", require_full_bars=True)
    df_5m = aggregator.aggregate(df_1m)

    assert len(df_5m) == 3
    # First 5m bar (minutes 0 to 4):
    # Open = open of min 0 = 100.0
    # High = max high of mins 0..4 = 105.0 + 4 = 109.0
    # Low = min low of mins 0..4 = 95.0 + 0 = 95.0
    # Close = close of min 4 = 102.0 + 4 = 106.0
    # Volume = 5 * 10.0 = 50.0
    b0 = df_5m.iloc[0]
    assert b0["open"] == 100.0
    assert b0["high"] == 109.0
    assert b0["low"] == 95.0
    assert b0["close"] == 106.0
    assert b0["volume"] == 50.0
    assert b0["constituent_count"] == 5
    assert bool(b0["is_complete"]) is True
    assert bool(b0["is_confirmed"]) is True


def test_incomplete_candle_rejection():
    """Verify incomplete higher-timeframe bar is excluded when require_full_bars=True."""
    # 7 minutes total: one complete 5m bar (mins 0..4), and an incomplete bar with 2 mins (mins 5..6)
    df_1m = create_1m_test_sequence(7)

    agg_strict = CandleAggregator(target_timeframe="5m", require_full_bars=True)
    df_strict = agg_strict.aggregate(df_1m)
    assert len(df_strict) == 1  # Only the complete bar is emitted

    agg_lenient = CandleAggregator(target_timeframe="5m", require_full_bars=False)
    df_lenient = agg_lenient.aggregate(df_1m)
    assert len(df_lenient) == 2  # Both bars emitted
    assert bool(df_lenient.iloc[1]["is_complete"]) is False


def test_causal_htf_alignment():
    """Verify MultiTimeframeAligner merges only closed higher-timeframe candles."""
    df_1m = create_1m_test_sequence(70)

    # Aggregate 1h bars (at minute 60, Bar 0 closes)
    agg_1h = CandleAggregator(target_timeframe="1h", require_full_bars=True)
    df_1h = agg_1h.aggregate(df_1m)
    assert len(df_1h) == 1
    # Add dummy HTF feature
    df_1h["trend_val"] = 42.0

    # Aggregate 5m base bars
    agg_5m = CandleAggregator(target_timeframe="5m", require_full_bars=True)
    df_5m = agg_5m.aggregate(df_1m)

    aligner = MultiTimeframeAligner(evaluation_point="BAR_CLOSE")
    aligned = aligner.align(df_5m, htf_data={"1h": df_1h})

    # The 1h bar opens at min 0 and closes at min 60 (bar_idx 11 of 5m bars)
    # For 5m bars 0 through 10 (minutes 0 to 55), the 1h bar has NOT closed yet!
    # Therefore, '1h_trend_val' MUST be NaN for bars 0 through 10.
    for i in range(11):
        assert pd.isna(aligned.loc[i, "1h_trend_val"])

    # For 5m bar 11 (minute 55..60), close_time == 1h close_time -> Available!
    assert aligned.loc[11, "1h_trend_val"] == 42.0
    assert aligned.loc[12, "1h_trend_val"] == 42.0
