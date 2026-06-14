# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage

from trip_planner.agents.state import TripPlannerState
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary
from trip_planner.services.auth_service import create_access_token

_DEPS_GET_USER = "trip_planner.api.dependencies.user_repository.get_user_by_id"
_THREAD_REPO = "trip_planner.api.routes.threads.thread_repository"
_MESSAGE_REPO = "trip_planner.api.routes.threads.message_repository"
_RUN_PLANNER = "trip_planner.api.routes.threads.run_planner"


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


def make_plan_result(itinerary: Itinerary | None = None) -> TripPlannerState:
    resolved = itinerary or make_itinerary()
    human_msg = HumanMessage(content="Paris 7 days")
    ai_msg = AIMessage(content="Here is your itinerary.")
    return TripPlannerState(
        messages=[human_msg, ai_msg],
        trip_request="Paris 7 days",
        draft_itinerary="",
        itinerary=resolved,
    )


def make_clarification_result(message: str = "Could you tell me where and how long?") -> TripPlannerState:
    clarification = ClarificationRequest(
        message=message,
        missing_fields=["destination", "duration"],
    )
    return TripPlannerState(
        messages=[],
        trip_request="plan me a trip",
        draft_itinerary="",
        clarification=clarification,
    )


def make_mock_thread(user_id: uuid.UUID) -> MagicMock:
    thread = MagicMock()
    thread.id = uuid.uuid4()
    thread.user_id = user_id
    thread.title = "Trip to Paris"
    thread.slug = "trip-to-paris-abc12345"
    thread.created_at = datetime.now(timezone.utc)
    thread.updated_at = datetime.now(timezone.utc)
    return thread


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


# --- POST /threads ---


