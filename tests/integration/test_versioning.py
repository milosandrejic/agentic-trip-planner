from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.trip import Trip
from trip_planner.repositories import itinerary_version_repository


async def test_add_version_auto_increments_version_number(
    integration_db: AsyncSession, persisted_trip: Trip
) -> None:
    """Each appended version gets the next sequential number for its trip."""
    first = await itinerary_version_repository.add_version(
        integration_db, persisted_trip.id, {"summary": "v1"}
    )
    second = await itinerary_version_repository.add_version(
        integration_db, persisted_trip.id, {"summary": "v2"}
    )
    third = await itinerary_version_repository.add_version(
        integration_db, persisted_trip.id, {"summary": "v3"}
    )

    assert [first.version_number, second.version_number, third.version_number] == [1, 2, 3]


async def test_rollback_points_current_version_to_an_earlier_version(
    integration_db: AsyncSession, persisted_trip: Trip
) -> None:
    """Setting current back to an older version rolls the trip's itinerary back."""
    trip = await integration_db.get(Trip, persisted_trip.id)
    assert trip is not None

    version_one = await itinerary_version_repository.add_version(
        integration_db, trip.id, {"summary": "original"}
    )
    version_two = await itinerary_version_repository.add_version(
        integration_db, trip.id, {"summary": "revised"}
    )
    await itinerary_version_repository.set_current(integration_db, trip, version_two)

    await itinerary_version_repository.set_current(integration_db, trip, version_one)

    current = await itinerary_version_repository.get_current(integration_db, trip.id)
    assert current is not None
    assert current.id == version_one.id
    assert current.itinerary == {"summary": "original"}


async def test_list_versions_returns_newest_first(
    integration_db: AsyncSession, persisted_trip: Trip
) -> None:
    """Version history is returned in descending version-number order."""
    await itinerary_version_repository.add_version(integration_db, persisted_trip.id, {"n": 1})
    await itinerary_version_repository.add_version(integration_db, persisted_trip.id, {"n": 2})

    versions = await itinerary_version_repository.list_versions(integration_db, persisted_trip.id)

    assert [version.version_number for version in versions] == [2, 1]
