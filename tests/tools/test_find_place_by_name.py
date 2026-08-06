# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, patch

from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places import ProviderPlace
from trip_planner.services.types import ToolStatus
from trip_planner.tools.find_place_by_name import _format_results, find_place_by_name_tool

_EIFFEL_TOWER = ProviderPlace(
    place_id="ChIJLU7jZClu5kcR4PcOOO6p3I0",
    name="Eiffel Tower",
    address="Av. Gustave Eiffel, 75007 Paris, France",
    rating=4.7,
    user_rating_count=400000,
)
_EIFFEL_TOWER_RESTAURANT = ProviderPlace(
    place_id="ChIJabc456",
    name="Eiffel Tower Restaurant",
    address="1st Floor, Eiffel Tower, Paris",
    rating=4.1,
)

_PATCH_SEARCH = "trip_planner.tools.find_place_by_name._provider.search_places"


# --- _format_results ---


def test_format_results_returns_no_places_message_when_empty() -> None:
    result = _format_results([])

    assert result == "No places found for this query."


def test_format_results_includes_place_id_name_address_and_rating() -> None:
    result = _format_results([_EIFFEL_TOWER, _EIFFEL_TOWER_RESTAURANT])

    assert "Eiffel Tower" in result
    assert "ChIJLU7jZClu5kcR4PcOOO6p3I0" in result
    assert "Av. Gustave Eiffel, 75007 Paris, France" in result
    assert "4.7 (400000 reviews)" in result


def test_format_results_rating_without_count() -> None:
    result = _format_results([_EIFFEL_TOWER_RESTAURANT])

    assert "Rating: 4.1" in result
    assert "reviews" not in result


def test_format_results_handles_missing_place_id() -> None:
    result = _format_results([ProviderPlace(name="Somewhere")])

    assert "Somewhere" in result
    assert "place_id: " in result


# --- find_place_by_name_tool ---


async def test_find_place_by_name_tool_returns_formatted_string_on_success() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [_EIFFEL_TOWER, _EIFFEL_TOWER_RESTAURANT]

        result = await find_place_by_name_tool.ainvoke({"query": "Eiffel Tower"})

    assert "Eiffel Tower" in result
    assert "ChIJLU7jZClu5kcR4PcOOO6p3I0" in result


async def test_find_place_by_name_tool_returns_no_places_when_empty() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []

        result = await find_place_by_name_tool.ainvoke({"query": "Nonexistent place xyz"})

    assert result == "No places found for this query."


async def test_find_place_by_name_tool_returns_error_string_on_provider_error() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = GooglePlacesError(429, "rate limited")

        result = await find_place_by_name_tool.ainvoke({"query": "Eiffel Tower"})

    assert "unavailable" in result
    assert "rate limited" in result


async def test_find_place_by_name_tool_returns_error_string_on_unexpected_response() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = KeyError("places")

        result = await find_place_by_name_tool.ainvoke({"query": "Eiffel Tower"})

    assert "Unexpected response" in result


# --- find_place_by_name_tool ToolResult envelope ---


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "find_place_by_name_tool", "args": args, "id": "call_1"}


async def test_find_place_by_name_tool_success_envelope_carries_typed_places() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [_EIFFEL_TOWER, _EIFFEL_TOWER_RESTAURANT]

        message = await find_place_by_name_tool.ainvoke(_tool_call({"query": "Eiffel Tower"}))

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "google-places"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert len(result.data.places) == 2


async def test_find_place_by_name_tool_empty_envelope_when_no_places() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []

        message = await find_place_by_name_tool.ainvoke(_tool_call({"query": "Nonexistent xyz"}))

    result = message.artifact
    assert result.status == ToolStatus.EMPTY
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is None
    assert result.latency_ms is not None


async def test_find_place_by_name_tool_error_envelope_is_retryable_on_provider_error() -> None:
    with patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = GooglePlacesError(503, "unavailable")

        message = await find_place_by_name_tool.ainvoke(_tool_call({"query": "Eiffel Tower"}))

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True
