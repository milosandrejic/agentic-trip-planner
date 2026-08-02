# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from trip_planner.agents.graph import PlannerOutcome
from trip_planner.core.pagination import decode_cursor, encode_cursor
from trip_planner.models.thread import ThreadStatus
from trip_planner.models.trip import TripStatus
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary
from trip_planner.services.auth_service import create_access_token

_DEPS_GET_USER = "trip_planner.api.dependencies.user_repository.get_user_by_id"
_THREAD_REPO = "trip_planner.api.routes.threads.thread_repository"
_MESSAGE_REPO = "trip_planner.api.routes.threads.message_repository"
_SVC_PLANNER = "trip_planner.services.trip_planning_service.plan_turn"
_SVC_TRIP_REPO = "trip_planner.repositories.trip_repository"
_SVC_MESSAGE_REPO = "trip_planner.repositories.message_repository"
_SVC_VERSION_REPO = "trip_planner.repositories.itinerary_version_repository"


def make_mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "ada@example.com"
    return user


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


def make_clarification_result(message: str = "Could you tell me where and how long?") -> PlannerOutcome:
    clarification = ClarificationRequest(
        message=message,
        missing_fields=["destination", "duration"],
    )
    return PlannerOutcome(clarification=clarification)


def make_mock_thread(user_id: uuid.UUID) -> MagicMock:
    thread = MagicMock()
    thread.id = uuid.uuid4()
    thread.user_id = user_id
    thread.trip_id = uuid.uuid4()
    thread.title = "Trip to Paris"
    thread.slug = "trip-to-paris-abc12345"
    thread.status = ThreadStatus.READY
    thread.created_at = datetime.now(timezone.utc)
    thread.updated_at = datetime.now(timezone.utc)
    return thread


def make_mock_trip(status: TripStatus = TripStatus.READY) -> MagicMock:
    trip = MagicMock()
    trip.id = uuid.uuid4()
    trip.status = status
    return trip


def make_mock_message(
    thread_id: uuid.UUID, role: str = "human", content: str = "Plan a trip"
) -> MagicMock:
    message = MagicMock()
    message.id = uuid.uuid4()
    message.thread_id = thread_id
    message.role = role
    message.content = content
    message.itinerary = None
    message.created_at = datetime.now(timezone.utc)
    return message


def patch_send_service(stack: ExitStack, *, trip: MagicMock) -> SimpleNamespace:
    """Patch the repository calls the service makes on a continuation turn."""
    create_message = AsyncMock()
    add_version = AsyncMock()
    stack.enter_context(patch(f"{_SVC_TRIP_REPO}.get_by_id", AsyncMock(return_value=trip)))
    stack.enter_context(patch(f"{_SVC_MESSAGE_REPO}.create_message", create_message))
    stack.enter_context(patch(f"{_SVC_VERSION_REPO}.add_version", add_version))
    stack.enter_context(patch(f"{_SVC_VERSION_REPO}.set_current", AsyncMock()))

    return SimpleNamespace(create_message=create_message, add_version=add_version)


# --- POST /threads/{thread_id}/messages ---


async def test_send_message_returns_200_with_itinerary(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    itinerary = make_itinerary("Tokyo")

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        stack.enter_context(patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)))
        patch_send_service(stack, trip=make_mock_trip())
        stack.enter_context(patch(_SVC_PLANNER, new=AsyncMock(return_value=make_plan_result(itinerary))))

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["result"]["type"] == "itinerary"
    assert response.json()["result"]["itinerary"]["destination"] == "Tokyo"


async def test_send_message_persists_itinerary_version(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        stack.enter_context(patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)))
        deps = patch_send_service(stack, trip=make_mock_trip())
        stack.enter_context(patch(_SVC_PLANNER, new=AsyncMock(return_value=make_plan_result())))

        await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    deps.add_version.assert_awaited_once()


async def test_send_message_passes_query_to_planner(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    query = "Add a day trip to Mount Fuji"

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        stack.enter_context(patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)))
        patch_send_service(stack, trip=make_mock_trip())
        planner = AsyncMock(return_value=make_plan_result())
        stack.enter_context(patch(_SVC_PLANNER, new=planner))

        await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert planner.call_args[0][0] == query
    assert planner.call_args[0][1] == str(thread.id)


