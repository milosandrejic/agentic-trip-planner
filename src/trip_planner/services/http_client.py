"""Lifespan-managed, pooled httpx.AsyncClient shared by all outbound providers."""
import httpx

from trip_planner.config import get_settings

_settings = get_settings()

_client: httpx.AsyncClient | None = None


def _build_timeout() -> httpx.Timeout:
    """Build the central per-phase (connect/read/write/pool) timeout for every provider."""
    return httpx.Timeout(
        connect=_settings.http_connect_timeout,
        read=_settings.http_read_timeout,
        write=_settings.http_write_timeout,
        pool=_settings.http_pool_timeout,
    )


async def open_http_client() -> None:
    """Create the shared pooled AsyncClient. Called once during app startup."""
    global _client

    if _client is None:
        _client = httpx.AsyncClient(timeout=_build_timeout())


async def close_http_client() -> None:
    """Close the shared pooled AsyncClient. Called once during app shutdown."""
    global _client

    if _client is not None:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared pooled AsyncClient, raising if startup hasn't opened it."""
    if _client is None:
        raise RuntimeError("Shared HTTP client is not initialised; open it during app startup.")

    return _client
