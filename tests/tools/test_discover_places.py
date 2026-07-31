# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.services.types import ToolStatus
from trip_planner.tools.discover_places import (
    _format_places,
    _geocode,
    _search_places,
    discover_places_tool,
)

_GEOCODE_RESPONSE = {
    "features": [
        {"properties": {"lat": 48.8566, "lon": 2.3522, "city": "Paris"}},
    ]
}

_GEOCODE_EMPTY_RESPONSE: dict[str, list[object]] = {"features": []}

_PLACES_RESPONSE = {
    "features": [
        {
            "properties": {
                "name": "Louvre Museum",
                "categories": ["entertainment.museum", "tourism.sights"],
                "formatted": "Rue de Rivoli, 75001 Paris",
                "place_id": "abc123",
            }
        },
        {
            "properties": {
                "name": "Musée d'Orsay",
                "categories": ["entertainment.museum"],
                "formatted": "1 Rue de la Légion d'Honneur, 75007 Paris",
                "place_id": "def456",
            }
        },
    ]
}


def _make_mock_response(json_data: object, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


def _patch_client(mock_response: MagicMock) -> MagicMock:
    """Return a mocked httpx.AsyncClient class whose get() yields mock_response."""
    mock_client_cls = MagicMock()
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client_cls


# --- _geocode ---


async def test_geocode_returns_lat_lon() -> None:
    mock_cls = _patch_client(_make_mock_response(_GEOCODE_RESPONSE))

    with patch("trip_planner.tools.discover_places.httpx.AsyncClient", mock_cls):
        lat, lon = await _geocode("Paris")

    assert lat == 48.8566
    assert lon == 2.3522


async def test_geocode_raises_for_unknown_city() -> None:
    mock_cls = _patch_client(_make_mock_response(_GEOCODE_EMPTY_RESPONSE))

    with patch("trip_planner.tools.discover_places.httpx.AsyncClient", mock_cls):
        with pytest.raises(ValueError, match="City not found"):
            await _geocode("Atlantis")


# --- _search_places ---


async def test_search_places_returns_properties_list() -> None:
    mock_cls = _patch_client(_make_mock_response(_PLACES_RESPONSE))

    with patch("trip_planner.tools.discover_places.httpx.AsyncClient", mock_cls):
        places = await _search_places(48.8566, 2.3522, "tourism.sights", 5000, 5)

    assert len(places) == 2
    assert places[0]["name"] == "Louvre Museum"


async def test_search_places_returns_empty_when_no_features() -> None:
    mock_cls = _patch_client(_make_mock_response({"features": []}))

    with patch("trip_planner.tools.discover_places.httpx.AsyncClient", mock_cls):
        places = await _search_places(48.8566, 2.3522, "tourism.sights", 5000, 5)

    assert places == []


# --- _format_places ---


def test_format_places_returns_no_places_message_when_empty() -> None:
    result = _format_places([])

    assert result == "No places found for these categories and location."


def test_format_places_includes_name_categories_and_address() -> None:
    places = [
        _PLACES_RESPONSE["features"][0]["properties"],
        _PLACES_RESPONSE["features"][1]["properties"],
    ]
    result = _format_places(places)

    assert "Louvre Museum" in result
    assert "entertainment.museum" in result
    assert "Rue de Rivoli, 75001 Paris" in result


def test_format_places_handles_missing_name() -> None:
    result = _format_places([{"categories": ["tourism.sights"]}])

    assert "Unnamed place" in result


# --- discover_places_tool ---


async def test_discover_places_tool_returns_formatted_string_on_success() -> None:
    with (
        patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo,
        patch("trip_planner.tools.discover_places._search_places", new_callable=AsyncMock) as mock_search,
    ):
        mock_geo.return_value = (48.8566, 2.3522)
        mock_search.return_value = [
            _PLACES_RESPONSE["features"][0]["properties"],
            _PLACES_RESPONSE["features"][1]["properties"],
        ]

        result = await discover_places_tool.ainvoke(
            {"city": "Paris", "categories": "entertainment.museum"}
        )

    assert "Louvre Museum" in result
    assert "Musée d'Orsay" in result


async def test_discover_places_tool_returns_error_string_for_unknown_city() -> None:
    with patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo:
        mock_geo.side_effect = ValueError("City not found: 'Atlantis'")

        result = await discover_places_tool.ainvoke(
            {"city": "Atlantis", "categories": "tourism.sights"}
        )

    assert "unavailable" in result
    assert "Atlantis" in result


async def test_discover_places_tool_returns_error_string_on_http_error() -> None:
    with (
        patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo,
        patch("trip_planner.tools.discover_places._search_places", new_callable=AsyncMock) as mock_search,
    ):
        mock_geo.return_value = (48.8566, 2.3522)
        mock_search.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=MagicMock(status_code=429)
        )

        result = await discover_places_tool.ainvoke(
            {"city": "Paris", "categories": "tourism.sights"}
        )

    assert "unavailable" in result
    assert "429" in result


# --- discover_places_tool ToolResult envelope ---


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "discover_places_tool", "args": args, "id": "call_1"}


async def test_discover_places_tool_success_envelope_carries_typed_places() -> None:
    with (
        patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo,
        patch("trip_planner.tools.discover_places._search_places", new_callable=AsyncMock) as mock_search,
    ):
        mock_geo.return_value = (48.8566, 2.3522)
        mock_search.return_value = [
            _PLACES_RESPONSE["features"][0]["properties"],
            _PLACES_RESPONSE["features"][1]["properties"],
        ]
        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "entertainment.museum"})
        )

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "geoapify"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert len(result.data.places) == 2


async def test_discover_places_tool_empty_envelope_when_no_places() -> None:
    with (
        patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo,
        patch("trip_planner.tools.discover_places._search_places", new_callable=AsyncMock) as mock_search,
    ):
        mock_geo.return_value = (48.8566, 2.3522)
        mock_search.return_value = []
        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "tourism.sights"})
        )

    result = message.artifact
    assert result.status == ToolStatus.EMPTY
    assert result.provider == "geoapify"
    assert result.data is None
    assert result.error is None
    assert result.latency_ms is not None


async def test_discover_places_tool_error_envelope_is_retryable_on_http_error() -> None:
    with (
        patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo,
        patch("trip_planner.tools.discover_places._search_places", new_callable=AsyncMock) as mock_search,
    ):
        mock_geo.return_value = (48.8566, 2.3522)
        mock_search.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=MagicMock(status_code=503)
        )
        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "tourism.sights"})
        )

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "geoapify"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True


async def test_discover_places_tool_error_envelope_not_retryable_for_unknown_city() -> None:
    with patch("trip_planner.tools.discover_places._geocode", new_callable=AsyncMock) as mock_geo:
        mock_geo.side_effect = ValueError("City not found: 'Atlantis'")
        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Atlantis", "categories": "tourism.sights"})
        )

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.error is not None
    assert result.error.retryable is False
