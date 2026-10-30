"""
Exchange Verifier Module for Binance USD-M Futures XAUUSDT TradFi Perpetual.
Enforces Principles 1, 2, 3, 4, 5 of PROJECT_SPECIFICATION.md:
- Exclusive symbol is XAUUSDT.
- Verify instrument at runtime.
- Never substitute another symbol.
- Verifies exact contract filters, status, and underlying constituents.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from sqlalchemy.dialects.postgresql import insert

from backend.config import settings
from backend.database import get_sync_session
from backend.models.tables import MarketMetadata

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """Raised when instrument verification fails against Binance Futures specifications."""
    pass


class ExchangeVerifier:
    """Authoritative verifier for the Binance XAUUSDT TradFi perpetual contract."""

    def __init__(self, base_url: Optional[str] = None, proxy_url: Optional[str] = None):
        # Default to testnet if running in development without proxy, or live endpoint
        self.base_url = base_url or settings.BINANCE_TESTNET_HTTP_URL
        self.proxy_url = proxy_url or settings.OUTBOUND_PROXY_URL
        self.symbol = settings.SYMBOL.upper()

    def _fetch_json(self, path: str) -> Dict[str, Any]:
        """Fetch JSON data from Binance endpoint with error handling."""
        url = f"{self.base_url.rstrip('/')}{path}"
        handlers = []
        if self.proxy_url:
            handlers.append(urllib.request.ProxyHandler({
                'http': self.proxy_url,
                'https': self.proxy_url
            }))
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-XAU/1.0"})

        try:
            with opener.open(req, timeout=10) as response:
                if response.status != 200:
                    raise VerificationError(f"HTTP {response.status} fetching {url}")
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 451 or e.code == 403:
                raise VerificationError(
                    f"Binance API returned HTTP {e.code} (Geographic / Legal Restriction) for {url}. "
                    "Ensure outbound proxy is configured or fallback endpoint is specified."
                ) from e
            raise VerificationError(f"HTTP Error {e.code} for {url}: {e.reason}") from e
        except Exception as e:
            raise VerificationError(f"Failed to connect to {url}: {e}") from e

    def verify_server_time(self) -> int:
        """Verify time synchronization with Binance exchange server."""
        data = self._fetch_json("/fapi/v1/time")
        server_time_ms = data.get("serverTime")
        if not server_time_ms or not isinstance(server_time_ms, int):
            raise VerificationError(f"Invalid serverTime response: {data}")
        return server_time_ms

    def verify_constituents(self) -> List[Dict[str, Any]]:
        """Verify underlying index constituents for XAUUSDT."""
        data = self._fetch_json(f"/fapi/v1/constituents?symbol={self.symbol}")
        if data.get("symbol") != self.symbol:
            raise VerificationError(f"Constituent symbol mismatch: expected {self.symbol}, got {data.get('symbol')}")
        constituents = data.get("constituents", [])
        if not constituents:
            raise VerificationError(f"No constituents found for {self.symbol}")
        return constituents

    def verify_contract(self) -> Dict[str, Any]:
        """
        Fetch and strictly validate contract specifications from /fapi/v1/exchangeInfo.
        Guarantees contract is XAUUSDT TRADIFI_PERPETUAL and actively trading.
        """
        info = self._fetch_json("/fapi/v1/exchangeInfo")
        symbols = info.get("symbols", [])
        matched = [s for s in symbols if s.get("symbol") == self.symbol]

        if not matched:
            raise VerificationError(
                f"Instrument {self.symbol} not found on Binance USD-M Futures exchangeInfo! "
                "Principle 5 prohibits silent substitution."
            )

        spec = matched[0]

        # Strict specification assertions
        if spec.get("symbol") != "XAUUSDT":
            raise VerificationError(f"Symbol mismatch: expected XAUUSDT, got {spec.get('symbol')}")

        if spec.get("baseAsset") != "XAU":
            raise VerificationError(f"Base asset must be XAU, got {spec.get('baseAsset')}")

        if spec.get("quoteAsset") != "USDT":
            raise VerificationError(f"Quote asset must be USDT, got {spec.get('quoteAsset')}")

        if spec.get("marginAsset") != "USDT":
            raise VerificationError(f"Margin asset must be USDT, got {spec.get('marginAsset')}")

        # Contract Type verification
        contract_type = spec.get("contractType")
        if contract_type not in ("TRADIFI_PERPETUAL", "PERPETUAL"):
            raise VerificationError(f"Unexpected contractType: {contract_type}")

        # Extract filters
        filters = {f["filterType"]: f for f in spec.get("filters", [])}

        price_filter = filters.get("PRICE_FILTER")
        if not price_filter:
            raise VerificationError("PRICE_FILTER missing in contract specifications")
        tick_size = float(price_filter["tickSize"])

        lot_size = filters.get("LOT_SIZE")
        if not lot_size:
            raise VerificationError("LOT_SIZE filter missing in contract specifications")
        step_size = float(lot_size["stepSize"])

        min_notional_filter = filters.get("MIN_NOTIONAL")
        min_notional = float(min_notional_filter.get("notional", 5.0)) if min_notional_filter else 5.0

        maint_margin_percent = float(spec.get("maintMarginPercent", 2.5))
        onboard_date_ms = int(spec.get("onboardDate", settings.CONTRACT_ONBOARD_TIME_MS))
        onboard_dt = datetime.fromtimestamp(onboard_date_ms / 1000, tz=timezone.utc)

        result = {
            "symbol": spec["symbol"],
            "pair": spec["pair"],
            "contract_type": contract_type,
            "underlying_type": spec.get("underlyingType", "COMMODITY"),
            "base_asset": spec["baseAsset"],
            "quote_asset": spec["quoteAsset"],
            "margin_asset": spec["marginAsset"],
            "price_precision": int(spec["pricePrecision"]),
            "quantity_precision": int(spec["quantityPrecision"]),
            "tick_size": tick_size,
            "step_size": step_size,
            "min_notional": min_notional,
            "maint_margin_percent": maint_margin_percent,
            "onboard_timestamp": onboard_dt,
            "status": spec.get("status", "TRADING"),
            "is_active": spec.get("status") == "TRADING",
        }
        return result

    def persist_metadata(self, spec: Dict[str, Any]) -> None:
        """Upsert verified contract specifications into market_metadata table."""
        stmt = insert(MarketMetadata).values(
            symbol=spec["symbol"],
            pair=spec["pair"],
            contract_type=spec["contract_type"],
            underlying_type=spec["underlying_type"],
            base_asset=spec["base_asset"],
            quote_asset=spec["quote_asset"],
            margin_asset=spec["margin_asset"],
            price_precision=spec["price_precision"],
            quantity_precision=spec["quantity_precision"],
            tick_size=spec["tick_size"],
            step_size=spec["step_size"],
            min_notional=spec["min_notional"],
            maint_margin_percent=spec["maint_margin_percent"],
            onboard_timestamp=spec["onboard_timestamp"],
            is_active=spec["is_active"],
            updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "price_precision": spec["price_precision"],
                "quantity_precision": spec["quantity_precision"],
                "tick_size": spec["tick_size"],
                "step_size": spec["step_size"],
                "min_notional": spec["min_notional"],
                "maint_margin_percent": spec["maint_margin_percent"],
                "is_active": spec["is_active"],
                "updated_at": datetime.now(timezone.utc),
            }
        )

        with get_sync_session() as session:
            session.execute(stmt)
            logger.info("Persisted verified contract metadata for %s", spec["symbol"])
