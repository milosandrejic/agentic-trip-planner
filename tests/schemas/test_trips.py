from uuid import uuid4

from trip_planner.schemas.trips import (
    Activity,
    FlightOption,
    HotelOption,
    Itinerary,
    Source,
)


def _activity(sources: list[Source]) -> Activity:
    """Return a minimal Activity carrying the given sources."""
    return Activity(time="09:00", description="Visit", sources=sources)


# --- numeric prices (item 7) ---


def test_flight_price_coerces_numeric_string_to_float() -> None:
    payload: dict[str, object] = {
        "airline": "BA",
        "stops": 0,
        "price": "250.00",
        "outbound_date": "2026-09-01",
    }
    flight = FlightOption.model_validate(payload)
    assert flight.price == 250.0
    assert isinstance(flight.price, float)


def test_hotel_prices_coerce_numeric_strings_to_float() -> None:
    payload: dict[str, object] = {
        "name": "Hotel Roma",
        "nightly_price": "95.00",
        "total_price": "380.00",
    }
    hotel = HotelOption.model_validate(payload)
    assert hotel.nightly_price == 95.0
    assert hotel.total_price == 380.0


# --- null instead of empty strings (item 6) ---


def test_flight_blank_fields_become_null() -> None:
    payload: dict[str, object] = {
        "airline": "BA",
        "stops": 0,
        "price": "",
        "currency": "   ",
        "outbound_date": "2026-09-01",
        "booking_url": "",
    }
    flight = FlightOption.model_validate(payload)
    assert flight.price is None
    assert flight.currency is None
    assert flight.booking_url is None


def test_hotel_blank_fields_become_null() -> None:
    payload: dict[str, object] = {
        "name": "Hotel Roma",
        "total_price": "",
        "currency": "",
        "area": "  ",
    }
    hotel = HotelOption.model_validate(payload)
    assert hotel.total_price is None
    assert hotel.currency is None
    assert hotel.area is None


# --- estimated prices (item 8) ---


def test_hotel_tilde_price_sets_is_estimated() -> None:
    payload: dict[str, object] = {"name": "Hotel Roma", "nightly_price": "~143.00"}
    hotel = HotelOption.model_validate(payload)
    assert hotel.nightly_price == 143.0
    assert hotel.is_estimated is True


def test_hotel_plain_price_is_not_estimated() -> None:
    payload: dict[str, object] = {"name": "Hotel Roma", "nightly_price": "143.00"}
    hotel = HotelOption.model_validate(payload)
    assert hotel.nightly_price == 143.0
    assert hotel.is_estimated is False


# --- valid source URLs only (item 9) ---


def test_activity_drops_sources_without_valid_url() -> None:
    activity = _activity(
        [
            Source(title="Good", url="https://example.com/a"),
            Source(title="Empty", url=""),
            Source(title="Broken", url="not-a-url"),
        ]
    )
    assert [source.title for source in activity.sources] == ["Good"]


def test_itinerary_drops_sources_without_valid_url() -> None:
    itinerary = Itinerary(
        destination="Paris",
        total_days=1,
        summary="A trip",
        days=[],
        sources=[
            Source(title="Good", url="http://example.com/a"),
            Source(title="Bad", url=""),
        ],
    )
    assert [source.title for source in itinerary.sources] == ["Good"]


# --- stable entity ids (item 5) ---


def test_activity_gets_a_default_id_when_omitted() -> None:
    activity = Activity(time="09:00", description="Visit")
    assert activity.id


def test_activity_blank_id_from_structured_output_becomes_fresh_uuid() -> None:
    activity = Activity.model_validate({"time": "09:00", "description": "Visit", "id": ""})
    assert activity.id


def test_activity_supplied_non_uuid_id_is_never_trusted() -> None:
    activity = Activity.model_validate(
        {"id": "activity-1", "time": "09:00", "description": "Visit"}
    )
    assert activity.id != "activity-1"


def test_activity_supplied_uuid_id_is_preserved() -> None:
    """A valid UUID round-tripping through the checkpointer or the database must stay stable."""
    stable_id = str(uuid4())
    activity = Activity.model_validate(
        {"id": stable_id, "time": "09:00", "description": "Visit"}
    )
    assert activity.id == stable_id


def test_flight_blank_id_from_structured_output_becomes_fresh_uuid() -> None:
    flight = FlightOption.model_validate(
        {"id": "", "airline": "BA", "stops": 0, "outbound_date": "2026-09-01"}
    )
    assert flight.id


def test_flight_supplied_uuid_id_is_preserved() -> None:
    stable_id = str(uuid4())
    flight = FlightOption.model_validate(
        {"id": stable_id, "airline": "BA", "stops": 0, "outbound_date": "2026-09-01"}
    )
    assert flight.id == stable_id


def test_hotel_supplied_non_uuid_id_is_never_trusted() -> None:
    hotel = HotelOption.model_validate({"id": "lp65564085", "name": "Hotel Roma"})
    assert hotel.id != "lp65564085"


def test_hotel_supplied_uuid_id_is_preserved() -> None:
    stable_id = str(uuid4())
    hotel = HotelOption.model_validate({"id": stable_id, "name": "Hotel Roma"})
    assert hotel.id == stable_id


def test_activity_ids_are_unique_across_instances() -> None:
    first = Activity(time="09:00", description="Visit")
    second = Activity(time="10:00", description="Wander")
    assert first.id != second.id
