from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.services.duffel_client import DuffelClient, DuffelError

_PATCH_SLEEP = "trip_planner.services.duffel_client.asyncio.sleep"


def _make_response(json_data: object, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
    response.headers = {}
    return response


def _make_non_json_response(text: str, status_code: int) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.side_effect = ValueError("no json to decode")
    response.text = text
    response.headers = {}
    return response


def _make_client(responses: Sequence[object]) -> MagicMock:
    """Return a mock pooled httpx.AsyncClient whose request() yields the given items.

    List items that are exceptions are raised; responses are returned.
    """
    client = MagicMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(side_effect=list(responses))
    return client


# --- get ---


async def test_get_returns_json_on_200() -> None:
    payload = {"data": {"id": "off_123"}}
    mock_client = _make_client([_make_response(payload, 200)])

    client = DuffelClient(http_client=mock_client)
    result = await client.get("/air/offers", params={"limit": "3"})

    assert result == payload


async def test_falls_back_to_shared_pooled_client_when_none_injected() -> None:
    shared_client = _make_client([_make_response({"data": "ok"}, 200)])

    with patch(
        "trip_planner.services.duffel_client.get_http_client", return_value=shared_client
    ) as mock_get:
        client = DuffelClient()
        result = await client.get("/air/offers")

    assert result == {"data": "ok"}
    mock_get.assert_called_once_with()
    shared_client.request.assert_awaited_once()


# --- post ---


async def test_post_returns_json_on_201() -> None:
    payload = {"data": {"id": "ofr_456"}}
    mock_client = _make_client([_make_response(payload, 201)])

    client = DuffelClient(http_client=mock_client)
    result = await client.post("/air/offer_requests", {"data": {}})

    assert result == payload


# --- error handling ---


async def test_raises_duffel_error_on_422() -> None:
    error_body = {"errors": [{"message": "Invalid IATA code"}]}
    mock_client = _make_client([_make_response(error_body, 422)])

    client = DuffelClient(http_client=mock_client)
    with pytest.raises(DuffelError) as exc_info:
        await client.post("/air/offer_requests", {"data": {}})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid IATA code"


async def test_raises_duffel_error_with_text_when_no_errors_array() -> None:
    mock_response = _make_response({}, 500)
    mock_response.text = "Internal Server Error"
    mock_client = _make_client([mock_response, mock_response, mock_response])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        with pytest.raises(DuffelError) as exc_info:
            await client.get("/air/offers")

    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in exc_info.value.detail


# --- retry logic ---


async def test_retries_on_429_then_succeeds() -> None:
    rate_limited = _make_response({}, 429)
    rate_limited.headers = {}
    success = _make_response({"data": "ok"}, 200)
    mock_client = _make_client([rate_limited, success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        result = await client.get("/air/offers")

    assert result == {"data": "ok"}
    assert mock_client.request.call_count == 2


async def test_retries_on_5xx_then_succeeds() -> None:
    server_error = _make_response({}, 503)
    server_error.headers = {}
    success = _make_response({"data": "ok"}, 200)
    mock_client = _make_client([server_error, success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        result = await client.get("/air/offers")

    assert result == {"data": "ok"}
    assert mock_client.request.call_count == 2


async def test_raises_after_max_retries_exhausted() -> None:
    error_body = {"errors": [{"message": "Service unavailable"}]}
    server_error = _make_response(error_body, 503)
    server_error.headers = {}
    mock_client = _make_client([server_error, server_error, server_error])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        with pytest.raises(DuffelError) as exc_info:
            await client.get("/air/offers")

    assert exc_info.value.status_code == 503
    assert mock_client.request.call_count == 3


async def test_uses_retry_after_header_for_wait_duration() -> None:
    rate_limited = _make_response({}, 429)
    rate_limited.headers = {"Retry-After": "5"}
    success = _make_response({"data": "ok"}, 200)
    mock_client = _make_client([rate_limited, success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock) as mock_sleep:
        client = DuffelClient(http_client=mock_client)
        await client.get("/air/offers")

    mock_sleep.assert_awaited_once_with(5.0)


# --- network resilience ---


async def test_retries_on_connect_error_then_succeeds() -> None:
    success = _make_response({"data": "ok"}, 200)
    mock_client = _make_client([httpx.ConnectError("connection refused"), success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        result = await client.get("/air/offers")

    assert result == {"data": "ok"}
    assert mock_client.request.call_count == 2


async def test_retries_on_read_timeout_then_succeeds() -> None:
    success = _make_response({"data": "ok"}, 200)
    mock_client = _make_client([httpx.ReadTimeout("timed out"), success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        result = await client.get("/air/offers")

    assert result == {"data": "ok"}
    assert mock_client.request.call_count == 2


async def test_raises_duffel_error_after_network_retries_exhausted() -> None:
    errors: list[object] = [httpx.ConnectError("connection reset")] * 3
    mock_client = _make_client(errors)

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = DuffelClient(http_client=mock_client)
        with pytest.raises(DuffelError) as exc_info:
            await client.get("/air/offers")

    assert exc_info.value.status_code == 503
    assert mock_client.request.call_count == 3


async def test_raises_duffel_error_with_text_on_non_json_error_body() -> None:
    non_json = _make_non_json_response("<html>Bad Request</html>", 400)
    mock_client = _make_client([non_json])

    client = DuffelClient(http_client=mock_client)
    with pytest.raises(DuffelError) as exc_info:
        await client.get("/air/offers")

    assert exc_info.value.status_code == 400
    assert "Bad Request" in exc_info.value.detail


async def test_raises_duffel_error_with_text_when_body_is_not_an_object() -> None:
    array_body = _make_response(["unexpected"], 400)
    mock_client = _make_client([array_body])

    client = DuffelClient(http_client=mock_client)
    with pytest.raises(DuffelError) as exc_info:
        await client.get("/air/offers")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == array_body.text
