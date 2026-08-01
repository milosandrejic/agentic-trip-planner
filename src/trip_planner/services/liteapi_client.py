"""Async HTTP client for the LiteAPI hotel API with retry and rate-limit handling."""
import asyncio
from typing import Any

import httpx

from trip_planner.config import get_settings
from trip_planner.services.http_client import get_http_client

_BASE_URL = "https://api.liteapi.travel/v3.0"
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; wait doubles on each retry
_UNAVAILABLE_STATUS = 503  # synthetic code when the API can't be reached at all

# Transient transport failures worth retrying: refused connects, timeouts, and resets.
_RETRIABLE_NETWORK_ERRORS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

_settings = get_settings()


class LiteApiError(Exception):
    """Raised when the LiteAPI returns an unrecoverable error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        """Initialise with the HTTP status code and LiteAPI error detail."""
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"LiteAPI error {status_code}: {detail}")


class LiteApiClient:
    """Async wrapper around the LiteAPI REST API.

    Handles X-API-Key auth, retry on 429 / 5xx responses, and respects the
    Retry-After header when rate-limited.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        """Initialise with the LiteAPI key and an optional injected HTTP client.

        When no client is supplied, the shared pooled client is resolved per request.
        """
        self._http_client = http_client
        self._headers = {
            "X-API-Key": _settings.liteapi_key,
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
        """Execute the request, retrying on transient network, 429, and 5xx failures.

        Network errors (connect failures, timeouts, resets) and 429 / 5xx responses
        are retried with exponential backoff; waits honour Retry-After when present.
        A network failure that outlives every retry surfaces as a LiteApiError so
        callers handle it the same way as an HTTP error.
        """
        url = f"{_BASE_URL}{path}"
        client = self._http_client or get_http_client()

        for attempt in range(_MAX_RETRIES):
            is_last_attempt = attempt == _MAX_RETRIES - 1

            try:
                response = await client.request(
                    method, url, headers=self._headers, params=params, json=json
                )
            except _RETRIABLE_NETWORK_ERRORS as exc:
                if is_last_attempt:
                    raise LiteApiError(_UNAVAILABLE_STATUS, f"network error: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                continue

            is_rate_limited = response.status_code == 429
            is_server_error = response.status_code >= 500
            should_retry = is_rate_limited or is_server_error

            if not should_retry:
                self._raise_for_liteapi_error(response)
                return response.json()  # type: ignore[no-any-return]

            if is_last_attempt:
                self._raise_for_liteapi_error(response)

            retry_after = response.headers.get("Retry-After")
            wait_seconds = _BACKOFF_BASE * (2**attempt)

            if retry_after is not None:
                wait_seconds = float(retry_after)

            await asyncio.sleep(wait_seconds)

        # Never reached; loop always returns or raises before exhausting retries.
        raise RuntimeError("LiteApiClient._request exited retry loop without returning.")

    def _raise_for_liteapi_error(self, response: httpx.Response) -> None:
        """Raise LiteApiError if the response indicates a failure."""
        is_error = response.status_code >= 400
        if not is_error:
            return

        raise LiteApiError(
            status_code=response.status_code, detail=self._error_detail(response)
        )

    def _error_detail(self, response: httpx.Response) -> str:
        """Extract a human-readable error detail, tolerating non-JSON bodies."""
        try:
            parsed: object = response.json()
        except ValueError:
            return response.text

        if not isinstance(parsed, dict):
            return response.text

        body: dict[str, Any] = parsed  # type: ignore[assignment]
        error: dict[str, Any] = body.get("error", {})  # type: ignore[assignment]
        detail = error.get("description", response.text)

        return str(detail)
