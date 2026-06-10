from langchain_core.messages import HumanMessage

from fastapi import APIRouter, HTTPException, status

from trip_planner.agents.graph import run_planner
from trip_planner.agents.state import TripPlannerState
from trip_planner.api.dependencies import CurrentUser
from trip_planner.schemas.trips import TripPlanRequest, TripPlanResponse

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("/plan", response_model=TripPlanResponse, status_code=200)
async def plan_trip(body: TripPlanRequest, _current_user: CurrentUser) -> TripPlanResponse:
    initial_state = TripPlannerState(
        messages=[HumanMessage(content=body.query)],
        trip_request=body.query,
        draft_itinerary="",
    )

    result = await run_planner(initial_state)

    itinerary = result.get("itinerary")
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Graph did not produce a structured itinerary",
        )

    return TripPlanResponse(itinerary=itinerary)
