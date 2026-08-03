"""Async currency conversion backed by the Frankfurter FX API (ECB reference rates)."""
from typing import Any

import httpx

from trip_planner.services.http_client import get_http_client

_BASE_URL = "https://api.frankfurter.dev/v1"


class CurrencyError(Exception):
    """Raised when an exchange rate cannot be retrieved or parsed."""

    def __init__(self, detail: str) -> None:
        """Initialise with a human-readable failure detail."""
        self.detail = detail
        super().__init__(detail)


class CurrencyConverter:
    """Convert monetary amounts between currencies using cached ECB reference rates."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        """Initialise with an optional injected HTTP client and an empty per-pair rate cache."""
        self._http_client = http_client
        self._rate_cache: dict[tuple[str, str], float] = {}

    async def rate(self, from_currency: str, to_currency: str) -> float:
        """Return the exchange rate between two currencies, caching each pair after first fetch."""
        source = from_currency.upper()
        target = to_currency.upper()

        if source == target:
            return 1.0

        cached = self._rate_cache.get((source, target))

        if cached is not None:
            return cached

        fetched = await self._fetch_rate(source, target)
        self._rate_cache[(source, target)] = fetched

        return fetched

    async def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert an amount from one currency to another, rounded to two decimals."""
        rate = await self.rate(from_currency, to_currency)

        return round(amount * rate, 2)

    async def _fetch_rate(self, source: str, target: str) -> float:
        """Fetch the source-to-target rate from Frankfurter, raising CurrencyError on any failure."""
        try:
            client = self._http_client or get_http_client()
            response = await client.get(
                f"{_BASE_URL}/latest",
                params={"from": source, "to": target},
                follow_redirects=True,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            rate = payload["rates"][target]

            return float(rate)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise CurrencyError(f"could not fetch rate {source}->{target}: {exc}") from exc
