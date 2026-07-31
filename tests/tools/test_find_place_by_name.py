# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from trip_planner.services.types import ToolStatus
from trip_planner.tools.find_place_by_name import _format_results, find_place_by_name_tool

_TEXT_SEARCH_RESPONSE = {
    "places": [
        {
            "id": "ChIJLU7jZClu5kcR4PcOOO6p3I0",
            "displayName": {"text": "Eiffel Tower", "languageCode": "en"},
            "formattedAddress": "Av. Gustave Eiffel, 75007 Paris, France",
            "rating": 4.7,
            "userRatingCount": 400000,
        },
        {
            "id": "ChIJabc456",
            "displayName": {"text": "Eiffel Tower Restaurant"},
            "formattedAddress": "1st Floor, Eiffel Tower, Paris",
            "rating": 4.1,
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
    """Return a mocked httpx.AsyncClient class whose post() yields mock_response."""
    mock_client_cls = MagicMock()
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client_cls


# --- _format_results ---


def test_format_results_returns_no_places_message_when_empty() -> None:
    result = _format_results([])

    assert result == "No places found for this query."


def test_format_results_includes_place_id_name_address_and_rating() -> None:
    result = _format_results(_TEXT_SEARCH_RESPONSE["places"])

    assert "Eiffel Tower" in result
    assert "ChIJLU7jZClu5kcR4PcOOO6p3I0" in result
    assert "Av. Gustave Eiffel, 75007 Paris, France" in result
    assert "4.7 (400000 reviews)" in result


def test_format_results_rating_without_count() -> None:
    result = _format_results([_TEXT_SEARCH_RESPONSE["places"][1]])

    assert "Rating: 4.1" in result
    assert "reviews" not in result


def test_format_results_handles_missing_display_name() -> None:
    result = _format_results([{"id": "ChIJxyz", "formattedAddress": "Somewhere"}])

    assert "Unknown place" in result
    assert "ChIJxyz" in result


# --- find_place_by_name_tool ---


async def test_find_place_by_name_tool_returns_formatted_string_on_success() -> None:
    mock_cls = _patch_client(_make_mock_response(_TEXT_SEARCH_RESPONSE))

    with patch("trip_planner.tools.find_place_by_name.httpx.AsyncClient", mock_cls):
        result = await find_place_by_name_tool.ainvoke({"query": "Eiffel Tower"})

    assert "Eiffel Tower" in result
    assert "ChIJLU7jZClu5kcR4PcOOO6p3I0" in result


async def test_find_place_by_name_tool_returns_no_places_when_empty() -> None:
    mock_cls = _patch_client(_make_mock_response({"places": []}))

    with patch("trip_planner.tools.find_place_by_name.httpx.AsyncClient", mock_cls):
        result = await find_place_by_name_tool.ainvoke({"query": "Nonexistent place xyz"})

    assert result == "No places found for this query."


async def test_find_place_by_name_tool_returns_error_string_on_http_error() -> None:
    mock_response = _make_mock_response({})
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=MagicMock(status_code=429)
    )
    mock_cls = _patch_client(mock_response)

    with patch("trip_planner.tools.find_place_by_name.httpx.AsyncClient", mock_cls):
        result = await find_place_by_name_tool.ainvoke({"query": "Eiffel Tower"})

    assert "unavailable" in result
    assert "429" in result


# --- find_place_by_name_tool ToolResult envelope ---


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "find_place_by_name_tool", "args": args, "id": "call_1"}


async def test_find_place_by_name_tool_success_envelope_carries_typed_places() -> None:
    mock_cls = _patch_client(_make_mock_response(_TEXT_SEARCH_RESPONSE))

    with patch("trip_planner.tools.find_place_by_name.httpx.AsyncClient", mock_cls):
        message = await find_place_by_name_tool.ainvoke(_tool_call({"query": "Eiffel Tower"}))

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "google-places"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert len(result.data.places) == 2


async def test_find_place_by_name_tool_empty_envelope_when_no_places() -> None:
    mock_cls = _patch_client(_make_mock_response({"places": []}))

    with patch("trip_planner.tools.find_place_by_name.httpx.AsyncClient", mock_cls):
        message = await find_place_by_name_tool.ainvoke(_tool_call({"query": "Nonexistent xyz"}))

    result = message.artifact
    assert result.status == ToolStatus.EMPTY
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is None
    assert result.latency_ms is not None


async def test_find_place_by_name_tool_error_envelope_is_retryable_on_http_error() -> None:
    mock_response = _make_mock_response({})
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=MagicMock(status_code=503)
    )
    mock_cls = _patch_client(mock_response)

    with patch("trip_planner.tools.find_place_by_name.httpx.AsyncClient", mock_cls):
        message = await find_place_by_name_tool.ainvoke(_tool_call({"query": "Eiffel Tower"}))

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True
