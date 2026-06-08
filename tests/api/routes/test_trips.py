# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage

from trip_planner.agents.state import TripPlannerState
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


def make_plan_result(itinerary: str = "Day 1: Arrive in Paris...") -> TripPlannerState:
    return TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days"), AIMessage(content=itinerary)],
        trip_request="Paris 7 days",
        draft_itinerary=itinerary,
    )


# --- POST /trips/plan ---


async def test_plan_trip_returns_200_with_itinerary(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    result = make_plan_result("Day 1: Arrive in Paris and check in.")

    with (
        patch("trip_planner.api.dependencies.user_repository.get_user_by_id", new_callable=AsyncMock) as mock_user,
        patch("trip_planner.api.routes.trips.run_planner", new_callable=AsyncMock) as mock_planner,
    ):
        mock_user.return_value = user
        mock_planner.return_value = result

        response = await db_client.post(
            "/trips/plan",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200

    body = response.json()
    assert body["itinerary"] == "Day 1: Arrive in Paris and check in."


async def test_plan_trip_returns_401_without_token(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/trips/plan",
        json={"query": "Plan a 7-day Paris trip for 2 people"},
    )

    assert response.status_code == 401


async def test_plan_trip_returns_401_for_invalid_token(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/trips/plan",
        json={"query": "Plan a 7-day Paris trip for 2 people"},
        headers={"Authorization": "Bearer not.a.valid.token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


async def test_plan_trip_returns_422_for_query_too_short(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))

    with patch("trip_planner.api.dependencies.user_repository.get_user_by_id", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = user

        response = await db_client.post(
            "/trips/plan",
            json={"query": "Paris"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422


async def test_plan_trip_passes_query_to_planner(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    query = "Plan a 7-day Paris trip for 2 people"
    result = make_plan_result("Day 1: Arrive in Paris.")

    with (
        patch("trip_planner.api.dependencies.user_repository.get_user_by_id", new_callable=AsyncMock) as mock_user,
        patch("trip_planner.api.routes.trips.run_planner", new_callable=AsyncMock) as mock_planner,
    ):
        mock_user.return_value = user
        mock_planner.return_value = result

        await db_client.post(
            "/trips/plan",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
        )

    called_state: TripPlannerState = mock_planner.call_args[0][0]
    assert called_state["trip_request"] == query
    assert called_state["draft_itinerary"] == ""
    assert called_state["messages"][0].content == query
