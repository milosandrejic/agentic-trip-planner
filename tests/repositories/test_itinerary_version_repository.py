import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from trip_planner.models.itinerary_version import ItineraryVersion
from trip_planner.models.trip import Trip
from trip_planner.repositories import itinerary_version_repository


def make_mock_trip() -> Trip:
    """Return a Trip instance with preset values (no DB needed)."""
    trip = Trip(user_id=uuid.uuid4(), title="Paris", slug="paris-abc12345")
    trip.id = uuid.uuid4()
    return trip


def make_mock_version(trip_id: uuid.UUID, version_number: int = 1) -> ItineraryVersion:
    """Return an ItineraryVersion instance with preset values (no DB needed)."""
    version = ItineraryVersion(
        trip_id=trip_id, version_number=version_number, itinerary={"summary": "v"}
    )
    version.id = uuid.uuid4()
    version.created_at = datetime.now(timezone.utc)
    return version


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


def _scalar_result(value: object) -> MagicMock:
    """Build a mock execute() result whose scalar() returns the given value."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


# --- add_version ---


async def test_add_version_starts_at_one_when_no_prior_versions() -> None:
    db = make_db()
    db.execute.return_value = _scalar_result(None)
    trip_id = uuid.uuid4()
    itinerary: dict[str, Any] = {"summary": "first"}

    await itinerary_version_repository.add_version(db, trip_id, itinerary)

    added: ItineraryVersion = db.add.call_args[0][0]
    assert added.trip_id == trip_id
    assert added.version_number == 1
    assert added.itinerary == itinerary


async def test_add_version_increments_from_current_max() -> None:
    db = make_db()
    db.execute.return_value = _scalar_result(4)

    await itinerary_version_repository.add_version(db, uuid.uuid4(), {"summary": "next"})

    added: ItineraryVersion = db.add.call_args[0][0]
    assert added.version_number == 5


async def test_add_version_calls_flush_and_refresh() -> None:
    db = make_db()
    db.execute.return_value = _scalar_result(None)

    await itinerary_version_repository.add_version(db, uuid.uuid4(), {"summary": "x"})

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


async def test_add_version_returns_the_new_version() -> None:
    db = make_db()
    db.execute.return_value = _scalar_result(None)

    result = await itinerary_version_repository.add_version(db, uuid.uuid4(), {"s": 1})

    assert isinstance(result, ItineraryVersion)


# --- get_current ---


async def test_get_current_returns_pointed_version() -> None:
    db = make_db()
    trip_id = uuid.uuid4()
    version = make_mock_version(trip_id)

    result = MagicMock()
    result.scalar_one_or_none.return_value = version
    db.execute.return_value = result

    found = await itinerary_version_repository.get_current(db, trip_id)

    assert found is version


async def test_get_current_returns_none_when_unset() -> None:
    db = make_db()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    found = await itinerary_version_repository.get_current(db, uuid.uuid4())

    assert found is None


async def test_get_current_joins_trip_pointer() -> None:
    db = make_db()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    await itinerary_version_repository.get_current(db, uuid.uuid4())

    compiled = str(db.execute.call_args[0][0])
    assert "JOIN trips" in compiled
    assert "trips.current_version_id = itinerary_versions.id" in compiled


# --- list_versions ---


async def test_list_versions_returns_all_versions() -> None:
    db = make_db()
    trip_id = uuid.uuid4()
    versions = [make_mock_version(trip_id, 2), make_mock_version(trip_id, 1)]

    result = MagicMock()
    result.scalars.return_value.all.return_value = versions
    db.execute.return_value = result

    found = await itinerary_version_repository.list_versions(db, trip_id)

    assert found == versions


async def test_list_versions_orders_by_version_number_desc() -> None:
    db = make_db()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    await itinerary_version_repository.list_versions(db, uuid.uuid4())

    compiled = str(db.execute.call_args[0][0])
    assert "ORDER BY itinerary_versions.version_number DESC" in compiled


# --- set_current ---


async def test_set_current_points_trip_at_version() -> None:
    db = make_db()
    trip = make_mock_trip()
    version = make_mock_version(trip.id, 3)

    await itinerary_version_repository.set_current(db, trip, version)

    assert trip.current_version_id == version.id


async def test_set_current_supports_rollback_to_older_version() -> None:
    db = make_db()
    trip = make_mock_trip()
    older = make_mock_version(trip.id, 1)
    trip.current_version_id = uuid.uuid4()  # currently on a newer version

    await itinerary_version_repository.set_current(db, trip, older)

    assert trip.current_version_id == older.id


async def test_set_current_calls_flush_and_refresh() -> None:
    db = make_db()
    trip = make_mock_trip()
    version = make_mock_version(trip.id, 1)

    await itinerary_version_repository.set_current(db, trip, version)

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()
