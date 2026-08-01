"""Async HTTP client for the Duffel Flights API with retry and rate-limit handling."""
import asyncio
from typing import Any

import httpx

from trip_planner.config import get_settings
from trip_planner.services.http_client import get_http_client

_BASE_URL = "https://api.duffel.com"
_DUFFEL_VERSION = "v2"
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; wait doubles on each retry

_settings = get_settings()


class DuffelError(Exception):
    """Raised when the Duffel API returns an unrecoverable error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        """Initialise with the HTTP status code and Duffel error detail."""
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Duffel API error {status_code}: {detail}")


class DuffelClient:
    """Async wrapper around the Duffel REST API.

    Handles Bearer-token auth, API versioning, retry on 429 / 5xx responses,
    and respects the Retry-After header when rate-limited.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        """Initialise with the Duffel API key and an optional injected HTTP client.

        When no client is supplied, the shared pooled client is resolved per request.
        """
        self._http_client = http_client
        self._headers = {
            "Authorization": f"Bearer {_settings.duffel_api_key}",
            "Duffel-Version": _DUFFEL_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    async def get(
        self, path: str, params: dict[str, str | int | float] | None = None
    ) -> dict[str, Any]:
        """Issue an authenticated GET request and return the parsed JSON body."""
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Issue an authenticated POST request and return the parsed JSON body."""
        return await self._request("POST", path, json=body)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str | int | float] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the request, retrying on transient 429 and 5xx responses.

        Waits respect the Retry-After header when present; otherwise uses
        exponential backoff starting at _BACKOFF_BASE seconds.
        """
        url = f"{_BASE_URL}{path}"
        client = self._http_client or get_http_client()

        for attempt in range(_MAX_RETRIES):
            response = await client.request(
                method, url, headers=self._headers, params=params, json=json
            )

            is_rate_limited = response.status_code == 429
            is_server_error = response.status_code >= 500
            should_retry = is_rate_limited or is_server_error

            if not should_retry:
                self._raise_for_duffel_error(response)
                return response.json()  # type: ignore[no-any-return]

            is_last_attempt = attempt == _MAX_RETRIES - 1

            if is_last_attempt:
                self._raise_for_duffel_error(response)

            retry_after = response.headers.get("Retry-After")
            wait_seconds = _BACKOFF_BASE * (2**attempt)

            if retry_after is not None:
                wait_seconds = float(retry_after)

            await asyncio.sleep(wait_seconds)

        # Never reached; loop always returns or raises before exhausting retries.
        raise RuntimeError("DuffelClient._request exited retry loop without returning.")

    def _raise_for_duffel_error(self, response: httpx.Response) -> None:
        """Raise DuffelError if the response indicates a failure."""
        is_error = response.status_code >= 400
        if not is_error:
            return

        body: dict[str, Any] = response.json()  # type: ignore[assignment]
        errors: list[dict[str, Any]] = body.get("errors", [])  # type: ignore[assignment]

        first_error = errors[0] if errors else {}
        detail = first_error.get("message", response.text)

        raise DuffelError(status_code=response.status_code, detail=str(detail))
