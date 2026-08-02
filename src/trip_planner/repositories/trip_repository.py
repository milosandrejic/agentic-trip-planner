import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.trip import Trip


async def create_trip(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    slug: str,
    destination: str | None = None,
) -> Trip:
    """Persist a new trip row and return the refreshed instance."""
    trip = Trip(user_id=user_id, title=title, slug=slug, destination=destination)

    db.add(trip)
    await db.flush()
    await db.refresh(trip)

    return trip


async def get_by_id(db: AsyncSession, trip_id: uuid.UUID) -> Trip | None:
    """Return an active trip by its id, or None if not found or soft-deleted."""
    result = await db.execute(
        select(Trip).where(Trip.id == trip_id, Trip.deleted_at.is_(None))
    )

    return result.scalar_one_or_none()


async def list_by_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    cursor: tuple[datetime, uuid.UUID] | None = None,
    limit: int = 20,
) -> list[Trip]:
    """Return active trips owned by the user, newest first, with keyset pagination.

    Pass `cursor` (an `(updated_at, id)` pair) to fetch the page after that row.
    The composite key keeps paging stable when several rows share an `updated_at`.
    """
    query = select(Trip).where(Trip.user_id == user_id, Trip.deleted_at.is_(None))

    if cursor is not None:
        cursor_updated_at, cursor_id = cursor
        query = query.where(
            or_(
                Trip.updated_at < cursor_updated_at,
                and_(Trip.updated_at == cursor_updated_at, Trip.id < cursor_id),
            )
        )

    query = query.order_by(Trip.updated_at.desc(), Trip.id.desc()).limit(limit)

    result = await db.execute(query)

    return list(result.scalars().all())


async def soft_delete(db: AsyncSession, trip: Trip) -> Trip:
    """Mark a trip as deleted and return the updated instance."""
    trip.deleted_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(trip)

    return trip
