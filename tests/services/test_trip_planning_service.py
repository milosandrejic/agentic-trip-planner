import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest import MonkeyPatch

from trip_planner.agents.graph import PlannerOutcome
from trip_planner.models.thread import Thread, ThreadStatus
from trip_planner.models.trip import Trip, TripStatus
from trip_planner.models.user import User
from trip_planner.repositories import (
    itinerary_version_repository,
    message_repository,
    thread_repository,
    trip_repository,
)
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary
from trip_planner.services.trip_planning_service import (
    PlannerContractError,
    TripPlanningService,
)


def make_user() -> User:
    """Return a User with an id for service tests."""
    return User(id=uuid.uuid4(), email="traveler@example.com")


def make_trip(status: TripStatus = TripStatus.DRAFT) -> Trip:
    """Return a Trip with an id and explicit status (defaults are applied only at flush)."""
    trip = Trip(id=uuid.uuid4(), user_id=uuid.uuid4(), title="Paris", slug="paris-abc123")
    trip.status = status
    return trip


def make_thread(trip_id: uuid.UUID | None = None) -> Thread:
    """Return a Thread with an id and explicit status."""
    thread = Thread(id=uuid.uuid4(), user_id=uuid.uuid4(), title="Paris", slug="paris-def456")
    thread.status = ThreadStatus.PENDING
    thread.trip_id = trip_id
    return thread


def make_itinerary() -> Itinerary:
    """Return a minimal valid itinerary."""
    activity = Activity(time="Morning", description="Louvre visit")

    return Itinerary(
        destination="Paris",
        total_days=1,
        summary="One day in Paris",
        days=[DayPlan(day=1, location="Paris", activities=[activity])],
    )


def make_clarification() -> ClarificationRequest:
    """Return a clarification request missing the destination."""
    return ClarificationRequest(
        message="Where would you like to go?", missing_fields=["destination"]
    )


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


def patch_repositories(
    monkeypatch: MonkeyPatch,
    *,
    trip: Trip,
    thread: Thread,
    version_id: uuid.UUID | None = None,
) -> None:
    """Replace repository calls with stubs that return the given trip and thread."""
    monkeypatch.setattr(trip_repository, "create_trip", AsyncMock(return_value=trip))
    monkeypatch.setattr(trip_repository, "get_by_id", AsyncMock(return_value=trip))
    monkeypatch.setattr(thread_repository, "create_thread", AsyncMock(return_value=thread))
    monkeypatch.setattr(message_repository, "create_message", AsyncMock())

    version = MagicMock()
    version.id = version_id or uuid.uuid4()
    monkeypatch.setattr(
        itinerary_version_repository, "add_version", AsyncMock(return_value=version)
    )
    monkeypatch.setattr(itinerary_version_repository, "set_current", AsyncMock())


# --- start_trip ---


async def test_start_trip_persists_version_and_marks_ready(monkeypatch: MonkeyPatch) -> None:
    trip = make_trip()
    thread = make_thread()
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    itinerary = make_itinerary()
    planner = AsyncMock(return_value=PlannerOutcome(itinerary=itinerary))
    db = make_db()

    result = await TripPlanningService(db, planner=planner).start_trip(make_user(), "Plan Paris")

    assert result.outcome.itinerary is itinerary
    assert trip.status is TripStatus.READY
    assert thread.status is ThreadStatus.READY
    assert thread.trip_id == trip.id
    itinerary_version_repository.add_version.assert_awaited_once()  # type: ignore[attr-defined]
    itinerary_version_repository.set_current.assert_awaited_once()  # type: ignore[attr-defined]
    # Request commit followed by the atomic response commit.
    assert db.commit.await_count == 2


async def test_start_trip_with_clarification_returns_to_draft(monkeypatch: MonkeyPatch) -> None:
    trip = make_trip()
    thread = make_thread()
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    planner = AsyncMock(return_value=PlannerOutcome(clarification=make_clarification()))
    db = make_db()

    result = await TripPlanningService(db, planner=planner).start_trip(make_user(), "Plan a trip")

    assert result.outcome.clarification is not None
    assert trip.status is TripStatus.DRAFT
    assert thread.status is ThreadStatus.READY
    itinerary_version_repository.add_version.assert_not_awaited()  # type: ignore[attr-defined]


