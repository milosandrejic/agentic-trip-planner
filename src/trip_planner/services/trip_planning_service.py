import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.agents.graph import PlannerOutcome, plan_turn
from trip_planner.models.thread import Thread, ThreadStatus
from trip_planner.models.trip import Trip, TripStatus
from trip_planner.models.user import User
from trip_planner.repositories import (
    itinerary_version_repository,
    message_repository,
    thread_repository,
    trip_repository,
)
from trip_planner.services import trip_lifecycle

# Signature of the planning boundary the service depends on. Injected so tests can supply a
# stub instead of executing the real LangGraph run.
PlannerCallable = Callable[[str, str], Awaitable[PlannerOutcome]]


class PlannerContractError(Exception):
    """Raised when a planning run finishes with neither an itinerary nor a clarification."""


@dataclass
class TripTurnResult:
    """Outcome of one planning turn: the affected trip, its thread, and the planner result."""

    trip: Trip
    thread: Thread
    outcome: PlannerOutcome


class TripPlanningService:
    """Sole application entry point for planner orchestration.

    Owns the full turn lifecycle: persist the user's request, run the graph outside any open
    transaction, then commit the assistant response, itinerary version, and lifecycle transition
    atomically. Routers call this service instead of touching the graph or repositories directly.
    """

    def __init__(self, db: AsyncSession, planner: PlannerCallable | None = None) -> None:
        """Store the session and the planning callable (defaults to the real graph run)."""
        self._db = db
        # Resolved at construction so route tests can patch the module-level plan_turn.
        self._planner = planner or plan_turn

    async def start_trip(self, user: User, query: str) -> TripTurnResult:
        """Create a trip and its thread, run the first turn, and return the result.

        The request (trip, thread, and first human message) commits before the graph runs so the
        planner never executes inside an open transaction.
        """
        title = query[:80]

        trip = await trip_repository.create_trip(
            self._db, user_id=user.id, title=title, slug=self._make_slug(query)
        )
        thread = await thread_repository.create_thread(
            self._db, user_id=user.id, title=title, slug=self._make_slug(query)
        )
        thread.trip_id = trip.id

        await message_repository.create_message(
            self._db, thread_id=thread.id, role="human", content=query
        )

        previous_status = trip.status
        self._transition(trip, TripStatus.GENERATING)
        thread.status = ThreadStatus.RUNNING
        await self._db.commit()

        outcome = await self._run_turn(trip, thread, query, previous_status)

        return TripTurnResult(trip=trip, thread=thread, outcome=outcome)

    async def continue_trip(self, thread: Thread, query: str) -> TripTurnResult:
        """Append a follow-up message to an existing trip's thread and run the next turn."""
        if thread.trip_id is None:
            raise PlannerContractError("Thread is not linked to a trip")

        trip = await trip_repository.get_by_id(self._db, thread.trip_id)

        if trip is None:
            raise PlannerContractError("Thread's trip no longer exists")

        await message_repository.create_message(
            self._db, thread_id=thread.id, role="human", content=query
        )

        previous_status = trip.status
        self._transition(trip, TripStatus.GENERATING)
        thread.status = ThreadStatus.RUNNING
        await self._db.commit()

        outcome = await self._run_turn(trip, thread, query, previous_status)

        return TripTurnResult(trip=trip, thread=thread, outcome=outcome)

    async def _run_turn(
        self, trip: Trip, thread: Thread, query: str, previous_status: TripStatus
    ) -> PlannerOutcome:
        """Run the graph outside the request transaction, then persist its outcome atomically."""
        try:
            outcome = await self._planner(query, str(thread.id))
        except Exception:
            # The graph failed; restore the trip and flag the thread so clients can retry.
            await self._restore_failed(trip, thread, previous_status)
            raise

        try:
            await self._persist_outcome(trip, thread, outcome)
        except Exception:
            # Any partial write is discarded so the response, version, and transition stay atomic.
            await self._db.rollback()
            await self._restore_failed(trip, thread, previous_status)
            raise

        return outcome

    async def _persist_outcome(
        self, trip: Trip, thread: Thread, outcome: PlannerOutcome
    ) -> None:
        """Commit the assistant response, itinerary version, and lifecycle transition together."""
        if outcome.clarification is not None:
            await message_repository.create_message(
                self._db,
                thread_id=thread.id,
                role="assistant",
                content=outcome.clarification.message,
            )
            self._transition(trip, TripStatus.DRAFT)
        elif outcome.itinerary is not None:
            snapshot = outcome.itinerary.model_dump()
            version = await itinerary_version_repository.add_version(
                self._db, trip.id, snapshot
            )
            await itinerary_version_repository.set_current(self._db, trip, version)
            trip.destination = outcome.itinerary.destination
            await message_repository.create_message(
                self._db,
                thread_id=thread.id,
                role="assistant",
                content=outcome.itinerary.summary,
                itinerary=snapshot,
            )
            self._transition(trip, TripStatus.READY)
        else:
            raise PlannerContractError(
                "Planner produced neither an itinerary nor a clarification"
            )

        thread.status = ThreadStatus.READY
        await self._db.commit()
        # Server-side onupdate expires updated_at on commit; reload so the caller can serialize
        # the trip synchronously without triggering an illegal async lazy-load.
        await self._db.refresh(trip)

    async def _restore_failed(
        self, trip: Trip, thread: Thread, previous_status: TripStatus
    ) -> None:
        """Reset the trip to its pre-turn state and mark the thread FAILED.

        This is a recovery, not a user-driven transition, so it bypasses the lifecycle guard and
        restores exactly the status the trip held before the turn began.
        """
        trip.status = previous_status
        thread.status = ThreadStatus.FAILED
        await self._db.commit()

    def _transition(self, trip: Trip, target: TripStatus) -> None:
        """Move the trip to `target`, rejecting transitions the lifecycle forbids."""
        trip_lifecycle.assert_transition(trip.status, target)
        trip.status = target

    def _make_slug(self, text: str) -> str:
        """Build a URL-safe slug from text with a random suffix to prevent collisions."""
        cleaned = re.sub(r"[^a-z0-9]+", "-", text[:60].lower()).strip("-")
        suffix = uuid.uuid4().hex[:8]

        return f"{cleaned}-{suffix}"
