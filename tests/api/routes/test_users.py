import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from trip_planner.services.auth_service import create_access_token


def make_mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "ada@example.com"
    user.first_name = "Ada"
    user.last_name = "Lovelace"
    user.country = None
    user.created_at = datetime.now(timezone.utc)

    return user


async def test_get_me_returns_200_with_user_data(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))

    with patch("trip_planner.api.dependencies.user_repository.get_user_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = user

        response = await db_client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200

    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["first_name"] == "Ada"
    assert "hashed_password" not in body


async def test_get_me_returns_401_without_token(db_client: AsyncClient) -> None:
    response = await db_client.get("/me")

    assert response.status_code == 401


async def test_get_me_returns_401_for_invalid_token(db_client: AsyncClient) -> None:
    response = await db_client.get("/me", headers={"Authorization": "Bearer not.a.valid.token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


async def test_get_me_returns_401_when_user_not_found(db_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id))

    with patch("trip_planner.api.dependencies.user_repository.get_user_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        response = await db_client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"
