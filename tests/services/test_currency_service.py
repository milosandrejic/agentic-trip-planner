from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from trip_planner.services.currency_service import CurrencyConverter, CurrencyError


def _client_returning(rates: dict[str, float]) -> AsyncMock:
    """Return a mock AsyncClient whose GET yields a Frankfurter-style rates payload."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"rates": rates})
    client = AsyncMock()
    client.get.return_value = response

    return client


async def test_rate_same_currency_short_circuits_without_http() -> None:
    client = AsyncMock()
    converter = CurrencyConverter(http_client=client)

    rate = await converter.rate("USD", "USD")

    assert rate == 1.0
    client.get.assert_not_called()


async def test_convert_applies_fetched_rate() -> None:
    converter = CurrencyConverter(http_client=_client_returning({"USD": 1.1}))

    result = await converter.convert(100.0, "EUR", "USD")

    assert result == 110.0


async def test_rate_is_cached_after_first_fetch() -> None:
    client = _client_returning({"USD": 1.2})
    converter = CurrencyConverter(http_client=client)

    await converter.rate("EUR", "USD")
    await converter.rate("EUR", "USD")

    assert client.get.call_count == 1


async def test_fetch_failure_raises_currency_error() -> None:
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("boom")
    converter = CurrencyConverter(http_client=client)

    with pytest.raises(CurrencyError):
        await converter.rate("EUR", "USD")


async def test_missing_rate_key_raises_currency_error() -> None:
    converter = CurrencyConverter(http_client=_client_returning({}))

    with pytest.raises(CurrencyError):
        await converter.rate("EUR", "USD")
