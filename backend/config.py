"""
Configuration module for Binance XAUUSDT Market Intelligence System.
Loads environment variables and sets fixed architectural constants.
"""

from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # Fixed Target Instrument Parameters
    SYMBOL: str = "XAUUSDT"
    BASE_ASSET: str = "XAU"
    QUOTE_ASSET: str = "USDT"
    CONTRACT_TYPE: str = "TRADIFI_PERPETUAL"

    # Primary timeframes mandated by Specification (Section 6)
    PRIMARY_TIMEFRAMES: List[str] = ["1d", "4h", "1h", "15m", "5m"]
    SECONDARY_TIMEFRAMES: List[str] = ["1m", "30m", "2h"]
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

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
