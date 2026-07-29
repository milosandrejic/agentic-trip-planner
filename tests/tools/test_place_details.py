# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from trip_planner.tools.place_details import _format_details, place_details_tool

_DETAILS_RESPONSE = {
    "displayName": {"text": "Louvre Museum", "languageCode": "en"},
    "formattedAddress": "Rue de Rivoli, 75001 Paris, France",
    "rating": 4.7,
    "userRatingCount": 320000,
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "websiteUri": "https://www.louvre.fr/",
    "internationalPhoneNumber": "+33 1 40 20 50 50",
    "regularOpeningHours": {
        "weekdayDescriptions": [
            "Monday: 9:00 AM – 6:00 PM",
            "Tuesday: Closed",
        ]
    },
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


# --- _format_details ---


def test_format_details_includes_all_available_fields() -> None:
    result = _format_details(_DETAILS_RESPONSE)

    assert "Louvre Museum" in result
    assert "Rue de Rivoli, 75001 Paris, France" in result
    assert "4.7" in result
    assert "320000 reviews" in result
    assert "PRICE_LEVEL_MODERATE" in result
    assert "+33 1 40 20 50 50" in result
    assert "https://www.louvre.fr/" in result
    assert "Monday: 9:00 AM – 6:00 PM" in result
    assert "Tuesday: Closed" in result


def test_format_details_handles_missing_optional_fields() -> None:
    result = _format_details({"displayName": {"text": "Small Cafe"}})

    assert result == "Small Cafe"


def test_format_details_handles_missing_display_name() -> None:
    result = _format_details({"formattedAddress": "Somewhere"})

    assert "Unknown place" in result
    assert "Somewhere" in result


def test_format_details_rating_without_count() -> None:
    result = _format_details({"displayName": {"text": "Place"}, "rating": 4.2})

    assert "Rating: 4.2" in result
    assert "reviews" not in result


# --- place_details_tool ---


async def test_place_details_tool_returns_formatted_string_on_success() -> None:
    mock_cls = _patch_client(_make_mock_response(_DETAILS_RESPONSE))

    with patch("trip_planner.tools.place_details.httpx.AsyncClient", mock_cls):
        result = await place_details_tool.ainvoke({"place_id": "ChIJ123"})

    assert "Louvre Museum" in result
    assert "4.7" in result


async def test_place_details_tool_returns_error_string_on_http_error() -> None:
    mock_response = _make_mock_response({})
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock(status_code=404)
    )
    mock_cls = _patch_client(mock_response)

    with patch("trip_planner.tools.place_details.httpx.AsyncClient", mock_cls):
        result = await place_details_tool.ainvoke({"place_id": "unknown"})

    assert "unavailable" in result
    assert "404" in result
