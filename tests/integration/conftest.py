import asyncio
import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from trip_planner import models  # noqa: F401  # pyright: ignore[reportUnusedImport]  (registers every table on Base.metadata)
from trip_planner.config import get_settings
from trip_planner.core.database import Base, get_db
from trip_planner.main import app
from trip_planner.models.trip import Trip
from trip_planner.models.user import User
from trip_planner.services.auth_service import create_access_token, hash_password

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _admin_url() -> str:
    """Connection URL to the default 'postgres' maintenance database for server-level admin SQL."""
    return (
        make_url(get_settings().database_url)
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )


def _test_url() -> str:
    """Connection URL to the dedicated integration-test database."""
    return get_settings().test_database_url


async def _recreate_database() -> None:
    """Drop and recreate the test database so each session starts from an empty server."""
    test_db_name = make_url(_test_url()).database
    admin_engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    await admin_engine.dispose()


def _run_migrations() -> None:
    """Build the test schema by running the production migrations (alembic upgrade head)."""
    env = {**os.environ, "DATABASE_URL": _test_url()}
    subprocess.run(["alembic", "upgrade", "head"], cwd=_PROJECT_ROOT, env=env, check=True)


@pytest.fixture(scope="session", autouse=True)
def _integration_schema() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Provision the integration-test database once for the whole session.

    Recreates the database on a throwaway event loop (so it never collides with the per-test loops
    pytest-asyncio creates), then applies the real Alembic migrations so the test schema stays
    identical to production and the migration chain is exercised on every run.
    """
    asyncio.run(_recreate_database())
    _run_migrations()
    yield


@pytest.fixture
async def integration_engine() -> AsyncIterator[AsyncEngine]:
    """A fresh async engine bound to the test database and the current test's event loop."""
    engine = create_async_engine(_test_url(), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(integration_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory mirroring the app's production configuration, bound to the test engine."""
    return async_sessionmaker(
        bind=integration_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


@pytest.fixture(autouse=True)
async def _clean_tables(integration_engine: AsyncEngine) -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Truncate every table after each test so cases stay isolated on the shared database."""
    yield
    # Unsorted is fine: CASCADE resolves order, and it sidesteps the trips<->versions cycle warning.
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.tables.values())
    async with integration_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def integration_db(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A real session for arranging fixtures and asserting persisted state."""
    async with sessionmaker() as session:
        yield session


@pytest.fixture
async def integration_client(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """HTTP client whose requests run against the real test database via get_db override."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(sessionmaker: async_sessionmaker[AsyncSession]) -> User:
    """A persisted, active user to authenticate integration requests against."""
    async with sessionmaker() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password=hash_password("secret123"),
            first_name="Ada",
            last_name="Lovelace",
            country=None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Bearer-token header for the persisted test user."""
    token = create_access_token(str(test_user.id))

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def persisted_trip(
    sessionmaker: async_sessionmaker[AsyncSession], test_user: User
) -> Trip:
    """A committed trip owned by the test user, for repository-level persistence tests."""
    async with sessionmaker() as session:
        trip = Trip(user_id=test_user.id, title="Weekend away", slug=f"trip-{uuid.uuid4().hex[:8]}")
        session.add(trip)
        await session.commit()
        await session.refresh(trip)

        return trip
