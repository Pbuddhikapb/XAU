"""
Configuration module for Binance XAUUSDT Market Intelligence System.
Loads environment variables and sets fixed architectural constants.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # Fixed Target Instrument Parameters
    SYMBOL: str = "XAUUSDT"
    BASE_ASSET: str = "XAU"
    QUOTE_ASSET: str = "USDT"
    CONTRACT_TYPE: str = "TRADIFI_PERPETUAL"

    # Primary timeframes mandated by Specification (Section 6)
    PRIMARY_TIMEFRAMES: list[str] = ["1d", "4h", "1h", "15m", "5m"]
    SECONDARY_TIMEFRAMES: list[str] = ["1m", "30m", "2h"]
    CANONICAL_TIMEFRAME: str = "1m"

    # Database URLs
    DATABASE_URL: str = "postgresql+asyncpg://xau_user:xau_pass_2026@localhost:5432/xau_intelligence"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://xau_user:xau_pass_2026@localhost:5432/xau_intelligence"

    # Binance USD-M Futures Endpoints (REST & WS)
    BINANCE_FUTURES_HTTP_URL: str = "https://fapi.binance.com"
    BINANCE_FUTURES_WS_URL: str = "wss://fstream.binance.com"

    # Public Historical Data Archive (AWS S3)
    BINANCE_DATA_VISION_URL: str = "https://data.binance.vision"
    BINANCE_S3_BUCKET_URL: str = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

    # Binance Testnet Endpoints (Unrestricted fallback for live sandbox / testing)
    BINANCE_TESTNET_HTTP_URL: str = "https://testnet.binancefuture.com"
    BINANCE_TESTNET_WS_URL: str = "wss://stream.binancefuture.com"

    # Optional outbound proxy URL (e.g. socks5:// or http://) for geo-restricted REST calls
    OUTBOUND_PROXY_URL: str | None = None

    # Server configuration
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Historical Inception Timestamp: 2025-12-11 08:05:00 UTC
    CONTRACT_ONBOARD_TIME_MS: int = 1765440300000

    # CME Session Day (18:00 ET to 17:00 ET) 1D aggregation alongside UTC 1D candle
    ENABLE_CME_SESSION_DAILY_CANDLES: bool = True

    # Phase 4: Decision Engine Architecture (Section 7 of Spec & Section 16 of Audit)
    DECISION_METHODOLOGY_VERSION: str = "v1.1.0-phase4"
    DATA_QUALITY_MIN_SCORE: float = 70.0

    # Engine A: Scoring Weights (Initial configurable parameters summing to 100 max pts)
    WEIGHT_STRUCTURE: float = 25.0
    WEIGHT_MTF_TREND: float = 20.0
    WEIGHT_MOMENTUM: float = 15.0
    WEIGHT_VOLUME: float = 15.0
    WEIGHT_VOLATILITY_PA: float = 15.0
    WEIGHT_LIQUIDITY: float = 10.0

    # Correlation-Aware Caps: Prevents double-counting collinear factors
    # Structure (25) + MTF Trend (20) max combined cap
    MAX_STRUCTURE_TREND_COMBINED: float = 35.0
    # Momentum (15) + Volatility/PA (15) max combined cap
    MAX_MOMENTUM_PA_COMBINED: float = 22.0

    # Engine B: Setup Qualification & Friction Model
    MIN_NET_RR: float = 1.5
    TAKER_FEE_PCT: float = 0.0010  # 0.05% entry + 0.05% exit = 0.10% roundtrip
    SLIPPAGE_PCT: float = 0.0002   # 0.02% slippage allowance
    SPREAD_PCT: float = 0.0001     # 0.01% estimated average spread
    FUNDING_PCT: float = 0.0001    # 0.01% per-holding period estimated funding friction

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
