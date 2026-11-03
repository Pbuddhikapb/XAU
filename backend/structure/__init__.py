"""
Structure and Multi-Timeframe Analysis Package for Binance XAUUSDT.
Strictly conforms to Section 5.E, 5.F, 5.G, 5.H, and Section 6 of PROJECT_SPECIFICATION.md.
"""

from backend.structure.breakout_retest import BreakoutRetestEvent, detect_breakout_retests
from backend.structure.liquidity_sweeps import LiquiditySweepEvent, detect_liquidity_sweeps
from backend.structure.market_structure import MarketStructureEvent, analyze_market_structure
from backend.structure.mtf_manager import MTFAlignmentResult, MTFManager, TimeframeState
from backend.structure.price_action import PriceActionPattern, detect_price_action_patterns
from backend.structure.structure_engine import StructureEngine
from backend.structure.support_resistance import SupportResistanceZone, detect_support_resistance_zones
from backend.structure.swings import SwingPoint, detect_swings

__all__ = [
    "BreakoutRetestEvent",
    "LiquiditySweepEvent",
    "MTFAlignmentResult",
    "MTFManager",
    "MarketStructureEvent",
    "PriceActionPattern",
    "StructureEngine",
    "SupportResistanceZone",
    "SwingPoint",
    "TimeframeState",
    "analyze_market_structure",
    "detect_liquidity_sweeps",
    "detect_price_action_patterns",
    "detect_support_resistance_zones",
    "detect_swings",
]