async def test_send_message_returns_200_with_clarification(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    result = make_clarification_result()

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        stack.enter_context(patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)))
        patch_send_service(stack, trip=make_mock_trip())
        stack.enter_context(patch(_SVC_PLANNER, new=AsyncMock(return_value=result)))

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "somewhere warm"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["type"] == "clarification"
    expected_clarification = result.clarification
    assert expected_clarification is not None
    assert body["result"]["clarification"]["message"] == expected_clarification.message


async def test_send_message_returns_404_when_thread_not_found(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    missing_thread_id = uuid.uuid4()

    with (
        patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)),
        patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=None)),
    ):
        response = await db_client.post(
            f"/threads/{missing_thread_id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"


async def test_send_message_returns_403_for_cross_user_access(db_client: AsyncClient) -> None:
    owner = make_mock_user()
    requester = make_mock_user()
    token = create_access_token(str(requester.id))
    # Thread belongs to owner, but the request is authenticated as a different user
    thread = make_mock_thread(owner.id)

    with (
        patch(_DEPS_GET_USER, new=AsyncMock(return_value=requester)),
        patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)),
    ):
        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


async def test_send_message_returns_500_when_graph_returns_no_result(
    db_client: AsyncClient,
) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        stack.enter_context(patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)))
        patch_send_service(stack, trip=make_mock_trip())
        stack.enter_context(patch(_SVC_PLANNER, new=AsyncMock(return_value=PlannerOutcome())))

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Graph did not produce a structured itinerary or clarification"


