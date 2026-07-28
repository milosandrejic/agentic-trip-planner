from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.services.liteapi_client import LiteApiClient, LiteApiError

_PATCH_CLIENT = "trip_planner.services.liteapi_client.httpx.AsyncClient"
_PATCH_SLEEP = "trip_planner.services.liteapi_client.asyncio.sleep"


def _make_response(json_data: object, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
    response.headers = {}
    return response


def _patch_http(responses: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
    """Return (mock_client_cls, mock_inner_client) with request side_effect set."""
    mock_client_cls = MagicMock()
    mock_inner = AsyncMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_inner.request = AsyncMock(side_effect=responses)
    return mock_client_cls, mock_inner


# --- get ---


async def test_get_returns_json_on_200() -> None:
    payload = {"data": [{"hotelId": "lp123"}]}
    mock_cls, _ = _patch_http([_make_response(payload, 200)])

    with patch(_PATCH_CLIENT, mock_cls):
        client = LiteApiClient()
        result = await client.get("/data/hotels", params={"limit": "3"})

    assert result == payload


# --- post ---


async def test_post_returns_json_on_200() -> None:
    payload: dict[str, object] = {"data": {"rates": []}}
    mock_cls, _ = _patch_http([_make_response(payload, 200)])

    with patch(_PATCH_CLIENT, mock_cls):
        client = LiteApiClient()
        result = await client.post("/hotels/rates", {"hotelIds": []})

    assert result == payload


# --- error handling ---


async def test_raises_liteapi_error_on_422() -> None:
    error_body = {"error": {"code": 2001, "description": "Invalid city code"}}
    mock_cls, _ = _patch_http([_make_response(error_body, 422)])

    with patch(_PATCH_CLIENT, mock_cls):
        client = LiteApiClient()
        with pytest.raises(LiteApiError) as exc_info:
            await client.post("/hotels/rates", {"hotelIds": []})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid city code"


async def test_raises_liteapi_error_with_text_when_no_error_object() -> None:
    mock_response = _make_response({}, 500)
    mock_response.text = "Internal Server Error"
    mock_cls, _ = _patch_http([mock_response, mock_response, mock_response])

    with (
        patch(_PATCH_CLIENT, mock_cls),
        patch(_PATCH_SLEEP, new_callable=AsyncMock),
    ):
        client = LiteApiClient()
        with pytest.raises(LiteApiError) as exc_info:
            await client.get("/data/hotels")

    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in exc_info.value.detail


# --- retry logic ---


async def test_retries_on_429_then_succeeds() -> None:
    rate_limited = _make_response({}, 429)
    rate_limited.headers = {}
    success = _make_response({"data": "ok"}, 200)
    mock_cls, mock_inner = _patch_http([rate_limited, success])

    with (
        patch(_PATCH_CLIENT, mock_cls),
        patch(_PATCH_SLEEP, new_callable=AsyncMock),
    ):
        client = LiteApiClient()
        result = await client.get("/data/hotels")

    assert result == {"data": "ok"}
    assert mock_inner.request.call_count == 2


async def test_retries_on_5xx_then_succeeds() -> None:
    server_error = _make_response({}, 503)
    server_error.headers = {}
    success = _make_response({"data": "ok"}, 200)
    mock_cls, mock_inner = _patch_http([server_error, success])

    with (
        patch(_PATCH_CLIENT, mock_cls),
        patch(_PATCH_SLEEP, new_callable=AsyncMock),
    ):
        client = LiteApiClient()
        result = await client.get("/data/hotels")

    assert result == {"data": "ok"}
    assert mock_inner.request.call_count == 2


async def test_raises_after_max_retries_exhausted() -> None:
    error_body = {"error": {"code": 5000, "description": "Service unavailable"}}
    server_error = _make_response(error_body, 503)
    server_error.headers = {}
    mock_cls, mock_inner = _patch_http([server_error, server_error, server_error])

    with (
        patch(_PATCH_CLIENT, mock_cls),
        patch(_PATCH_SLEEP, new_callable=AsyncMock),
    ):
        client = LiteApiClient()
        with pytest.raises(LiteApiError) as exc_info:
            await client.get("/data/hotels")

    assert exc_info.value.status_code == 503
    assert mock_inner.request.call_count == 3


async def test_uses_retry_after_header_for_wait_duration() -> None:
    rate_limited = _make_response({}, 429)
    rate_limited.headers = {"Retry-After": "5"}
    success = _make_response({"data": "ok"}, 200)
    mock_cls, _ = _patch_http([rate_limited, success])

    with (
        patch(_PATCH_CLIENT, mock_cls),
        patch(_PATCH_SLEEP, new_callable=AsyncMock) as mock_sleep,
    ):
        client = LiteApiClient()
        await client.get("/data/hotels")

    mock_sleep.assert_awaited_once_with(5.0)
