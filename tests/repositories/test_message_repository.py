import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from trip_planner.models.message import Message
from trip_planner.repositories import message_repository


def make_mock_message(
    thread_id: uuid.UUID | None = None,
    role: str = "human",
    content: str = "Plan a trip",
) -> Message:
    """Return a Message instance with preset values (no DB needed)."""
    message = Message(
        thread_id=thread_id or uuid.uuid4(),
        role=role,
        content=content,
    )
    message.id = uuid.uuid4()
    message.created_at = datetime.now(timezone.utc)
    return message


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


# --- create_message ---


async def test_create_message_adds_correct_message_to_session() -> None:
    db = make_db()
    thread_id = uuid.uuid4()

    await message_repository.create_message(
        db, thread_id=thread_id, role="human", content="Plan a trip"
    )

    added_message: Message = db.add.call_args[0][0]
    assert isinstance(added_message, Message)
    assert added_message.thread_id == thread_id
    assert added_message.role == "human"
    assert added_message.content == "Plan a trip"
    assert added_message.itinerary is None


async def test_create_message_persists_itinerary_when_provided() -> None:
    db = make_db()
    itinerary_data = {"destination": "Paris", "total_days": 7}

    await message_repository.create_message(
        db, thread_id=uuid.uuid4(), role="assistant", content="Here is your plan.", itinerary=itinerary_data
    )

    added_message: Message = db.add.call_args[0][0]
    assert added_message.itinerary == itinerary_data


async def test_create_message_calls_flush_and_refresh() -> None:
    db = make_db()

    await message_repository.create_message(
        db, thread_id=uuid.uuid4(), role="human", content="Plan a trip"
    )

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


async def test_create_message_returns_message_instance() -> None:
    db = make_db()

    result = await message_repository.create_message(
        db, thread_id=uuid.uuid4(), role="human", content="Plan a trip"
    )

    assert isinstance(result, Message)


# --- list_by_thread ---


async def test_list_by_thread_returns_messages() -> None:
    db = make_db()
    thread_id = uuid.uuid4()
    messages = [
        make_mock_message(thread_id, role="human"),
        make_mock_message(thread_id, role="assistant"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = messages
    db.execute.return_value = mock_result

    result = await message_repository.list_by_thread(db, thread_id=thread_id)

    assert result == messages
    assert len(result) == 2


async def test_list_by_thread_returns_empty_list_when_no_messages() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    result = await message_repository.list_by_thread(db, thread_id=uuid.uuid4())

    assert result == []


async def test_list_by_thread_with_before_cursor_calls_execute() -> None:
    db = make_db()
    cursor = datetime.now(timezone.utc)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    await message_repository.list_by_thread(db, thread_id=uuid.uuid4(), before=cursor)

    db.execute.assert_awaited_once()


async def test_list_by_thread_respects_limit_parameter() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    # Should not raise; limit is passed through to the query builder
    await message_repository.list_by_thread(db, thread_id=uuid.uuid4(), limit=5)

    db.execute.assert_awaited_once()


# --- soft_delete_by_thread ---


async def test_soft_delete_by_thread_sets_deleted_at_on_all_messages() -> None:
    db = make_db()
    thread_id = uuid.uuid4()
    msg_a = make_mock_message(thread_id)
    msg_b = make_mock_message(thread_id)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [msg_a, msg_b]
    db.execute.return_value = mock_result

    before = datetime.now(timezone.utc)
    await message_repository.soft_delete_by_thread(db, thread_id=thread_id)

    assert msg_a.deleted_at is not None
    assert msg_b.deleted_at is not None
    assert msg_a.deleted_at >= before
    assert msg_b.deleted_at >= before


async def test_soft_delete_by_thread_calls_flush() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    await message_repository.soft_delete_by_thread(db, thread_id=uuid.uuid4())

    db.flush.assert_awaited_once()


async def test_soft_delete_by_thread_does_nothing_when_no_messages() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    # Should complete without error and flush once
    await message_repository.soft_delete_by_thread(db, thread_id=uuid.uuid4())

    db.flush.assert_awaited_once()
