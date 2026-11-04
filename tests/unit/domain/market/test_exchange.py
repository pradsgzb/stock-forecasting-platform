import pytest

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainValidationError,
    UnsupportedExchangeError,
)
from stock_predictor.domain.market.exchange import Exchange, ExchangeCatalog
from stock_predictor.domain.market.identifiers import CountryCode, MarketIdentifierCode


def _exchange(mic: str = "XNYS", timezone: str = "America/New_York") -> Exchange:
    return Exchange(
        MarketIdentifierCode(mic),
        "Test Exchange",
        CountryCode("US"),
        timezone,
        mic,
    )


def test_exchange_exposes_zoneinfo() -> None:
    exchange = _exchange()
    assert exchange.timezone.key == "America/New_York"


def test_invalid_timezone_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="Unknown IANA"):
        _exchange(timezone="Not/AZone")


def test_catalog_rejects_duplicates_and_unknown_lookup() -> None:
    exchange = _exchange()
    with pytest.raises(DomainConflictError, match="Duplicate exchange"):
        ExchangeCatalog((exchange, exchange))

    catalog = ExchangeCatalog((exchange,))
    with pytest.raises(UnsupportedExchangeError):
        catalog.get(MarketIdentifierCode("XBAD"))
    assert catalog.all() == (exchange,)


def test_catalog_cannot_be_empty() -> None:
    with pytest.raises(DomainValidationError, match="cannot be empty"):
        ExchangeCatalog(())
