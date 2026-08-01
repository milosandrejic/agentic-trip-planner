from fastapi import APIRouter, HTTPException, status

from trip_planner.agents.graph import plan_turn
from trip_planner.api.dependencies import CurrentUser
from trip_planner.schemas.trips import TripPlanRequest, TripPlanResponse

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("/plan", response_model=TripPlanResponse, status_code=200)
async def plan_trip(body: TripPlanRequest, _current_user: CurrentUser) -> TripPlanResponse:
    outcome = await plan_turn(body.query)

    itinerary = outcome.itinerary
    if itinerary is None:
        # 500 because the graph completed successfully but violated its contract by not
        # producing a structured itinerary.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Graph did not produce a structured itinerary",
        )

    return TripPlanResponse(itinerary=itinerary)
