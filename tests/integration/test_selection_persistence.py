from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.selected_flight import SelectedFlight
from trip_planner.models.selected_hotel import SelectedHotel
from trip_planner.models.trip import Trip
from trip_planner.repositories import selection_repository
from trip_planner.schemas.trips import FlightOption, HotelOption


def make_flight(airline: str = "ITA Airways", price: float = 250.00) -> FlightOption:
    """Return a minimal valid flight option."""
    return FlightOption(
        airline=airline,
        stops=0,
        price=price,
        currency="EUR",
        outbound_date="2026-09-01",
    )


def make_hotel(name: str = "Hotel Roma", total: float = 480.00) -> HotelOption:
    """Return a minimal valid hotel option."""
    return HotelOption(name=name, total_price=total, currency="EUR")


async def test_set_selected_flight_persists_snapshot(
    integration_db: AsyncSession, persisted_trip: Trip
) -> None:
    """The chosen flight is stored as a JSONB snapshot and retrievable for the trip."""
    await selection_repository.set_selected_flight(integration_db, persisted_trip.id, make_flight())

    stored = await selection_repository.get_selected_flight(integration_db, persisted_trip.id)
    assert stored is not None
    assert stored.flight["airline"] == "ITA Airways"
    assert stored.flight["price"] == 250.0


async def test_set_selected_flight_replaces_previous_choice(
    integration_db: AsyncSession, persisted_trip: Trip
) -> None:
    """Selecting a new flight updates the single row instead of adding another."""
    await selection_repository.set_selected_flight(integration_db, persisted_trip.id, make_flight())

    await selection_repository.set_selected_flight(
        integration_db, persisted_trip.id, make_flight(airline="Ryanair", price=90.00)
    )

    count = await integration_db.scalar(
        select(func.count()).select_from(SelectedFlight).where(
            SelectedFlight.trip_id == persisted_trip.id
        )
    )
    stored = await selection_repository.get_selected_flight(integration_db, persisted_trip.id)
    assert count == 1
    assert stored is not None
    assert stored.flight["airline"] == "Ryanair"


async def test_set_selected_hotel_persists_and_replaces(
    integration_db: AsyncSession, persisted_trip: Trip
) -> None:
    """The chosen hotel persists as a snapshot and is replaced in place on re-selection."""
    await selection_repository.set_selected_hotel(integration_db, persisted_trip.id, make_hotel())

    await selection_repository.set_selected_hotel(
        integration_db, persisted_trip.id, make_hotel(name="Grand Hotel", total=620.00)
    )

    count = await integration_db.scalar(
        select(func.count()).select_from(SelectedHotel).where(
            SelectedHotel.trip_id == persisted_trip.id
        )
    )
    stored = await selection_repository.get_selected_hotel(integration_db, persisted_trip.id)
    assert count == 1
    assert stored is not None
    assert stored.hotel["name"] == "Grand Hotel"
    assert stored.hotel["total_price"] == 620.0
