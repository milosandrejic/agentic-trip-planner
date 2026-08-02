import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from trip_planner.models.trip import Trip, TripStatus
from trip_planner.repositories import trip_repository


def make_mock_trip(user_id: uuid.UUID | None = None) -> Trip:
    """Return a Trip instance with preset values (no DB needed)."""
    trip = Trip(
        user_id=user_id or uuid.uuid4(),
        title="Trip to Paris",
        slug="trip-to-paris-abc12345",
    )
    trip.id = uuid.uuid4()
    trip.status = TripStatus.DRAFT
    trip.created_at = datetime.now(timezone.utc)
    trip.updated_at = datetime.now(timezone.utc)
    return trip


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


# --- create_trip ---


async def test_create_trip_adds_correct_trip_to_session() -> None:
    db = make_db()
    user_id = uuid.uuid4()

    await trip_repository.create_trip(
        db, user_id=user_id, title="Paris Trip", slug="paris-trip-abc", destination="Paris"
    )

    added_trip: Trip = db.add.call_args[0][0]
    assert isinstance(added_trip, Trip)
    assert added_trip.user_id == user_id
    assert added_trip.title == "Paris Trip"
    assert added_trip.slug == "paris-trip-abc"
    assert added_trip.destination == "Paris"


async def test_create_trip_defaults_destination_to_none() -> None:
    db = make_db()

    await trip_repository.create_trip(db, user_id=uuid.uuid4(), title="Paris", slug="paris-abc")

    added_trip: Trip = db.add.call_args[0][0]
    assert added_trip.destination is None


async def test_create_trip_calls_flush_and_refresh() -> None:
    db = make_db()

    await trip_repository.create_trip(db, user_id=uuid.uuid4(), title="Paris", slug="paris-abc")

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


async def test_create_trip_returns_trip_instance() -> None:
    db = make_db()
    trip = make_mock_trip()

    result = await trip_repository.create_trip(
        db, user_id=trip.user_id, title=trip.title, slug=trip.slug
    )

    assert isinstance(result, Trip)


# --- get_by_id ---


async def test_get_by_id_returns_trip_when_found() -> None:
    db = make_db()
    trip = make_mock_trip()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = trip
    db.execute.return_value = mock_result

    result = await trip_repository.get_by_id(db, trip.id)

    assert result is trip


async def test_get_by_id_returns_none_when_missing() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await trip_repository.get_by_id(db, uuid.uuid4())

    assert result is None


async def test_get_by_id_excludes_soft_deleted_rows() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    await trip_repository.get_by_id(db, uuid.uuid4())

    compiled = str(db.execute.call_args[0][0])
    assert "trips.deleted_at IS NULL" in compiled


# --- list_by_user ---


async def test_list_by_user_returns_trips() -> None:
    db = make_db()
    user_id = uuid.uuid4()
    trips = [make_mock_trip(user_id), make_mock_trip(user_id)]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = trips
    db.execute.return_value = mock_result

    result = await trip_repository.list_by_user(db, user_id=user_id)

    assert result == trips
    assert len(result) == 2


async def test_list_by_user_returns_empty_list_when_no_trips() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    result = await trip_repository.list_by_user(db, user_id=uuid.uuid4())

    assert result == []


async def test_list_by_user_orders_by_updated_at_then_id_for_stable_paging() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    await trip_repository.list_by_user(db, user_id=uuid.uuid4())

    compiled = str(db.execute.call_args[0][0])
    # id is the tiebreaker so rows sharing an updated_at keep a deterministic order.
    assert "ORDER BY trips.updated_at DESC, trips.id DESC" in compiled


async def test_list_by_user_cursor_uses_composite_updated_at_and_id_predicate() -> None:
    db = make_db()
    cursor = (datetime.now(timezone.utc), uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    await trip_repository.list_by_user(db, user_id=uuid.uuid4(), cursor=cursor)

    compiled = str(db.execute.call_args[0][0])
    # Keyset predicate: updated_at < cursor OR (updated_at == cursor AND id < cursor_id).
    assert "trips.updated_at <" in compiled
    assert "trips.updated_at =" in compiled
    assert "trips.id <" in compiled


async def test_list_by_user_respects_limit_parameter() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    await trip_repository.list_by_user(db, user_id=uuid.uuid4(), limit=5)

    compiled = str(db.execute.call_args[0][0])
    assert "LIMIT" in compiled


# --- soft_delete ---


async def test_soft_delete_sets_deleted_at_on_trip() -> None:
    db = make_db()
    trip = make_mock_trip()

    before = datetime.now(timezone.utc)
    await trip_repository.soft_delete(db, trip)

    assert trip.deleted_at is not None
    assert trip.deleted_at >= before


async def test_soft_delete_calls_flush_and_refresh() -> None:
    db = make_db()
    trip = make_mock_trip()

    await trip_repository.soft_delete(db, trip)

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()
