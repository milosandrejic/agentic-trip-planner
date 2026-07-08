# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from unittest.mock import AsyncMock, patch

from trip_planner.services.duffel_client import DuffelError
from trip_planner.tools.flight_search import (
    _build_offer_request,
    _format_offers,
    flight_search_tool,
)

_PATCH_POST = "trip_planner.tools.flight_search._client.post"
_PATCH_GET = "trip_planner.tools.flight_search._client.get"

_OFFER_REQUEST_RESPONSE = {"data": {"id": "ofr_123"}}

_OFFERS_RESPONSE = {
    "data": [
        {
            "owner": {"name": "British Airways"},
            "total_amount": "250.00",
            "total_currency": "GBP",
            "slices": [
                {
                    "duration": "PT1H15M",
                    "segments": [{"id": "seg_1"}],
                }
            ],
        },
        {
            "owner": {"name": "easyJet"},
            "total_amount": "89.99",
            "total_currency": "GBP",
            "slices": [
                {
                    "duration": "PT1H20M",
                    "segments": [{"id": "seg_2"}],
                }
            ],
        },
    ]
}


# --- _build_offer_request ---


def test_build_offer_request_one_way_has_single_slice() -> None:
    payload = _build_offer_request("LHR", "CDG", "2024-07-01", None, 1)

    slices = payload["data"]["slices"]
    assert len(slices) == 1
    assert slices[0]["origin"] == "LHR"
    assert slices[0]["destination"] == "CDG"
    assert slices[0]["departure_date"] == "2024-07-01"


def test_build_offer_request_round_trip_has_two_slices() -> None:
    payload = _build_offer_request("LHR", "CDG", "2024-07-01", "2024-07-08", 2)

    slices = payload["data"]["slices"]
    assert len(slices) == 2
    assert slices[1]["origin"] == "CDG"
    assert slices[1]["destination"] == "LHR"
    assert slices[1]["departure_date"] == "2024-07-08"


def test_build_offer_request_creates_correct_passenger_count() -> None:
    payload = _build_offer_request("LHR", "CDG", "2024-07-01", None, 3)

    passengers = payload["data"]["passengers"]
    assert len(passengers) == 3
    assert all(p["type"] == "adult" for p in passengers)


# --- _format_offers ---


def test_format_offers_returns_no_flights_message_when_empty() -> None:
    result = _format_offers([])

    assert result == "No flights found for this route and dates."


def test_format_offers_includes_airline_price_and_stops() -> None:
    offers = _OFFERS_RESPONSE["data"]
    result = _format_offers(offers)  # type: ignore[arg-type]

    assert "British Airways" in result
    assert "250.00 GBP" in result
    assert "Stops: 0" in result
    assert "PT1H15M" in result


def test_format_offers_caps_at_max_three_results() -> None:
    many_offers = [_OFFERS_RESPONSE["data"][0]] * 5
    result = _format_offers(many_offers)  # type: ignore[arg-type]

    assert result.count("Option") == 3


# --- flight_search_tool ---


async def test_flight_search_tool_returns_formatted_string_on_success() -> None:
    with (
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
    ):
        mock_post.return_value = _OFFER_REQUEST_RESPONSE
        mock_get.return_value = _OFFERS_RESPONSE

        result = await flight_search_tool.ainvoke(
            {
                "origin": "LHR",
                "destination": "CDG",
                "departure_date": "2024-07-01",
            }
        )

    assert "British Airways" in result
    assert "easyJet" in result


async def test_flight_search_tool_passes_correct_offer_request_id() -> None:
    with (
        patch(_PATCH_POST, new_callable=AsyncMock) as mock_post,
        patch(_PATCH_GET, new_callable=AsyncMock) as mock_get,
    ):
        mock_post.return_value = _OFFER_REQUEST_RESPONSE
        mock_get.return_value = _OFFERS_RESPONSE

        await flight_search_tool.ainvoke(
            {"origin": "LHR", "destination": "CDG", "departure_date": "2024-07-01"}
        )

    get_params = mock_get.call_args.kwargs["params"]
    assert get_params["offer_request_id"] == "ofr_123"


async def test_flight_search_tool_returns_error_string_on_duffel_error() -> None:
    with patch(_PATCH_POST, new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = DuffelError(422, "Invalid IATA code")

        result = await flight_search_tool.ainvoke(
            {"origin": "INVALID", "destination": "CDG", "departure_date": "2024-07-01"}
        )

    assert "Invalid IATA code" in result
    assert "unavailable" in result


async def test_flight_search_tool_returns_error_string_on_unexpected_response() -> None:
    with patch(_PATCH_POST, new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {}  # missing "data" key

        result = await flight_search_tool.ainvoke(
            {"origin": "LHR", "destination": "CDG", "departure_date": "2024-07-01"}
        )

    assert "Unexpected response" in result
