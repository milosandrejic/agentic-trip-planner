"""Async HTTP client for the LiteAPI hotel API with retry and rate-limit handling."""
import asyncio
from typing import Any

import httpx

from trip_planner.config import get_settings

_BASE_URL = "https://api.liteapi.travel/v3.0"
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; wait doubles on each retry

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

    def __init__(self) -> None:
        """Initialise the client using the configured LiteAPI key."""
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
        """Execute the request, retrying on transient 429 and 5xx responses.

        Waits respect the Retry-After header when present; otherwise uses
        exponential backoff starting at _BACKOFF_BASE seconds.
        """
        url = f"{_BASE_URL}{path}"

        for attempt in range(_MAX_RETRIES):
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, url, headers=self._headers, params=params, json=json
                )

            is_rate_limited = response.status_code == 429
            is_server_error = response.status_code >= 500
            should_retry = is_rate_limited or is_server_error

            if not should_retry:
                self._raise_for_liteapi_error(response)
                return response.json()  # type: ignore[no-any-return]

            is_last_attempt = attempt == _MAX_RETRIES - 1

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

        body: dict[str, Any] = response.json()  # type: ignore[assignment]
        error: dict[str, Any] = body.get("error", {})  # type: ignore[assignment]

        detail = error.get("description", response.text)

        raise LiteApiError(status_code=response.status_code, detail=str(detail))
