from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import AsyncClient

_GET_HTTP_CLIENT = "trip_planner.api.routes.places.get_http_client"


def _make_response(status_code: int, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = headers or {}
    return response


async def test_photo_redirects_to_googles_location_header(client: AsyncClient) -> None:
    upstream = _make_response(302, {"location": "https://lh3.googleusercontent.com/photo-1"})
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=upstream)

    with patch(_GET_HTTP_CLIENT, return_value=mock_client):
        response = await client.get(
            "/places/photos/places/place-1/photos/photo-1", follow_redirects=False
        )

    assert response.status_code == 302
    assert response.headers["location"] == "https://lh3.googleusercontent.com/photo-1"


async def test_photo_request_includes_reference_max_width_and_key(client: AsyncClient) -> None:
    upstream = _make_response(302, {"location": "https://lh3.googleusercontent.com/photo-1"})
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=upstream)

    with patch(_GET_HTTP_CLIENT, return_value=mock_client):
        await client.get(
            "/places/photos/places/place-1/photos/photo-1?max_width_px=400",
            follow_redirects=False,
        )

    args, kwargs = mock_client.get.call_args
    assert args[0] == "https://places.googleapis.com/v1/places/place-1/photos/photo-1/media"
    assert kwargs["params"]["maxWidthPx"] == 400
    assert "key" in kwargs["params"]
    assert kwargs["follow_redirects"] is False


async def test_photo_returns_502_when_google_does_not_redirect(client: AsyncClient) -> None:
    upstream = _make_response(404)
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=upstream)

    with patch(_GET_HTTP_CLIENT, return_value=mock_client):
        response = await client.get("/places/photos/places/place-1/photos/photo-1")

    assert response.status_code == 502


async def test_photo_returns_502_on_network_error(client: AsyncClient) -> None:
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))

    with patch(_GET_HTTP_CLIENT, return_value=mock_client):
        response = await client.get("/places/photos/places/place-1/photos/photo-1")

    assert response.status_code == 502
