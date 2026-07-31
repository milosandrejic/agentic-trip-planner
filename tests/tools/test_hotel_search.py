# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, patch

from trip_planner.services.liteapi_client import LiteApiError
from trip_planner.services.types import ToolStatus
from trip_planner.tools.hotel_search import (
    _build_rates_request,
    _extract_lowest_price,
    _format_hotels,
    hotel_search_tool,
)

_PATCH_GET = "trip_planner.tools.hotel_search._client.get"
_PATCH_POST = "trip_planner.tools.hotel_search._client.post"

_HOTELS_RESPONSE = {
    "data": [
        {
            "id": "lp1",
            "name": "Hotel Le Marais",
            "rating": 4,
            "address": "12 Rue de Rivoli",
        },
        {
            "id": "lp2",
            "name": "Grand Louvre Hotel",
            "rating": 5,
            "address": "5 Rue Saint-Honore",
        },
    ]
}

_RATES_RESPONSE = {
    "data": [
        {
            "hotelId": "lp1",
            "roomTypes": [
                {
                    "rates": [
                        {"retailRate": {"total": [{"amount": 420.0, "currency": "USD"}]}},
                        {"retailRate": {"total": [{"amount": 380.0, "currency": "USD"}]}},
                    ]
                }
            ],
        },
        {
            "hotelId": "lp2",
            "roomTypes": [
                {"rates": [{"retailRate": {"total": [{"amount": 950.0, "currency": "USD"}]}}]}
            ],
        },
    ]
}


# --- _build_rates_request ---


def test_build_rates_request_includes_hotels_dates_and_occupancy() -> None:
    payload = _build_rates_request(["lp1", "lp2"], "2024-07-01", "2024-07-05", 2)

    assert payload["hotelIds"] == ["lp1", "lp2"]
    assert payload["checkin"] == "2024-07-01"
    assert payload["checkout"] == "2024-07-05"
    assert payload["occupancies"] == [{"adults": 2}]


# --- _extract_lowest_price ---


def test_extract_lowest_price_returns_cheapest_rate() -> None:
    amount, currency = _extract_lowest_price(_RATES_RESPONSE["data"][0])

    assert amount == "380.00"
    assert currency == "USD"


def test_extract_lowest_price_returns_na_when_no_rates() -> None:
    amount, currency = _extract_lowest_price({"roomTypes": []})

    assert amount == "N/A"
    assert currency == ""


# --- _format_hotels ---


def test_format_hotels_returns_no_hotels_message_when_empty() -> None:
    result = _format_hotels([], {})

    assert result == "No hotels found for this city and dates."


def test_format_hotels_includes_name_price_and_rating() -> None:
    hotels = _HOTELS_RESPONSE["data"]
    price_by_id = {"lp1": ("380.00", "USD"), "lp2": ("950.00", "USD")}
    result = _format_hotels(hotels, price_by_id)  # type: ignore[arg-type]

    assert "Hotel Le Marais" in result
    assert "380.00 USD" in result
    assert "Rating: 4" in result
    assert "12 Rue de Rivoli" in result


def test_format_hotels_caps_at_max_three_results() -> None:
    many_hotels = [_HOTELS_RESPONSE["data"][0]] * 5
    result = _format_hotels(many_hotels, {})  # type: ignore[arg-type]

    assert result.count("Option") == 3


# --- hotel_search_tool ---


async def test_hotel_search_tool_returns_formatted_string_on_success() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.return_value = _RATES_RESPONSE

        result = await hotel_search_tool.ainvoke(
            {
                "city_name": "Paris",
                "country_code": "FR",
                "checkin": "2024-07-01",
                "checkout": "2024-07-05",
            }
        )

    assert "Hotel Le Marais" in result
    assert "Grand Louvre Hotel" in result
    assert "380.00 USD" in result


async def test_hotel_search_tool_returns_no_hotels_when_city_empty() -> None:
    with patch(_PATCH_GET, new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"data": []}

        result = await hotel_search_tool.ainvoke(
            {
                "city_name": "Nowhere",
                "country_code": "XX",
                "checkin": "2024-07-01",
                "checkout": "2024-07-05",
            }
        )

    assert result == "No hotels found for this city and dates."


async def test_hotel_search_tool_returns_error_string_on_liteapi_error() -> None:
    with patch(_PATCH_GET, new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = LiteApiError(422, "Invalid country code")

        result = await hotel_search_tool.ainvoke(
            {
                "city_name": "Paris",
                "country_code": "INVALID",
                "checkin": "2024-07-01",
                "checkout": "2024-07-05",
            }
        )

    assert "Invalid country code" in result
    assert "unavailable" in result


async def test_hotel_search_tool_returns_error_string_on_unexpected_response() -> None:
    with (
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = _HOTELS_RESPONSE
        mock_post.side_effect = TypeError("bad payload")

        result = await hotel_search_tool.ainvoke(
            {
                "city_name": "Paris",
                "country_code": "FR",
                "checkin": "2024-07-01",
                "checkout": "2024-07-05",
            }
        )

    assert "Unexpected response" in result


# --- hotel_search_tool ToolResult envelope ---

_SUCCESS_ARGS = {
    "city_name": "Paris",
    "country_code": "FR",
    "checkin": "2024-07-01",
    "checkout": "2024-07-05",
}


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "hotel_search_tool", "args": args, "id": "call_1"}


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
