from unittest.mock import AsyncMock

from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "trip-planner"}


async def test_health_db_returns_200_when_database_reachable(
    db_client: AsyncClient,
    mock_db_session: AsyncMock,
) -> None:
    response = await db_client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}
    mock_db_session.execute.assert_called_once()
