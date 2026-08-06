from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.services.google_places_client import GooglePlacesClient, GooglePlacesError

_PATCH_SLEEP = "trip_planner.services.google_places_client.asyncio.sleep"
_FIELD_MASK = "id,displayName"


def _make_response(json_data: object, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
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
    payload = {"id": "place-1", "displayName": {"text": "Eiffel Tower"}}
    mock_client = _make_client([_make_response(payload, 200)])

    client = GooglePlacesClient(http_client=mock_client)
    result = await client.get("/places/place-1", _FIELD_MASK)

    assert result == payload
    _, kwargs = mock_client.request.call_args
    assert kwargs["headers"]["X-Goog-FieldMask"] == _FIELD_MASK


async def test_falls_back_to_shared_pooled_client_when_none_injected() -> None:
    shared_client = _make_client([_make_response({"places": []}, 200)])

    with patch(
        "trip_planner.services.google_places_client.get_http_client", return_value=shared_client
    ) as mock_get:
        client = GooglePlacesClient()
        result = await client.get("/places/place-1", _FIELD_MASK)

    assert result == {"places": []}
    mock_get.assert_called_once_with()
    shared_client.request.assert_awaited_once()


# --- post ---


async def test_post_returns_json_on_200() -> None:
    payload: dict[str, object] = {"places": [{"id": "place-1"}]}
    mock_client = _make_client([_make_response(payload, 200)])

    client = GooglePlacesClient(http_client=mock_client)
    result = await client.post("/places:searchText", {"textQuery": "Eiffel Tower"}, _FIELD_MASK)

    assert result == payload


# --- error handling ---


async def test_raises_google_places_error_on_400() -> None:
    error_body = {"error": {"code": 400, "message": "Invalid field mask"}}
    mock_client = _make_client([_make_response(error_body, 400)])

    client = GooglePlacesClient(http_client=mock_client)
    with pytest.raises(GooglePlacesError) as exc_info:
        await client.post("/places:searchText", {}, _FIELD_MASK)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid field mask"


async def test_raises_google_places_error_with_text_when_no_error_object() -> None:
    mock_response = _make_response({}, 500)
    mock_response.text = "Internal Server Error"
    mock_client = _make_client([mock_response, mock_response, mock_response])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        with pytest.raises(GooglePlacesError) as exc_info:
            await client.get("/places/place-1", _FIELD_MASK)

    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in exc_info.value.detail


# --- retry logic ---


async def test_retries_on_429_then_succeeds() -> None:
    rate_limited = _make_response({}, 429)
    success = _make_response({"id": "place-1"}, 200)
    mock_client = _make_client([rate_limited, success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        result = await client.get("/places/place-1", _FIELD_MASK)

    assert result == {"id": "place-1"}
    assert mock_client.request.call_count == 2


async def test_retries_on_5xx_then_succeeds() -> None:
    server_error = _make_response({}, 503)
    success = _make_response({"id": "place-1"}, 200)
    mock_client = _make_client([server_error, success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        result = await client.get("/places/place-1", _FIELD_MASK)

    assert result == {"id": "place-1"}
    assert mock_client.request.call_count == 2


async def test_raises_after_max_retries_exhausted() -> None:
    error_body = {"error": {"code": 503, "message": "Service unavailable"}}
    server_error = _make_response(error_body, 503)
    mock_client = _make_client([server_error, server_error, server_error])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        with pytest.raises(GooglePlacesError) as exc_info:
            await client.get("/places/place-1", _FIELD_MASK)

    assert exc_info.value.status_code == 503
    assert mock_client.request.call_count == 3


async def test_uses_retry_after_header_for_wait_duration() -> None:
    rate_limited = _make_response({}, 429)
    rate_limited.headers = {"Retry-After": "5"}
    success = _make_response({"id": "place-1"}, 200)
    mock_client = _make_client([rate_limited, success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock) as mock_sleep:
        client = GooglePlacesClient(http_client=mock_client)
        await client.get("/places/place-1", _FIELD_MASK)

    mock_sleep.assert_awaited_once_with(5.0)


# --- network resilience ---


async def test_retries_on_connect_error_then_succeeds() -> None:
    success = _make_response({"id": "place-1"}, 200)
    mock_client = _make_client([httpx.ConnectError("connection refused"), success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        result = await client.get("/places/place-1", _FIELD_MASK)

    assert result == {"id": "place-1"}
    assert mock_client.request.call_count == 2


async def test_retries_on_read_timeout_then_succeeds() -> None:
    success = _make_response({"id": "place-1"}, 200)
    mock_client = _make_client([httpx.ReadTimeout("timed out"), success])

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        result = await client.get("/places/place-1", _FIELD_MASK)

    assert result == {"id": "place-1"}
    assert mock_client.request.call_count == 2


async def test_raises_google_places_error_after_network_retries_exhausted() -> None:
    errors: list[object] = [httpx.ConnectError("connection reset")] * 3
    mock_client = _make_client(errors)

    with patch(_PATCH_SLEEP, new_callable=AsyncMock):
        client = GooglePlacesClient(http_client=mock_client)
        with pytest.raises(GooglePlacesError) as exc_info:
            await client.get("/places/place-1", _FIELD_MASK)

    assert exc_info.value.status_code == 503
    assert mock_client.request.call_count == 3
