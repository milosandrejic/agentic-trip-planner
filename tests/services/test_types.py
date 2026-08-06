import pytest
from pydantic import BaseModel, ValidationError

from trip_planner.services.types import (
    FlightOffer,
    FlightSearchResult,
    HotelResult,
    HotelSearchResult,
    PlaceResult,
    PlacesResult,
    ToolError,
    ToolResult,
    ToolStatus,
    WeatherDay,
    WeatherResult,
)


class _SamplePayload(BaseModel):
    value: str


def test_ok_builds_success_result_with_data() -> None:
    payload = _SamplePayload(value="paris")

    result = ToolResult.ok(
        provider="duffel",
        data=payload,
        provider_request_id="req-123",
        latency_ms=42.5,
        cached=True,
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.provider == "duffel"
    assert result.provider_request_id == "req-123"
    assert result.latency_ms == 42.5
    assert result.cached is True
    assert result.data == payload
    assert result.error is None


def test_empty_builds_empty_result_without_data() -> None:
    result = ToolResult[_SamplePayload].empty(provider="liteapi", latency_ms=10.0)

    assert result.status is ToolStatus.EMPTY
    assert result.provider == "liteapi"
    assert result.latency_ms == 10.0
    assert result.data is None
    assert result.error is None
    assert result.cached is False


def test_fail_builds_error_result_with_structured_error() -> None:
    result = ToolResult[_SamplePayload].fail(
        provider="geoapify",
        message="rate limited",
        retryable=True,
        code="429",
        provider_request_id="req-9",
        latency_ms=5.0,
    )

    assert result.status is ToolStatus.ERROR
    assert result.provider == "geoapify"
    assert result.data is None
    assert result.error == ToolError(message="rate limited", retryable=True, code="429")
    assert result.error is not None
    assert result.error.retryable is True


def test_error_defaults_are_not_retryable() -> None:
    result = ToolResult[_SamplePayload].fail(provider="google", message="not found")

    assert result.error is not None
    assert result.error.retryable is False
    assert result.error.code is None


def test_error_status_requires_error() -> None:
    with pytest.raises(ValidationError, match="must include an error"):
        ToolResult[_SamplePayload](status=ToolStatus.ERROR, provider="duffel")


# --- typed payloads ---


def test_flight_search_result_preserves_provider_ids_and_prices() -> None:
    offer = FlightOffer(
        offer_id="off_123",
        airline="British Airways",
        stops=0,
        total_amount="250.00",
        currency="GBP",
        outbound_date="2026-08-01",
    )
    payload = FlightSearchResult(
        origin="LHR",
        destination="CDG",
        departure_date="2026-08-01",
        passengers=2,
        offers=[offer],
    )

    result = ToolResult.ok(provider="duffel", data=payload)

    assert result.data is not None
    assert result.data.offers[0].offer_id == "off_123"
    assert result.data.offers[0].duration_min is None
    assert result.data.return_date is None


def test_hotel_search_result_preserves_coordinates() -> None:
    hotel = HotelResult(
        hotel_id="lp_9",
        name="Hotel Le Marais",
        total_price="380.00",
        currency="USD",
        latitude=48.8566,
        longitude=2.3522,
    )
    payload = HotelSearchResult(
        city="Paris",
        country_code="FR",
        checkin="2026-08-01",
        checkout="2026-08-05",
        adults=2,
        hotels=[hotel],
    )

    assert payload.hotels[0].hotel_id == "lp_9"
    assert payload.hotels[0].latitude == 48.8566
    assert payload.hotels[0].rating is None


def test_weather_result_holds_daily_values() -> None:
    payload = WeatherResult(
        location="Paris",
        latitude=48.85,
        longitude=2.35,
        days=[WeatherDay(date="2026-08-01", temp_max_c=28.0, temp_min_c=17.0, precipitation_mm=0.0)],
    )

    assert payload.days[0].temp_max_c == 28.0
    assert payload.days[0].date == "2026-08-01"


def test_places_result_preserves_metadata() -> None:
    place = PlaceResult(
        name="Louvre Museum",
        place_id="ChIJ123",
        categories=["entertainment.museum"],
        latitude=48.8606,
        longitude=2.3376,
        rating=4.7,
        opening_hours=["Monday: 9 AM - 6 PM"],
        business_status="OPERATIONAL",
        editorial_summary="A former royal palace turned world-famous art museum.",
        google_maps_url="https://maps.google.com/?cid=123",
    )
    payload = PlacesResult(query="museums in Paris", places=[place])

    assert payload.places[0].place_id == "ChIJ123"
    assert payload.places[0].opening_hours == ["Monday: 9 AM - 6 PM"]
    assert payload.places[0].website_url is None
    assert payload.places[0].business_status == "OPERATIONAL"
    assert payload.places[0].editorial_summary is not None
    assert payload.places[0].google_maps_url == "https://maps.google.com/?cid=123"


def test_payloads_default_collections_to_empty_lists() -> None:
    flights = FlightSearchResult(
        origin="LHR", destination="CDG", departure_date="2026-08-01", passengers=1
    )
    places = PlacesResult(query="restaurants")

    assert flights.offers == []
    assert places.places == []


def test_non_error_status_rejects_error() -> None:
    with pytest.raises(ValidationError, match="must not include an error"):
        ToolResult[_SamplePayload](
            status=ToolStatus.SUCCESS,
            provider="duffel",
            error=ToolError(message="oops"),
        )
