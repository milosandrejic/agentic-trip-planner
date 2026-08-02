import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.place import Place
from trip_planner.repositories import place_repository
from trip_planner.services.types import PlaceResult


def make_place_result(name: str = "Colosseum", place_id: str = "google-123") -> PlaceResult:
    """Return a provider place result carrying core fields plus metadata."""
    return PlaceResult(
        name=name,
        place_id=place_id,
        categories=["landmark", "historic"],
        address="Piazza del Colosseo, Rome",
        latitude=41.8902,
        longitude=12.4922,
        rating=4.7,
        user_rating_count=100,
        price_level="PRICE_LEVEL_MODERATE",
    )


async def test_upsert_place_inserts_normalized_row(integration_db: AsyncSession) -> None:
    """A new provider result is stored with core columns and metadata folded into JSONB."""
    place = await place_repository.upsert_place(integration_db, "google", make_place_result())

    assert place.provider == "google"
    assert place.external_id == "google-123"
    assert place.name == "Colosseum"
    assert place.latitude == 41.8902
    assert place.place_metadata["categories"] == ["landmark", "historic"]
    assert place.place_metadata["rating"] == 4.7
    assert place.place_metadata["user_rating_count"] == 100


async def test_upsert_place_updates_existing_row_on_duplicate(
    integration_db: AsyncSession,
) -> None:
    """A second upsert with the same (provider, external_id) updates rather than duplicates."""
    await place_repository.upsert_place(integration_db, "google", make_place_result())

    updated = await place_repository.upsert_place(
        integration_db, "google", make_place_result(name="Colosseum (Flavian Amphitheatre)")
    )

    count = await integration_db.scalar(select(func.count()).select_from(Place))
    assert count == 1
    assert updated.name == "Colosseum (Flavian Amphitheatre)"


async def test_upsert_place_without_place_id_raises(integration_db: AsyncSession) -> None:
    """A result missing a provider id cannot be normalized and is rejected."""
    result = PlaceResult(name="Nameless", place_id=None)

    with pytest.raises(ValueError, match="place_id"):
        await place_repository.upsert_place(integration_db, "google", result)
