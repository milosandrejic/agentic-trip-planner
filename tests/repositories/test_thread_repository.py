import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trip_planner.models.thread import Thread
from trip_planner.repositories import thread_repository


def make_mock_thread(user_id: uuid.UUID | None = None) -> Thread:
    """Return a Thread instance with preset values (no DB needed)."""
    thread = Thread(
        user_id=user_id or uuid.uuid4(),
        title="Trip to Paris",
        slug="trip-to-paris-abc12345",
    )
    thread.id = uuid.uuid4()
    thread.created_at = datetime.now(timezone.utc)
    thread.updated_at = datetime.now(timezone.utc)
    return thread


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


# --- create_thread ---


async def test_create_thread_adds_correct_thread_to_session() -> None:
    db = make_db()
    user_id = uuid.uuid4()

    await thread_repository.create_thread(db, user_id=user_id, title="Paris Trip", slug="paris-trip-abc")

    added_thread: Thread = db.add.call_args[0][0]
    assert isinstance(added_thread, Thread)
    assert added_thread.user_id == user_id
    assert added_thread.title == "Paris Trip"
    assert added_thread.slug == "paris-trip-abc"


async def test_create_thread_calls_flush_and_refresh() -> None:
    db = make_db()

    await thread_repository.create_thread(db, user_id=uuid.uuid4(), title="Paris", slug="paris-abc")

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


async def test_create_thread_returns_thread_instance() -> None:
    db = make_db()
    thread = make_mock_thread()
    db.refresh.side_effect = lambda obj: None

    result = await thread_repository.create_thread(
        db, user_id=thread.user_id, title=thread.title, slug=thread.slug
    )

    assert isinstance(result, Thread)


# --- get_by_id ---


async def test_get_by_id_returns_thread_when_found() -> None:
    db = make_db()
    thread = make_mock_thread()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    db.execute.return_value = mock_result

    result = await thread_repository.get_by_id(db, thread.id)

    assert result is thread


async def test_get_by_id_returns_none_when_not_found() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await thread_repository.get_by_id(db, uuid.uuid4())

    assert result is None


# --- get_by_slug ---


async def test_get_by_slug_returns_thread_when_found() -> None:
    db = make_db()
    thread = make_mock_thread()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    db.execute.return_value = mock_result

    result = await thread_repository.get_by_slug(db, thread.slug)

    assert result is thread


async def test_get_by_slug_returns_none_when_not_found() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await thread_repository.get_by_slug(db, "nonexistent-slug")

    assert result is None


# --- list_by_user ---


async def test_list_by_user_returns_threads() -> None:
    db = make_db()
    user_id = uuid.uuid4()
    threads = [make_mock_thread(user_id), make_mock_thread(user_id)]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = threads
    db.execute.return_value = mock_result

    result = await thread_repository.list_by_user(db, user_id=user_id)

    assert result == threads
    assert len(result) == 2


async def test_list_by_user_returns_empty_list_when_no_threads() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    result = await thread_repository.list_by_user(db, user_id=uuid.uuid4())

    assert result == []


# --- soft_delete ---


async def test_soft_delete_sets_deleted_at_on_thread() -> None:
    db = make_db()
    thread = make_mock_thread()

    before = datetime.now(timezone.utc)
    await thread_repository.soft_delete(db, thread)

    assert thread.deleted_at is not None
    assert thread.deleted_at >= before


async def test_soft_delete_calls_flush_and_refresh() -> None:
    db = make_db()
    thread = make_mock_thread()

    await thread_repository.soft_delete(db, thread)

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()
