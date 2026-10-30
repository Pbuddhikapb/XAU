"""
Integration and unit tests for ExchangeVerifier.
Verifies contract rules, filters, constituents, and database persistence against Binance Futures.
"""

import pytest
from sqlalchemy import select

from backend.data.exchange_verifier import ExchangeVerifier, VerificationError
from backend.database import get_sync_session
from backend.models.tables import MarketMetadata


def test_exchange_verifier_live():
    verifier = ExchangeVerifier()

    # 1. Server time
    server_time = verifier.verify_server_time()
    assert isinstance(server_time, int)
    assert server_time > 1700000000000

    # 2. Contract specifications
    spec = verifier.verify_contract()
    assert spec["symbol"] == "XAUUSDT"
    assert spec["pair"] == "XAUUSDT"
    assert spec["contract_type"] in ("TRADIFI_PERPETUAL", "PERPETUAL")
    assert spec["base_asset"] == "XAU"
    assert spec["quote_asset"] == "USDT"
    assert spec["tick_size"] == 0.01
    assert spec["step_size"] == 0.001
    assert spec["min_notional"] == 5.0
    assert spec["status"] == "TRADING"

    # 3. Constituents
    constituents = verifier.verify_constituents()
    assert len(constituents) >= 2
    exchanges = [c["exchange"] for c in constituents]
    assert "dxfeed" in exchanges or "massive" in exchanges

    # 4. Persistence into PostgreSQL
    verifier.persist_metadata(spec)

    with get_sync_session() as session:
        meta = session.execute(
            select(MarketMetadata).where(MarketMetadata.symbol == "XAUUSDT")
        ).scalar_one()

        assert meta.symbol == "XAUUSDT"
        assert float(meta.tick_size) == 0.01
        assert float(meta.step_size) == 0.001
        assert meta.is_active is True

    # 5. Funding history persistence
    funding_count = verifier.fetch_and_persist_funding_history(limit=5)
    assert funding_count >= 1

    from backend.models.tables import FundingHistory
    with get_sync_session() as session:
        records = session.execute(
            select(FundingHistory).where(FundingHistory.symbol == "XAUUSDT")
        ).scalars().all()
        assert len(records) >= 1
        assert records[0].funding_rate is not None



def test_exchange_verifier_invalid_symbol():
    verifier = ExchangeVerifier()
    verifier.symbol = "INVALID_SYMBOL_99"

    with pytest.raises(VerificationError) as exc_info:
        verifier.verify_contract()
    assert "Principle 5 prohibits silent substitution" in str(exc_info.value)