async def test_create_thread_returns_201_with_thread_and_itinerary(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    itinerary = make_itinerary("Paris")
    result = make_plan_result(itinerary)
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.create_thread", new_callable=AsyncMock) as mock_create_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock),
    ):
        mock_get_user.return_value = user
        mock_create_thread.return_value = thread
        mock_planner.return_value = result

        response = await db_client.post(
            "/threads",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["thread"]["title"] == thread.title
    assert body["thread"]["slug"] == thread.slug
    assert body["result"]["type"] == "itinerary"
    assert body["result"]["itinerary"]["destination"] == "Paris"
    assert body["result"]["itinerary"]["total_days"] == 1


async def test_create_thread_passes_query_to_planner(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    query = "Plan a 7-day Paris trip for 2 people"
    result = make_plan_result()
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.create_thread", new_callable=AsyncMock) as mock_create_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock),
    ):
        mock_get_user.return_value = user
        mock_create_thread.return_value = thread
        mock_planner.return_value = result

        await db_client.post(
            "/threads",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
        )

    called_state: TripPlannerState = mock_planner.call_args[0][0]
    called_thread_id: str = mock_planner.call_args[1]["thread_id"]
    assert called_state["trip_request"] == query
    assert called_state["messages"][0].content == query
    assert called_thread_id == str(thread.id)


async def test_create_thread_persists_human_and_assistant_messages(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    itinerary = make_itinerary("Paris")
    result = make_plan_result(itinerary)
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.create_thread", new_callable=AsyncMock) as mock_create_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock) as mock_create_message,
    ):
        mock_get_user.return_value = user
        mock_create_thread.return_value = thread
        mock_planner.return_value = result

        await db_client.post(
            "/threads",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert mock_create_message.call_count == 2
    human_call = mock_create_message.call_args_list[0]
    assistant_call = mock_create_message.call_args_list[1]
    assert human_call.kwargs["role"] == "human"
    assert assistant_call.kwargs["role"] == "assistant"
    assert assistant_call.kwargs["content"] == itinerary.summary


async def test_create_thread_returns_500_when_graph_returns_no_itinerary(
    db_client: AsyncClient,
) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    empty_result = TripPlannerState(messages=[], trip_request="Paris 7 days", draft_itinerary="")

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.create_thread", new_callable=AsyncMock) as mock_create_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
    ):
        mock_get_user.return_value = user
        mock_create_thread.return_value = thread
        mock_planner.return_value = empty_result

        response = await db_client.post(
            "/threads",
            json={"query": "Plan a 7-day Paris trip for 2 people"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Graph did not produce a structured itinerary or clarification"


async def test_create_thread_returns_401_without_token(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/threads",
        json={"query": "Plan a 7-day Paris trip for 2 people"},
    )

    assert response.status_code == 401


async def test_create_thread_returns_422_for_query_too_short(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))

    with patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = user

        response = await db_client.post(
            "/threads",
            json={"query": "Paris"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422


# --- POST /threads/{thread_id}/messages ---


async def test_send_message_returns_200_with_itinerary(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    itinerary = make_itinerary("Tokyo")
    result = make_plan_result(itinerary)
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock),
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_planner.return_value = result

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["result"]["type"] == "itinerary"
    assert response.json()["result"]["itinerary"]["destination"] == "Tokyo"


async def test_send_message_passes_query_to_planner(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    query = "Add a day trip to Mount Fuji"
    result = make_plan_result()
    thread = make_mock_thread(user.id)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock),
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_planner.return_value = result

        await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
        )

    called_state: TripPlannerState = mock_planner.call_args[0][0]
    called_thread_id: str = mock_planner.call_args[1]["thread_id"]
    assert called_state["trip_request"] == query
    assert called_state["messages"][0].content == query
    assert called_thread_id == str(thread.id)


async def test_send_message_returns_404_when_thread_not_found(db_client: AsyncClient) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    missing_thread_id = uuid.uuid4()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = None

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
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
    ):
        mock_get_user.return_value = requester
        mock_get_thread.return_value = thread

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


async def test_send_message_returns_500_when_graph_returns_no_itinerary(
    db_client: AsyncClient,
) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    empty_result = TripPlannerState(messages=[], trip_request="", draft_itinerary="")

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_planner.return_value = empty_result

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "Add a day trip to Mount Fuji"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Graph did not produce a structured itinerary or clarification"


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


# --- Clarification responses ---


async def test_create_thread_returns_201_with_clarification_when_request_is_vague(
    db_client: AsyncClient,
) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    result = make_clarification_result()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.create_thread", new_callable=AsyncMock) as mock_create_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock),
    ):
        mock_get_user.return_value = user
        mock_create_thread.return_value = thread
        mock_planner.return_value = result

        response = await db_client.post(
            "/threads",
            json={"query": "Plan me a trip please help"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["result"]["type"] == "clarification"
    expected_clarification = result.get("clarification")
    assert expected_clarification is not None
    assert body["result"]["clarification"]["message"] == expected_clarification.message
    assert "destination" in body["result"]["clarification"]["missing_fields"]


async def test_create_thread_persists_clarification_as_assistant_message(
    db_client: AsyncClient,
) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    clarification_message = "Could you tell me where and how long?"
    result = make_clarification_result(clarification_message)

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.create_thread", new_callable=AsyncMock) as mock_create_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock) as mock_create_message,
    ):
        mock_get_user.return_value = user
        mock_create_thread.return_value = thread
        mock_planner.return_value = result

        await db_client.post(
            "/threads",
            json={"query": "Plan me a trip please help"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert mock_create_message.call_count == 2
    human_call = mock_create_message.call_args_list[0]
    assistant_call = mock_create_message.call_args_list[1]
    assert human_call.kwargs["role"] == "human"
    assert assistant_call.kwargs["role"] == "assistant"
    assert assistant_call.kwargs["content"] == clarification_message


async def test_send_message_returns_200_with_clarification_on_vague_follow_up(
    db_client: AsyncClient,
) -> None:
    user = make_mock_user()
    token = create_access_token(str(user.id))
    thread = make_mock_thread(user.id)
    result = make_clarification_result()

    with (
        patch(_DEPS_GET_USER, new_callable=AsyncMock) as mock_get_user,
        patch(f"{_THREAD_REPO}.get_by_id", new_callable=AsyncMock) as mock_get_thread,
        patch(_RUN_PLANNER, new_callable=AsyncMock) as mock_planner,
        patch(f"{_MESSAGE_REPO}.create_message", new_callable=AsyncMock),
    ):
        mock_get_user.return_value = user
        mock_get_thread.return_value = thread
        mock_planner.return_value = result

        response = await db_client.post(
            f"/threads/{thread.id}/messages",
            json={"query": "somewhere warm"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["type"] == "clarification"
    expected_clarification = result.get("clarification")
    assert expected_clarification is not None
    assert body["result"]["clarification"]["message"] == expected_clarification.message
