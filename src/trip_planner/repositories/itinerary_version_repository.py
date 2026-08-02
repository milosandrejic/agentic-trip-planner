import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.itinerary_version import ItineraryVersion
from trip_planner.models.trip import Trip


async def add_version(
    db: AsyncSession,
    trip_id: uuid.UUID,
    itinerary: dict[str, Any],
) -> ItineraryVersion:
    """Append a new itinerary version for the trip, auto-incrementing version_number."""
    result = await db.execute(
        select(func.max(ItineraryVersion.version_number)).where(
            ItineraryVersion.trip_id == trip_id
        )
    )
    current_max = result.scalar()
    next_number = (current_max or 0) + 1

    version = ItineraryVersion(
        trip_id=trip_id, version_number=next_number, itinerary=itinerary
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)

    return version


async def get_current(db: AsyncSession, trip_id: uuid.UUID) -> ItineraryVersion | None:
    """Return the version the trip currently points to, or None if unset."""
    result = await db.execute(
        select(ItineraryVersion)
        .join(Trip, Trip.current_version_id == ItineraryVersion.id)
        .where(Trip.id == trip_id)
    )

    return result.scalar_one_or_none()


async def list_versions(db: AsyncSession, trip_id: uuid.UUID) -> list[ItineraryVersion]:
    """Return all versions for the trip, newest version_number first."""
    result = await db.execute(
        select(ItineraryVersion)
        .where(ItineraryVersion.trip_id == trip_id)
        .order_by(ItineraryVersion.version_number.desc())
    )

    return list(result.scalars().all())


async def set_current(
    db: AsyncSession, trip: Trip, version: ItineraryVersion
) -> Trip:
    """Point the trip at the given version (used to publish new versions or roll back)."""
    trip.current_version_id = version.id

    await db.flush()
    await db.refresh(trip)

    return trip
