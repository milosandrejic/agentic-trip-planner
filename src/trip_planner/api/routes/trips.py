from fastapi import APIRouter, status

from trip_planner.api.dependencies import CurrentUser, DbSession
from trip_planner.api.planner_result import invalid_planner_outcome, to_planner_result
from trip_planner.models.trip import Trip
from trip_planner.schemas.trip_planning import (
    CreateTripRequest,
    CreateTripResponse,
    TripSummary,
)
from trip_planner.services.trip_planning_service import (
    PlannerContractError,
    TripPlanningService,
)

router = APIRouter(prefix="/trips", tags=["trips"])


def _to_trip_summary(trip: Trip) -> TripSummary:
    """Convert a Trip ORM instance to a TripSummary response schema."""
    return TripSummary(
        id=trip.id,
        title=trip.title,
        slug=trip.slug,
        destination=trip.destination,
        status=trip.status,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
    )


@router.post("", response_model=CreateTripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(
    body: CreateTripRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CreateTripResponse:
    """Create a trip and its thread, run the first planning turn, and return the result."""
    service = TripPlanningService(db)

    try:
        turn = await service.start_trip(current_user, body.query)
    except PlannerContractError:
        raise invalid_planner_outcome from None

    return CreateTripResponse(
        trip=_to_trip_summary(turn.trip),
        thread_id=turn.thread.id,
        result=to_planner_result(turn.outcome),
    )
