"""Lifespan-managed, pooled httpx.AsyncClient shared by all outbound providers."""
import httpx

_DEFAULT_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None


async def open_http_client() -> None:
    """Create the shared pooled AsyncClient. Called once during app startup."""
    global _client

    if _client is None:
        _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)


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
