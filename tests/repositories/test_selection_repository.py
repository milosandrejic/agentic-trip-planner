import uuid
from unittest.mock import AsyncMock, MagicMock

from trip_planner.models.selected_flight import SelectedFlight
from trip_planner.models.selected_hotel import SelectedHotel
from trip_planner.repositories import selection_repository
from trip_planner.schemas.trips import FlightOption, HotelOption


def make_flight(airline: str = "British Airways") -> FlightOption:
    """Return a valid FlightOption for selection tests."""
    return FlightOption(
        airline=airline,
        stops=0,
        price="250.00",
        currency="GBP",
        outbound_date="2026-09-01",
    )


def make_hotel(name: str = "Hotel Le Marais") -> HotelOption:
    """Return a valid HotelOption for selection tests."""
    return HotelOption(name=name, total_price="380.00", currency="EUR")


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


def _found(value: object) -> MagicMock:
    """Build a mock execute() result whose scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# --- set_selected_flight ---


async def test_set_selected_flight_inserts_snapshot_when_absent() -> None:
    db = make_db()
    db.execute.return_value = _found(None)
    trip_id = uuid.uuid4()

    await selection_repository.set_selected_flight(db, trip_id, make_flight())

    added: SelectedFlight = db.add.call_args[0][0]
    assert added.trip_id == trip_id
    assert added.flight["airline"] == "British Airways"
    assert added.flight["price"] == "250.00"


async def test_set_selected_flight_replaces_existing_selection() -> None:
    db = make_db()
    existing = SelectedFlight(trip_id=uuid.uuid4(), flight={"airline": "Old"})
    db.execute.return_value = _found(existing)

    result = await selection_repository.set_selected_flight(
        db, existing.trip_id, make_flight("Air France")
    )

    assert result is existing
    assert existing.flight["airline"] == "Air France"
    db.add.assert_not_called()


async def test_set_selected_flight_calls_flush_and_refresh() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    await selection_repository.set_selected_flight(db, uuid.uuid4(), make_flight())

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


# --- get_selected_flight ---


async def test_get_selected_flight_returns_selection() -> None:
    db = make_db()
    selection = SelectedFlight(trip_id=uuid.uuid4(), flight={"airline": "BA"})
    db.execute.return_value = _found(selection)

    result = await selection_repository.get_selected_flight(db, selection.trip_id)

    assert result is selection


async def test_get_selected_flight_returns_none_when_unset() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    result = await selection_repository.get_selected_flight(db, uuid.uuid4())

    assert result is None


# --- set_selected_hotel ---


async def test_set_selected_hotel_inserts_snapshot_when_absent() -> None:
    db = make_db()
    db.execute.return_value = _found(None)
    trip_id = uuid.uuid4()

    await selection_repository.set_selected_hotel(db, trip_id, make_hotel())

    added: SelectedHotel = db.add.call_args[0][0]
    assert added.trip_id == trip_id
    assert added.hotel["name"] == "Hotel Le Marais"
    assert added.hotel["total_price"] == "380.00"


async def test_set_selected_hotel_replaces_existing_selection() -> None:
    db = make_db()
    existing = SelectedHotel(trip_id=uuid.uuid4(), hotel={"name": "Old"})
    db.execute.return_value = _found(existing)

    result = await selection_repository.set_selected_hotel(
        db, existing.trip_id, make_hotel("Ritz")
    )

    assert result is existing
    assert existing.hotel["name"] == "Ritz"
    db.add.assert_not_called()


async def test_set_selected_hotel_calls_flush_and_refresh() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    await selection_repository.set_selected_hotel(db, uuid.uuid4(), make_hotel())

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


# --- get_selected_hotel ---


async def test_get_selected_hotel_returns_selection() -> None:
    db = make_db()
    selection = SelectedHotel(trip_id=uuid.uuid4(), hotel={"name": "Ritz"})
    db.execute.return_value = _found(selection)

    result = await selection_repository.get_selected_hotel(db, selection.trip_id)

    assert result is selection


async def test_get_selected_hotel_returns_none_when_unset() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    result = await selection_repository.get_selected_hotel(db, uuid.uuid4())

    assert result is None
