"""
Volume Analysis Module for Binance XAUUSDT.
Strictly conforms to Section 5.D of PROJECT_SPECIFICATION.md:
- Relative Volume (RVOL 20)
- Volume Expansion
- Taker Buy/Sell Ratio
- Buying and Selling Pressure Proxies & Net Volume Delta
"""

from typing import Any

import numpy as np
import pandas as pd


def calculate_rvol(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Calculate Relative Volume (RVOL).
    Compares current volume to the trailing 20-period baseline volume.

    Formula:
        RVOL_t = Volume_t / SMA(Volume, period)_{t-1}
    """
    if len(volume) < 2:
        return pd.Series(1.0, index=volume.index, dtype=np.float64)

    # Use prior period moving average so current spike does not inflate baseline
    vol_ma = volume.shift(1).rolling(window=period, min_periods=min(5, len(volume))).mean()
    vol_ma = vol_ma.combine_first(volume.rolling(window=period, min_periods=1).mean())

    eps = 1e-9
    rvol = volume / (vol_ma + eps)
    return rvol.fillna(1.0)


def calculate_taker_buy_ratio(volume: pd.Series, taker_buy_volume: pd.Series) -> pd.Series:
    """
    Calculate Taker Buy Ratio.

    Formula:
        TakerBuyRatio_t = TakerBuyVolume_t / (Volume_t + epsilon)
        Guaranteed bounded in [0.0, 1.0].
    """
    eps = 1e-9
    ratio = taker_buy_volume / (volume + eps)
    return ratio.clip(lower=0.0, upper=1.0)


def calculate_volume_delta(volume: pd.Series, taker_buy_volume: pd.Series) -> pd.DataFrame:
    """
    Calculate Net Volume Delta and Directional Pressure Proxies.

    Formulas:
        TakerSellVolume = Volume - TakerBuyVolume
        NetDelta = TakerBuyVolume - TakerSellVolume
        CumulativeDelta = cumsum(NetDelta)
    """
    taker_sell = (volume - taker_buy_volume).clip(lower=0.0)
    net_delta = taker_buy_volume - taker_sell
    cum_delta = net_delta.cumsum()

    return pd.DataFrame(
        {
            "taker_buy": taker_buy_volume,
            "taker_sell": taker_sell,
            "net_delta": net_delta,
            "cum_delta": cum_delta,
        },
        index=volume.index,
    )


def calculate_pressure_proxies(
    open_p: pd.Series,
    high_p: pd.Series,
    low_p: pd.Series,
    close_p: pd.Series,
    volume: pd.Series,
    taker_buy_vol: pd.Series,
) -> pd.DataFrame:
    """
    Calculate Buying and Selling Pressure proxies combining order flow with price action wicks.

    Formulas:
        Range = High - Low + epsilon
        BuyingPressure = TakerBuyVol * (Close - Low) / Range
        SellingPressure = TakerSellVol * (High - Close) / Range
    """
    eps = 1e-9
    rng = high_p - low_p + eps
    taker_sell = (volume - taker_buy_vol).clip(lower=0.0)

    buying_pressure = taker_buy_vol * ((close_p - low_p).clip(lower=0.0) / rng)
    selling_pressure = taker_sell * ((high_p - close_p).clip(lower=0.0) / rng)

    return pd.DataFrame(
        {
            "buying_pressure": buying_pressure,
            "selling_pressure": selling_pressure,
        },
        index=volume.index,
    )


def evaluate_volume_profile(
    open_p: pd.Series,
    high_p: pd.Series,
    low_p: pd.Series,
    close_p: pd.Series,
    volume: pd.Series,
    taker_buy_vol: pd.Series,
) -> dict[str, Any]:
    """
    Evaluate comprehensive volume conditions for the latest candle.
    Returns RVOL, taker buy ratio, net volume delta, and pressure assessment.
    """
    if len(volume) < 20:
        return {
            "relative_volume": 1.0,
            "taker_buy_ratio": 0.5,
            "net_volume_delta": 0.0,
            "volume_expansion": False,
            "volume_bias": "NEUTRAL",
        }

    rvol_s = calculate_rvol(volume, period=20)
    ratio_s = calculate_taker_buy_ratio(volume, taker_buy_vol)
    delta_df = calculate_volume_delta(volume, taker_buy_vol)

    last_idx = volume.index[-1]
    rvol_val = float(rvol_s.loc[last_idx])
    ratio_val = float(ratio_s.loc[last_idx])
    delta_val = float(delta_df["net_delta"].loc[last_idx])

    is_expanded = rvol_val >= 1.5

    # Volume directional bias
    if ratio_val > 0.55 and delta_val > 0:
        bias = "AGGRESSIVE_BUYING" if is_expanded else "MODERATE_BUYING"
    elif ratio_val < 0.45 and delta_val < 0:
        bias = "AGGRESSIVE_SELLING" if is_expanded else "MODERATE_SELLING"
    else:
        bias = "NEUTRAL"

    return {
        "relative_volume": round(rvol_val, 4),
        "taker_buy_ratio": round(ratio_val, 4),
        "net_volume_delta": round(delta_val, 4),
        "volume_expansion": is_expanded,
        "volume_bias": bias,
    }
