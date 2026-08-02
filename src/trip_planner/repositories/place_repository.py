from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.place import Place
from trip_planner.services.types import PlaceResult

# Non-core provider fields folded into the Place.metadata JSONB blob.
_METADATA_FIELDS = {
    "categories",
    "rating",
    "user_rating_count",
    "price_level",
    "opening_hours",
    "website_url",
    "phone",
}


async def upsert_place(db: AsyncSession, provider: str, result: PlaceResult) -> Place:
    """Normalize a provider place result into a Place, deduped by (provider, external_id).

    Updates the existing row when the (provider, external_id) pair is already stored,
    otherwise inserts a new one. Raises ValueError when the result has no external id.
    """
    if result.place_id is None:
        raise ValueError("Cannot normalize a place without a provider place_id")

    external_id = result.place_id
    metadata = result.model_dump(include=_METADATA_FIELDS)

    existing = await _find(db, provider, external_id)

    if existing is not None:
        existing.name = result.name
        existing.latitude = result.latitude
        existing.longitude = result.longitude
        existing.address = result.address
        existing.place_metadata = metadata
        await db.flush()
        await db.refresh(existing)
        return existing

    place = Place(
        provider=provider,
        external_id=external_id,
        name=result.name,
        latitude=result.latitude,
        longitude=result.longitude,
        address=result.address,
        place_metadata=metadata,
    )
    db.add(place)
    await db.flush()
    await db.refresh(place)

    return place


async def _find(db: AsyncSession, provider: str, external_id: str) -> Place | None:
    """Return the stored place for a (provider, external_id) pair, or None."""
    result = await db.execute(
        select(Place).where(Place.provider == provider, Place.external_id == external_id)
    )

    return result.scalar_one_or_none()
