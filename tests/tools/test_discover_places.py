# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places import ProviderPlace
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

_GEOAPIFY_PLACES_RESPONSE = {
    "features": [
        {
            "properties": {
                "name": "Louvre Museum",
                "categories": ["entertainment.museum", "tourism.sights"],
                "formatted": "Rue de Rivoli, 75001 Paris",
                "place_id": "abc123",
            }
        },
    ]
}

_LOUVRE = ProviderPlace(
    place_id="abc123",
    name="Louvre Museum",
    address="Rue de Rivoli, 75001 Paris",
    types=["museum", "tourist_attraction"],
)
_ORSAY = ProviderPlace(
    place_id="def456",
    name="Musée d'Orsay",
    address="1 Rue de la Légion d'Honneur, 75007 Paris",
    types=["museum"],
)

_PATCH_SEARCH = "trip_planner.tools.discover_places._provider.search_places"


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


# --- _geocode / _search_places (Geoapify fallback, kept unwired) ---


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


async def test_search_places_returns_properties_list() -> None:
    mock_cls = _patch_client(_make_mock_response(_GEOAPIFY_PLACES_RESPONSE))

    with patch("trip_planner.tools.discover_places.httpx.AsyncClient", mock_cls):
        places = await _search_places(48.8566, 2.3522, "tourism.sights", 5000, 5)

    assert len(places) == 1
    assert places[0]["name"] == "Louvre Museum"


async def test_search_places_returns_empty_when_no_features() -> None:
    mock_cls = _patch_client(_make_mock_response({"features": []}))

    with patch("trip_planner.tools.discover_places.httpx.AsyncClient", mock_cls):
        places = await _search_places(48.8566, 2.3522, "tourism.sights", 5000, 5)

    assert places == []


# --- _format_places (Google Places, default) ---


def test_format_places_returns_no_places_message_when_empty() -> None:
    result = _format_places([])

    assert result == "No places found for these categories and location."


def test_format_places_includes_name_categories_and_address() -> None:
    result = _format_places([_LOUVRE, _ORSAY])

    assert "Louvre Museum" in result
    assert "museum" in result
    assert "Rue de Rivoli, 75001 Paris" in result


def test_format_places_handles_missing_categories() -> None:
    result = _format_places([ProviderPlace(name="Unnamed place")])

    assert "Unnamed place" in result


# --- discover_places_tool ---


async def test_discover_places_tool_returns_formatted_string_on_success() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [_LOUVRE, _ORSAY]

        result = await discover_places_tool.ainvoke(
            {"city": "Paris", "categories": "museums"}
        )

    assert "Louvre Museum" in result
    assert "Musée d'Orsay" in result


async def test_discover_places_tool_ranks_closed_places_below_operational_ones() -> None:
    closed = _LOUVRE.model_copy(update={"rating": 4.9, "business_status": "CLOSED_PERMANENTLY"})
    operational = _ORSAY.model_copy(update={"rating": 3.0, "business_status": "OPERATIONAL"})

    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [closed, operational]

        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "museums"})
        )

    result = message.artifact
    assert result.data is not None
    assert result.data.places[0].name == "Musée d'Orsay"


async def test_discover_places_tool_returns_error_string_on_provider_error() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = GooglePlacesError(429, "rate limited")

        result = await discover_places_tool.ainvoke({"city": "Paris", "categories": "museums"})

    assert "unavailable" in result
    assert "rate limited" in result


async def test_discover_places_tool_returns_error_string_on_unexpected_response() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = KeyError("places")

        result = await discover_places_tool.ainvoke({"city": "Paris", "categories": "museums"})

    assert "Unexpected response" in result


# --- discover_places_tool ToolResult envelope ---


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "discover_places_tool", "args": args, "id": "call_1"}


async def test_discover_places_tool_success_envelope_carries_typed_places() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [_LOUVRE, _ORSAY]

        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "museums"})
        )

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "google-places"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert len(result.data.places) == 2


async def test_discover_places_tool_empty_envelope_when_no_places() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []

        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "museums"})
        )

    result = message.artifact
    assert result.status == ToolStatus.EMPTY
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is None
    assert result.latency_ms is not None


async def test_discover_places_tool_error_envelope_is_retryable_on_provider_error() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = GooglePlacesError(503, "unavailable")

        message = await discover_places_tool.ainvoke(
            _tool_call({"city": "Paris", "categories": "museums"})
        )

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True
