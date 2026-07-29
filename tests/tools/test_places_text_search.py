# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from trip_planner.tools.places_text_search import _format_results, places_text_search_tool

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


# --- places_text_search_tool ---


async def test_places_text_search_tool_returns_formatted_string_on_success() -> None:
    mock_cls = _patch_client(_make_mock_response(_TEXT_SEARCH_RESPONSE))

    with patch("trip_planner.tools.places_text_search.httpx.AsyncClient", mock_cls):
        result = await places_text_search_tool.ainvoke({"query": "Eiffel Tower"})

    assert "Eiffel Tower" in result
    assert "ChIJLU7jZClu5kcR4PcOOO6p3I0" in result


async def test_places_text_search_tool_returns_no_places_when_empty() -> None:
    mock_cls = _patch_client(_make_mock_response({"places": []}))

    with patch("trip_planner.tools.places_text_search.httpx.AsyncClient", mock_cls):
        result = await places_text_search_tool.ainvoke({"query": "Nonexistent place xyz"})

    assert result == "No places found for this query."


async def test_places_text_search_tool_returns_error_string_on_http_error() -> None:
    mock_response = _make_mock_response({})
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=MagicMock(status_code=429)
    )
    mock_cls = _patch_client(mock_response)

    with patch("trip_planner.tools.places_text_search.httpx.AsyncClient", mock_cls):
        result = await places_text_search_tool.ainvoke({"query": "Eiffel Tower"})

    assert "unavailable" in result
    assert "429" in result
