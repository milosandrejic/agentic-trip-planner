import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from trip_planner.services.auth_service import hash_password


def make_mock_user(
    email: str = "ada@example.com",
    first_name: str = "Ada",
    last_name: str = "Lovelace",
    plain_password: str = "secret123",
    country: str | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.country = country
    user.hashed_password = hash_password(plain_password)
    user.created_at = datetime.now(timezone.utc)

    return user


# --- POST /auth/register ---

async def test_register_returns_201_with_user_data(db_client: AsyncClient) -> None:
    user = make_mock_user()

    with patch("trip_planner.api.routes.auth.user_repository.create_user", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = user

        payload = {
            "email": "ada@example.com",
            "password": "secret123",
            "first_name": "Ada",
            "last_name": "Lovelace",
        }
        response = await db_client.post("/auth/register", json=payload)

    assert response.status_code == 201

    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Lovelace"
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_returns_409_when_email_already_registered(db_client: AsyncClient) -> None:
    with patch("trip_planner.api.routes.auth.user_repository.create_user", new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = IntegrityError(None, None, Exception())

        payload = {
            "email": "ada@example.com",
            "password": "secret123",
            "first_name": "Ada",
            "last_name": "Lovelace",
        }
        response = await db_client.post("/auth/register", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


async def test_register_returns_422_for_invalid_email(db_client: AsyncClient) -> None:
    payload = {
        "email": "not-an-email",
        "password": "secret123",
        "first_name": "Ada",
        "last_name": "Lovelace",
    }
    response = await db_client.post("/auth/register", json=payload)

    assert response.status_code == 422


async def test_register_returns_422_for_missing_required_fields(db_client: AsyncClient) -> None:
    response = await db_client.post("/auth/register", json={"email": "ada@example.com"})

    assert response.status_code == 422


# --- POST /auth/login ---

async def test_login_returns_200_with_access_token(db_client: AsyncClient) -> None:
    user = make_mock_user(plain_password="secret123")

    with patch("trip_planner.api.routes.auth.user_repository.get_user_by_email", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = user

        payload = {"email": "ada@example.com", "password": "secret123"}
        response = await db_client.post("/auth/login", json=payload)

    assert response.status_code == 200

    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


async def test_login_returns_401_when_user_not_found(db_client: AsyncClient) -> None:
    with patch("trip_planner.api.routes.auth.user_repository.get_user_by_email", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        payload = {"email": "unknown@example.com", "password": "secret123"}
        response = await db_client.post("/auth/login", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_login_returns_401_for_wrong_password(db_client: AsyncClient) -> None:
    user = make_mock_user(plain_password="correct_password")

    with patch("trip_planner.api.routes.auth.user_repository.get_user_by_email", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = user

        payload = {"email": "ada@example.com", "password": "wrong_password"}
        response = await db_client.post("/auth/login", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_login_returns_422_for_invalid_email(db_client: AsyncClient) -> None:
    payload = {"email": "not-an-email", "password": "secret123"}
    response = await db_client.post("/auth/login", json=payload)

    assert response.status_code == 422
