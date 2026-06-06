from collections.abc import AsyncGenerator, AsyncIterator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.core.database import get_db
from trip_planner.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
async def db_client(mock_db_session: AsyncMock) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
