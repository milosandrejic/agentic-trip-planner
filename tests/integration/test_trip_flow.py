import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.agents.graph import PlannerOutcome
from trip_planner.models.itinerary_version import ItineraryVersion
from trip_planner.models.message import Message
from trip_planner.models.thread import Thread, ThreadStatus
from trip_planner.models.trip import Trip, TripStatus
from trip_planner.models.user import User
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary

_PLANNER = "trip_planner.services.trip_planning_service.plan_turn"


def make_itinerary(destination: str = "Paris", summary: str = "A lovely trip") -> Itinerary:
    """Return a minimal valid itinerary for the given destination."""
    activity = Activity(time="Morning", description=f"Explore {destination}")

    return Itinerary(
        destination=destination,
        total_days=1,
        summary=summary,
        days=[DayPlan(day=1, location=destination, activities=[activity])],
    )


def install_planner(monkeypatch: pytest.MonkeyPatch, outcome: PlannerOutcome) -> None:
    """Patch the service's planner boundary to return a fixed outcome."""

    async def fake_plan_turn(query: str, thread_id: str) -> PlannerOutcome:
        """Deterministic stand-in for the LangGraph run."""
        return outcome

    monkeypatch.setattr(_PLANNER, fake_plan_turn)


async def test_create_trip_persists_trip_thread_version_and_messages(
    integration_client: AsyncClient,
    integration_db: AsyncSession,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /trips runs the first turn and commits every artifact of a ready trip."""
    install_planner(monkeypatch, PlannerOutcome(itinerary=make_itinerary("Rome")))

    response = await integration_client.post(
        "/trips", json={"query": "Plan three days in Rome"}, headers=auth_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["trip"]["status"] == "ready"
    assert body["result"]["type"] == "itinerary"
    assert body["result"]["itinerary"]["destination"] == "Rome"

    trip_id = uuid.UUID(body["trip"]["id"])
    trip = await integration_db.get(Trip, trip_id)
    assert trip is not None
    assert trip.status == TripStatus.READY
    assert trip.current_version_id is not None

    versions = (
        await integration_db.execute(
            select(ItineraryVersion).where(ItineraryVersion.trip_id == trip_id)
        )
    ).scalars().all()
    assert len(versions) == 1
    assert versions[0].version_number == 1
    assert trip.current_version_id == versions[0].id

    thread = await integration_db.get(Thread, uuid.UUID(body["thread_id"]))
    assert thread is not None
    assert thread.trip_id == trip_id
    assert thread.status == ThreadStatus.READY

    messages = (
        await integration_db.execute(
            select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert [message.role for message in messages] == ["human", "assistant"]
    assert messages[1].itinerary is not None


async def test_create_trip_with_clarification_leaves_trip_in_draft(
    integration_client: AsyncClient,
    integration_db: AsyncSession,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clarification outcome records the question and keeps the trip in draft with no version."""
    clarification = ClarificationRequest(
        message="Which city do you want to visit?", missing_fields=["destination"]
    )
    install_planner(monkeypatch, PlannerOutcome(clarification=clarification))

    response = await integration_client.post(
        "/trips", json={"query": "I want to travel somewhere"}, headers=auth_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["result"]["type"] == "clarification"
    assert body["trip"]["status"] == "draft"

    trip_id = uuid.UUID(body["trip"]["id"])
    trip = await integration_db.get(Trip, trip_id)
    assert trip is not None
    assert trip.status == TripStatus.DRAFT
    assert trip.current_version_id is None

    versions = (
        await integration_db.execute(
            select(ItineraryVersion).where(ItineraryVersion.trip_id == trip_id)
        )
    ).scalars().all()
    assert versions == []

    messages = (
        await integration_db.execute(
            select(Message)
            .where(Message.thread_id == uuid.UUID(body["thread_id"]))
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "Which city do you want to visit?"
    assert messages[-1].itinerary is None


async def test_continue_trip_appends_second_version(
    integration_client: AsyncClient,
    integration_db: AsyncSession,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A follow-up message runs another turn and appends a second version made current."""
    install_planner(monkeypatch, PlannerOutcome(itinerary=make_itinerary("Lisbon", "Draft one")))
    created = await integration_client.post(
        "/trips", json={"query": "Plan a weekend in Lisbon"}, headers=auth_headers
    )
    trip_id = uuid.UUID(created.json()["trip"]["id"])
    thread_id = created.json()["thread_id"]

    install_planner(monkeypatch, PlannerOutcome(itinerary=make_itinerary("Lisbon", "Draft two")))
    response = await integration_client.post(
        f"/threads/{thread_id}/messages",
        json={"query": "Add a day trip to Sintra"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["result"]["itinerary"]["summary"] == "Draft two"

    versions = (
        await integration_db.execute(
            select(ItineraryVersion)
            .where(ItineraryVersion.trip_id == trip_id)
            .order_by(ItineraryVersion.version_number)
        )
    ).scalars().all()
    assert [version.version_number for version in versions] == [1, 2]

    trip = await integration_db.get(Trip, trip_id)
    assert trip is not None
    assert trip.status == TripStatus.READY
    assert trip.current_version_id == versions[1].id

    messages = (
        await integration_db.execute(
            select(Message)
            .where(Message.thread_id == uuid.UUID(thread_id))
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert [message.role for message in messages] == [
        "human",
        "assistant",
        "human",
        "assistant",
    ]


async def test_planner_failure_marks_thread_failed_and_restores_trip(
    integration_client: AsyncClient,
    integration_db: AsyncSession,
    test_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing planner rolls the trip back to draft and flags the thread as failed."""

    async def boom(query: str, thread_id: str) -> PlannerOutcome:
        """Simulate a graph execution failure."""
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(_PLANNER, boom)

    with pytest.raises(RuntimeError, match="graph exploded"):
        await integration_client.post(
            "/trips", json={"query": "Plan a trip to Oslo"}, headers=auth_headers
        )

    trip = (
        await integration_db.execute(select(Trip).where(Trip.user_id == test_user.id))
    ).scalar_one()
    assert trip.status == TripStatus.DRAFT
    assert trip.current_version_id is None

    thread = (
        await integration_db.execute(select(Thread).where(Thread.user_id == test_user.id))
    ).scalar_one()
    assert thread.status == ThreadStatus.FAILED

    versions = (
        await integration_db.execute(
            select(ItineraryVersion).where(ItineraryVersion.trip_id == trip.id)
        )
    ).scalars().all()
    assert versions == []
