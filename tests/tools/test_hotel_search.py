# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, patch

from trip_planner.services.hotels.provider import ProviderHotel
from trip_planner.services.liteapi_client import LiteApiError
from trip_planner.services.types import ToolStatus
from trip_planner.tools.hotel_search import _format_hotels, hotel_search_tool

_PATCH_GET = "trip_planner.tools.hotel_search._provider._client.get"
_PATCH_POST = "trip_planner.tools.hotel_search._provider._client.post"

_HOTELS_RESPONSE: dict[str, Any] = {
    "data": [
        {
            "id": "lp1",
            "name": "Hotel Le Marais",
            "stars": 4,
            "rating": 8.6,
            "address": "12 Rue de Rivoli",
            "main_photo": "https://example.com/lp1.jpg",
        },
        {
            "id": "lp2",
            "name": "Grand Louvre Hotel",
            "stars": 5,
            "rating": 9.1,
            "address": "5 Rue Saint-Honore",
        },
    ]
}

_RATES_RESPONSE: dict[str, Any] = {
    "data": [
        {
            "hotelId": "lp1",
            "roomTypes": [
                {"rates": [{"retailRate": {"total": [{"amount": 380.0, "currency": "EUR"}]}}]}
            ],
        },
        {
            "hotelId": "lp2",
            "roomTypes": [
                {"rates": [{"retailRate": {"total": [{"amount": 960.0, "currency": "EUR"}]}}]}
            ],
        },
    ]
}

_SUCCESS_ARGS = {
    "city_name": "Paris",
    "country_code": "FR",
    "checkin": "2024-07-01",
    "checkout": "2024-07-05",
}


def _provider_hotel(
    name: str, nightly_price: float | None, star_rating: float | None, address: str | None = None
) -> ProviderHotel:
    return ProviderHotel(
        hotel_id=name,
        name=name,
        nightly_price=nightly_price,
        star_rating=star_rating,
        currency="EUR",
        address=address,
    )


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "hotel_search_tool", "args": args, "id": "call_1"}


# --- _format_hotels ---


def test_format_hotels_returns_no_hotels_message_when_empty() -> None:
    assert _format_hotels([]) == "No hotels found matching the requested criteria."


def test_format_hotels_includes_name_nightly_price_and_star_rating() -> None:
    hotels = [_provider_hotel("Hotel Le Marais", 95.0, 4, address="12 Rue de Rivoli")]

    result = _format_hotels(hotels)

    assert "Hotel Le Marais" in result
    assert "95.00 EUR per night" in result
    assert "Star rating: 4" in result
    assert "12 Rue de Rivoli" in result


# --- hotel_search_tool ---


async def test_hotel_search_tool_returns_formatted_string_on_success() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.return_value = _RATES_RESPONSE
        result = await hotel_search_tool.ainvoke(_SUCCESS_ARGS)

    assert "Hotel Le Marais" in result
    assert "Grand Louvre Hotel" in result
    assert "95.00 EUR per night" in result


async def test_hotel_search_tool_applies_max_nightly_price() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.return_value = _RATES_RESPONSE
        message = await hotel_search_tool.ainvoke(
            _tool_call({**_SUCCESS_ARGS, "max_nightly_price": 100.0})
        )

    hotels = message.artifact.data.hotels
    assert [hotel.name for hotel in hotels] == ["Hotel Le Marais"]


async def test_hotel_search_tool_applies_min_star_rating() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.return_value = _RATES_RESPONSE
        message = await hotel_search_tool.ainvoke(
            _tool_call({**_SUCCESS_ARGS, "min_star_rating": 5.0})
        )

    hotels = message.artifact.data.hotels
    assert [hotel.name for hotel in hotels] == ["Grand Louvre Hotel"]


async def test_hotel_search_tool_returns_no_hotels_when_city_empty() -> None:
    with patch(_PATCH_GET, new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"data": []}
        result = await hotel_search_tool.ainvoke(_SUCCESS_ARGS)

    assert result == "No hotels found matching the requested criteria."


async def test_hotel_search_tool_returns_error_string_on_liteapi_error() -> None:
    with patch(_PATCH_GET, new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = LiteApiError(422, "Invalid country code")
        result = await hotel_search_tool.ainvoke({**_SUCCESS_ARGS, "country_code": "INVALID"})

    assert "Invalid country code" in result
    assert "unavailable" in result


async def test_hotel_search_tool_returns_error_string_on_unexpected_response() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.side_effect = TypeError("bad payload")
        result = await hotel_search_tool.ainvoke(_SUCCESS_ARGS)

    assert "Unexpected response" in result


# --- hotel_search_tool ToolResult envelope ---


async def test_hotel_search_tool_success_envelope_carries_typed_hotels() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.return_value = _RATES_RESPONSE
        message = await hotel_search_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "liteapi"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert len(result.data.hotels) == 2
    assert result.data.hotels[0].photo_url == "https://example.com/lp1.jpg"
    assert result.data.hotels[1].photo_url is None


async def test_hotel_search_tool_empty_envelope_when_no_hotels() -> None:
    with patch(_PATCH_GET, new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"data": []}
        message = await hotel_search_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.EMPTY
    assert result.provider == "liteapi"
    assert result.data is None
    assert result.error is None
    assert result.latency_ms is not None


async def test_hotel_search_tool_error_envelope_is_retryable_on_liteapi_error() -> None:
    with patch(_PATCH_GET, new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = LiteApiError(503, "Service unavailable")
        message = await hotel_search_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "liteapi"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True


async def test_hotel_search_tool_error_envelope_not_retryable_on_unexpected_response() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.side_effect = TypeError("bad payload")
        message = await hotel_search_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.error is not None
    assert result.error.retryable is False