async def test_send_message_propagates_planner_error(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with ExitStack() as stack:
        stack.enter_context(patch(_DEPS_GET_USER, new=AsyncMock(return_value=user)))
        stack.enter_context(patch(f"{_THREAD_REPO}.get_by_id", new=AsyncMock(return_value=thread)))
        patch_send_service(stack, trip=make_mock_trip())
        stack.enter_context(
            patch(_SVC_PLANNER, new=AsyncMock(side_effect=TimeoutError("planner exceeded the time limit")))
        )

        with pytest.raises(TimeoutError):
            await db_client.post(
                f"/threads/{thread.id}/messages",
                json={"query": "Add a day trip to Mount Fuji"},
                headers={"Authorization": f"Bearer {token}"},
            )


async def test_send_message_returns_401_without_token(db_client: AsyncClient) -> None:
    response = await db_client.post(
        f"/threads/{uuid.uuid4()}/messages",
        json={"query": "Add a day trip to Mount Fuji"},
    )

    assert response.status_code == 401


# --- GET /threads ---


async def test_list_threads_returns_200_with_thread_summaries(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.list_by_user", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_list.return_value = [thread]

        response = await db_client.get(
            "/threads",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["threads"]) == 1
    assert body["threads"][0]["title"] == thread.title
    assert body["threads"][0]["slug"] == thread.slug


async def test_list_threads_returns_empty_list_when_no_threads(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.list_by_user", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_list.return_value = []

        response = await db_client.get(
            "/threads",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["threads"] == []


async def test_list_threads_returns_next_cursor_when_page_is_full(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.list_by_user", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_list.return_value = [thread]

        response = await db_client.get(
            "/threads",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token}"},
        )

    next_cursor = response.json()["next_cursor"]
    assert next_cursor is not None
    assert decode_cursor(next_cursor) == (thread.updated_at, thread.id)


async def test_list_threads_omits_next_cursor_when_page_not_full(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.list_by_user", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_list.return_value = [thread]

        response = await db_client.get(
            "/threads",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.json()["next_cursor"] is None


async def test_list_threads_forwards_decoded_cursor_to_repository(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    cursor_at = datetime.now(timezone.utc)
    cursor_id = uuid.uuid4()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.list_by_user", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_list.return_value = []

        await db_client.get(
            "/threads",
            params={"cursor": encode_cursor(cursor_at, cursor_id)},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert mock_list.call_args.kwargs["cursor"] == (cursor_at, cursor_id)


async def test_list_threads_returns_400_for_invalid_cursor(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))

    with patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = user

        response = await db_client.get(
            "/threads",
            params={"cursor": "not-a-valid-cursor!!!"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid pagination cursor"


# --- GET /threads/{thread_id} ---


async def test_get_thread_returns_200_with_thread_and_messages(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    messages = [
        make_mock_message(thread.id, role="human", content="Plan a trip"),
        make_mock_message(thread.id, role="assistant", content="Here is your plan."),
    ]

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(f"{_MESSAGE_REPO}.list_by_thread", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_list.return_value = messages

        response = await db_client.get(
            f"/threads/{thread.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["thread"]["title"] == thread.title
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "human"
    assert body["messages"][1]["role"] == "assistant"


async def test_get_thread_returns_404_when_thread_not_found(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    missing_thread_id = uuid.uuid4()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = None

        response = await db_client.get(
            f"/threads/{missing_thread_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"


async def test_get_thread_returns_403_for_cross_user_access(db_client: AsyncClient) -> None:
    owner = make_mock_user()
    requester = make_mock_user()
    token = create_access_token(str(requester.id))
    # Thread belongs to owner, but the request is authenticated as a different user
    thread = make_mock_thread(owner.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = requester
        mock_get_thread.return_value = thread

        response = await db_client.get(
            f"/threads/{thread.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


async def test_get_thread_passes_pagination_params_to_repository(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(f"{_MESSAGE_REPO}.list_by_thread", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_list.return_value = []

        await db_client.get(
            f"/threads/{thread.id}",
            params={"limit": 5},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert mock_list.call_args.kwargs["limit"] == 5


async def test_get_thread_returns_next_cursor_when_page_is_full(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    message = make_mock_message(thread.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(f"{_MESSAGE_REPO}.list_by_thread", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_list.return_value = [message]

        response = await db_client.get(
            f"/threads/{thread.id}",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token}"},
        )

    next_cursor = response.json()["next_cursor"]
    assert next_cursor is not None
    assert decode_cursor(next_cursor) == (message.created_at, message.id)


async def test_get_thread_forwards_decoded_cursor_to_repository(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    cursor_at = datetime.now(timezone.utc)
    cursor_id = uuid.uuid4()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(f"{_MESSAGE_REPO}.list_by_thread", new_callable=AsyncMock) as mock_list,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_list.return_value = []

        await db_client.get(
            f"/threads/{thread.id}",
            params={"cursor": encode_cursor(cursor_at, cursor_id)},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert mock_list.call_args.kwargs["cursor"] == (cursor_at, cursor_id)


async def test_get_thread_returns_400_for_invalid_cursor(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread

        response = await db_client.get(
            f"/threads/{thread.id}",
            params={"cursor": "not-a-valid-cursor!!!"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid pagination cursor"


# --- DELETE /threads/{thread_id} ---


async def test_delete_thread_returns_204_and_soft_deletes(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(
            f"{_MESSAGE_REPO}.soft_delete_by_thread", new_callable=AsyncMock
        ) as mock_delete_messages,
        patch(f"{_THREAD_REPO}.soft_delete", new_callable=AsyncMock) as mock_delete_thread,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread

        response = await db_client.delete(
            f"/threads/{thread.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 204
    assert mock_delete_messages.call_count == 1
    assert mock_delete_thread.call_count == 1


async def test_delete_thread_returns_404_when_thread_not_found(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    missing_thread_id = uuid.uuid4()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = None

        response = await db_client.delete(
            f"/threads/{missing_thread_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"


async def test_delete_thread_returns_403_for_cross_user_access(db_client: AsyncClient) -> None:
    owner = make_mock_user()
    requester = make_mock_user()
    token = create_access_token(str(requester.id))
    # Thread belongs to owner, but the request is authenticated as a different user
    thread = make_mock_thread(owner.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = requester
        mock_get_thread.return_value = thread

        response = await db_client.delete(
            f"/threads/{thread.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
