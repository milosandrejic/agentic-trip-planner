# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from trip_planner.agents.graph import PlannerOutcome
from trip_planner.models.trip import TripStatus
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary, Source
from trip_planner.services.auth_service import create_access_token

_DEPS_GET_USER = "trip_planner.api.dependencies.user_repository.get_user_by_id"
_SERVICE = "trip_planner.services.trip_planning_service"
_PLANNER = f"{_SERVICE}.plan_turn"
_TRIP_REPO = "trip_planner.repositories.trip_repository"
_THREAD_REPO = "trip_planner.repositories.thread_repository"
_MESSAGE_REPO = "trip_planner.repositories.message_repository"
_VERSION_REPO = "trip_planner.repositories.itinerary_version_repository"


def make_mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "ada@example.com"
    return user


def make_mock_trip(status: TripStatus = TripStatus.DRAFT) -> MagicMock:
    trip = MagicMock()
    trip.id = uuid.uuid4()
    trip.title = "Trip to Paris"
    trip.slug = "trip-to-paris-abc12345"
    trip.destination = None
    trip.status = status
    trip.created_at = datetime.now(timezone.utc)
    trip.updated_at = datetime.now(timezone.utc)
    return trip


def make_mock_thread() -> MagicMock:
    thread = MagicMock()
    thread.id = uuid.uuid4()
    thread.trip_id = None
    return thread


def make_itinerary(destination: str = "Paris") -> Itinerary:
    activity = Activity(time="Morning", description="Visit the Eiffel Tower")
    day = DayPlan(day=1, location=destination, activities=[activity])
    return Itinerary(
        destination=destination,
        total_days=1,
        summary=f"A wonderful trip to {destination}.",
        days=[day],
    )


def make_plan_result(itinerary: Itinerary | None = None) -> PlannerOutcome:
    return PlannerOutcome(itinerary=itinerary or make_itinerary())


def make_clarification_result(message: str = "Where would you like to go?") -> PlannerOutcome:
    clarification = ClarificationRequest(message=message, missing_fields=["destination"])
    return PlannerOutcome(clarification=clarification)


def patch_service_repos(stack: ExitStack, *, trip: MagicMock, thread: MagicMock) -> SimpleNamespace:
    """Patch the repository calls the service makes and return the mocks worth asserting on."""
    create_message = AsyncMock()
    add_version = AsyncMock()
    stack.enter_context(patch(f"{_TRIP_REPO}.create_trip", AsyncMock(return_value=trip)))
    stack.enter_context(patch(f"{_TRIP_REPO}.get_by_id", AsyncMock(return_value=trip)))
    stack.enter_context(patch(f"{_THREAD_REPO}.create_thread", AsyncMock(return_value=thread)))
    stack.enter_context(patch(f"{_MESSAGE_REPO}.create_message", create_message))
    stack.enter_context(patch(f"{_VERSION_REPO}.add_version", add_version))
    stack.enter_context(patch(f"{_VERSION_REPO}.set_current", AsyncMock()))

    return SimpleNamespace(create_message=create_message, add_version=add_version)


# --- POST /trips ---


async def test_create_trip_returns_201_with_itinerary(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    trip = make_mock_trip()
    thread = make_mock_thread()
    itinerary = make_itinerary("Paris")

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        patch_service_repos(stack, trip=trip, thread=thread)
        stack.enter_context(patch(_PLANNER, new=AsyncMock(return_value=make_plan_result(itinerary))))

        response = await db_client.post(
            "/trips",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["trip"]["title"] == trip.title
    assert body["trip"]["slug"] == trip.slug
    assert body["thread_id"] == str(thread.id)
    assert body["result"]["type"] == "itinerary"
    assert body["result"]["itinerary"]["destination"] == "Paris"


async def test_create_trip_returns_201_with_clarification(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    trip = make_mock_trip()
    thread = make_mock_thread()

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        deps = patch_service_repos(stack, trip=trip, thread=thread)
        stack.enter_context(patch(_PLANNER, new=AsyncMock(return_value=make_clarification_result())))

        response = await db_client.post(
            "/trips",
            json={"query": "Plan me a trip somewhere"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    assert response.json()["result"]["type"] == "clarification"
    deps.add_version.assert_not_awaited()


async def test_create_trip_persists_itinerary_version(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    trip = make_mock_trip()
    thread = make_mock_thread()

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        deps = patch_service_repos(stack, trip=trip, thread=thread)
        stack.enter_context(patch(_PLANNER, new=AsyncMock(return_value=make_plan_result())))

        await db_client.post(
            "/trips",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    deps.add_version.assert_awaited_once()


async def test_create_trip_returns_sources(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    trip = make_mock_trip()
    thread = make_mock_thread()
    itinerary = make_itinerary("Paris")
    itinerary.sources.append(Source(title="Paris Guide", url="https://example.com/paris"))

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        patch_service_repos(stack, trip=trip, thread=thread)
        stack.enter_context(patch(_PLANNER, new=AsyncMock(return_value=make_plan_result(itinerary))))

        response = await db_client.post(
            "/trips",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.json()["result"]["itinerary"]["sources"][0]["url"] == "https://example.com/paris"


async def test_create_trip_passes_query_to_planner(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    trip = make_mock_trip()
    thread = make_mock_thread()
    query = "Plan a 7-day Paris trip for 2 people"

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        patch_service_repos(stack, trip=trip, thread=thread)
        planner = AsyncMock(return_value=make_plan_result())
        stack.enter_context(patch(_PLANNER, new=planner))

        await db_client.post(
            "/trips",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert planner.call_args[0][0] == query
    assert planner.call_args[0][1] == str(thread.id)


async def test_create_trip_returns_401_without_token(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/trips",
        json={"query": "Plan a 7-day Paris trip for 2 people"},
    )

    assert response.status_code == 401


async def test_create_trip_returns_401_for_invalid_token(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/trips",
        json={"query": "Plan a 7-day Paris trip for 2 people"},
        headers={"Authorization": "Bearer not.a.valid.token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


async def test_create_trip_returns_422_for_query_too_short(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))

    with patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)):
        response = await db_client.post(
            "/trips",
            json={"query": "Paris"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422


async def test_create_trip_returns_500_when_graph_returns_no_result(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    trip = make_mock_trip()
    thread = make_mock_thread()

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        patch_service_repos(stack, trip=trip, thread=thread)
        stack.enter_context(patch(_PLANNER, new=AsyncMock(return_value=PlannerOutcome())))

        response = await db_client.post(
            "/trips",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Graph did not produce a structured itinerary or clarification"
