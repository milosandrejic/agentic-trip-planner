import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.selected_flight import SelectedFlight
from trip_planner.models.selected_hotel import SelectedHotel
from trip_planner.schemas.trips import FlightOption, HotelOption


async def set_selected_flight(
    db: AsyncSession, trip_id: uuid.UUID, flight: FlightOption
) -> SelectedFlight:
    """Record the trip's chosen flight, replacing any previous selection."""
    snapshot = flight.model_dump()
    existing = await get_selected_flight(db, trip_id)

    if existing is not None:
        existing.flight = snapshot
        await db.flush()
        await db.refresh(existing)
        return existing

    selection = SelectedFlight(trip_id=trip_id, flight=snapshot)
    db.add(selection)
    await db.flush()
    await db.refresh(selection)

    return selection


async def get_selected_flight(
    db: AsyncSession, trip_id: uuid.UUID
) -> SelectedFlight | None:
    """Return the trip's chosen flight, or None if none has been selected."""
    result = await db.execute(
        select(SelectedFlight).where(SelectedFlight.trip_id == trip_id)
    )

    return result.scalar_one_or_none()


async def set_selected_hotel(
    db: AsyncSession, trip_id: uuid.UUID, hotel: HotelOption
) -> SelectedHotel:
    """Record the trip's chosen hotel, replacing any previous selection."""
    snapshot = hotel.model_dump()
    existing = await get_selected_hotel(db, trip_id)

    if existing is not None:
        existing.hotel = snapshot
        await db.flush()
        await db.refresh(existing)
        return existing

    selection = SelectedHotel(trip_id=trip_id, hotel=snapshot)
    db.add(selection)
    await db.flush()
    await db.refresh(selection)

    return selection


async def get_selected_hotel(
    db: AsyncSession, trip_id: uuid.UUID
) -> SelectedHotel | None:
    """Return the trip's chosen hotel, or None if none has been selected."""
    result = await db.execute(
        select(SelectedHotel).where(SelectedHotel.trip_id == trip_id)
    )

    return result.scalar_one_or_none()
