import httpx
import pytest

from trip_planner.config import get_settings
from trip_planner.services import http_client


async def test_get_http_client_raises_before_open() -> None:
    await http_client.close_http_client()

    with pytest.raises(RuntimeError):
        http_client.get_http_client()


async def test_open_creates_shared_client_and_get_returns_it() -> None:
    await http_client.open_http_client()

    try:
        client = http_client.get_http_client()
        assert isinstance(client, httpx.AsyncClient)
    finally:
        await http_client.close_http_client()


async def test_shared_client_uses_configured_granular_timeouts() -> None:
    settings = get_settings()
    await http_client.open_http_client()

    try:
        timeout = http_client.get_http_client().timeout
        assert timeout.connect == settings.http_connect_timeout
        assert timeout.read == settings.http_read_timeout
        assert timeout.write == settings.http_write_timeout
        assert timeout.pool == settings.http_pool_timeout
    finally:
        await http_client.close_http_client()


async def test_open_is_idempotent_and_reuses_the_same_client() -> None:
    await http_client.open_http_client()

    try:
        first = http_client.get_http_client()
        await http_client.open_http_client()
        second = http_client.get_http_client()
        assert first is second
    finally:
        await http_client.close_http_client()


async def test_close_disposes_client_so_get_raises_again() -> None:
    await http_client.open_http_client()
    await http_client.close_http_client()

    with pytest.raises(RuntimeError):
        http_client.get_http_client()
