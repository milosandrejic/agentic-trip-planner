import uuid
from unittest.mock import AsyncMock, MagicMock

from trip_planner.models.user import User
from trip_planner.repositories import user_repository


def make_mock_user() -> User:
    """Return a User instance with preset values (no DB needed)."""
    user = User(
        email="ada@example.com",
        hashed_password="$2b$12$hashed",
        first_name="Ada",
        last_name="Lovelace",
        country="GB",
    )
    user.id = uuid.uuid4()
    return user


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


# --- get_user_by_email ---


async def test_get_user_by_email_returns_user_when_found() -> None:
    db = make_db()
    user = make_mock_user()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute.return_value = mock_result

    result = await user_repository.get_user_by_email(db, "ada@example.com")

    assert result is user


async def test_get_user_by_email_returns_none_when_not_found() -> None:
    db = make_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await user_repository.get_user_by_email(db, "missing@example.com")

    assert result is None


# --- get_user_by_id ---


async def test_get_user_by_id_returns_user_when_found() -> None:
    db = make_db()
    user = make_mock_user()
    db.get.return_value = user

    result = await user_repository.get_user_by_id(db, user.id)

    assert result is user
    db.get.assert_awaited_once_with(User, user.id)


async def test_get_user_by_id_returns_none_when_not_found() -> None:
    db = make_db()
    db.get.return_value = None

    result = await user_repository.get_user_by_id(db, uuid.uuid4())

    assert result is None


# --- create_user ---


async def test_create_user_adds_correct_user_to_session() -> None:
    db = make_db()

    await user_repository.create_user(
        db,
        email="ada@example.com",
        hashed_password="$2b$12$hashed",
        first_name="Ada",
        last_name="Lovelace",
        country="GB",
    )

    added_user: User = db.add.call_args[0][0]
    assert isinstance(added_user, User)
    assert added_user.email == "ada@example.com"
    assert added_user.first_name == "Ada"
    assert added_user.last_name == "Lovelace"
    assert added_user.country == "GB"


async def test_create_user_accepts_null_country() -> None:
    db = make_db()

    await user_repository.create_user(
        db,
        email="ada@example.com",
        hashed_password="$2b$12$hashed",
        first_name="Ada",
        last_name="Lovelace",
        country=None,
    )

    added_user: User = db.add.call_args[0][0]
    assert added_user.country is None


async def test_create_user_calls_flush_and_refresh() -> None:
    db = make_db()

    await user_repository.create_user(
        db,
        email="ada@example.com",
        hashed_password="$2b$12$hashed",
        first_name="Ada",
        last_name="Lovelace",
        country=None,
    )

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


async def test_create_user_returns_user_instance() -> None:
    db = make_db()

    result = await user_repository.create_user(
        db,
        email="ada@example.com",
        hashed_password="$2b$12$hashed",
        first_name="Ada",
        last_name="Lovelace",
        country=None,
    )

    assert isinstance(result, User)