async def test_start_trip_marks_failed_when_planner_raises(monkeypatch: MonkeyPatch) -> None:
    trip = make_trip()
    thread = make_thread()
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    planner = AsyncMock(side_effect=RuntimeError("graph exploded"))
    db = make_db()

    with pytest.raises(RuntimeError, match="graph exploded"):
        await TripPlanningService(db, planner=planner).start_trip(make_user(), "Plan Paris")

    # The trip is restored to its pre-turn status and the thread flags the failure.
    assert trip.status is TripStatus.DRAFT
    assert thread.status is ThreadStatus.FAILED


async def test_start_trip_raises_contract_error_on_empty_outcome(
    monkeypatch: MonkeyPatch,
) -> None:
    trip = make_trip()
    thread = make_thread()
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    planner = AsyncMock(return_value=PlannerOutcome())
    db = make_db()

    with pytest.raises(PlannerContractError):
        await TripPlanningService(db, planner=planner).start_trip(make_user(), "Plan Paris")

    assert trip.status is TripStatus.DRAFT
    assert thread.status is ThreadStatus.FAILED


async def test_start_trip_rolls_back_and_fails_when_response_commit_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    trip = make_trip()
    thread = make_thread()
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    planner = AsyncMock(return_value=PlannerOutcome(itinerary=make_itinerary()))
    db = make_db()
    # Only the atomic response commit fails; the recovery commit must still succeed.
    db.commit.side_effect = [None, RuntimeError("commit failed"), None]

    with pytest.raises(RuntimeError, match="commit failed"):
        await TripPlanningService(db, planner=planner).start_trip(make_user(), "Plan Paris")

    db.rollback.assert_awaited_once()
    assert trip.status is TripStatus.DRAFT
    assert thread.status is ThreadStatus.FAILED


# --- continue_trip ---


async def test_continue_trip_appends_version_and_marks_ready(monkeypatch: MonkeyPatch) -> None:
    trip = make_trip(status=TripStatus.READY)
    thread = make_thread(trip_id=trip.id)
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    itinerary = make_itinerary()
    planner = AsyncMock(return_value=PlannerOutcome(itinerary=itinerary))
    db = make_db()

    result = await TripPlanningService(db, planner=planner).continue_trip(thread, "Add a day")

    assert result.outcome.itinerary is itinerary
    assert trip.status is TripStatus.READY
    assert thread.status is ThreadStatus.READY
    itinerary_version_repository.add_version.assert_awaited_once()  # type: ignore[attr-defined]


async def test_continue_trip_restores_previous_status_on_planner_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    trip = make_trip(status=TripStatus.READY)
    thread = make_thread(trip_id=trip.id)
    patch_repositories(monkeypatch, trip=trip, thread=thread)

    planner = AsyncMock(side_effect=RuntimeError("graph exploded"))
    db = make_db()

    with pytest.raises(RuntimeError, match="graph exploded"):
        await TripPlanningService(db, planner=planner).continue_trip(thread, "Add a day")

    # A failed modification leaves the previously-ready trip intact.
    assert trip.status is TripStatus.READY
    assert thread.status is ThreadStatus.FAILED


async def test_continue_trip_raises_when_thread_has_no_trip(monkeypatch: MonkeyPatch) -> None:
    thread = make_thread(trip_id=None)
    planner = AsyncMock()
    db = make_db()

    with pytest.raises(PlannerContractError):
        await TripPlanningService(db, planner=planner).continue_trip(thread, "Add a day")

    planner.assert_not_awaited()


async def test_continue_trip_raises_when_trip_missing(monkeypatch: MonkeyPatch) -> None:
    thread = make_thread(trip_id=uuid.uuid4())
    monkeypatch.setattr(trip_repository, "get_by_id", AsyncMock(return_value=None))
    planner = AsyncMock()
    db = make_db()

    with pytest.raises(PlannerContractError):
        await TripPlanningService(db, planner=planner).continue_trip(thread, "Add a day")

    planner.assert_not_awaited()
