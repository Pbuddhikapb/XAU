"""
Analytics Package for Binance XAUUSDT Market Intelligence System.
Strictly conforms to Section 5 of PROJECT_SPECIFICATION.md.
"""

from backend.analytics.divergence import DivergencePoint, DivergenceResult, detect_divergences, find_swings
from backend.analytics.indicator_engine import IndicatorEngine
from backend.analytics.momentum import calculate_macd, calculate_roc, calculate_rsi, evaluate_momentum
from backend.analytics.trend import (
    calculate_adx_dmi,
    calculate_ema,
    calculate_trend_emas,
    evaluate_trend_direction_and_strength,
)
from backend.analytics.volatility import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_historical_volatility_percentile,
    evaluate_volatility_regime,
)
from backend.analytics.volume import (
    calculate_pressure_proxies,
    calculate_rvol,
    calculate_taker_buy_ratio,
    calculate_volume_delta,
    evaluate_volume_profile,
)
from backend.analytics.vwap import calculate_session_anchored_vwap, evaluate_vwap_position

__all__ = [
    "DivergencePoint",
    "DivergenceResult",
    "IndicatorEngine",
    "calculate_adx_dmi",
    "calculate_atr",
    "calculate_bollinger_bands",
    "calculate_ema",
    "calculate_historical_volatility_percentile",
    "calculate_macd",
    "calculate_pressure_proxies",
    "calculate_roc",
    "calculate_rsi",
    "calculate_rvol",
    "calculate_session_anchored_vwap",
    "calculate_taker_buy_ratio",
    "calculate_trend_emas",
    "calculate_volume_delta",
    "detect_divergences",
    "evaluate_momentum",
    "evaluate_trend_direction_and_strength",
    "evaluate_volatility_regime",
    "evaluate_volume_profile",
    "evaluate_vwap_position",
    "find_swings",
]
