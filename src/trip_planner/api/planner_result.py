from fastapi import HTTPException, status

from trip_planner.agents.graph import PlannerOutcome
from trip_planner.schemas.threads import ClarificationResult, ItineraryResult, PlannerResult

# 500 because the graph completed without producing either a structured itinerary or a
# clarification, violating its own output contract.
invalid_planner_outcome = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Graph did not produce a structured itinerary or clarification",
)


def to_planner_result(outcome: PlannerOutcome) -> PlannerResult:
    """Map a planner outcome to the discriminated response result, or raise 500 if empty."""
    if outcome.clarification is not None:
        return ClarificationResult(clarification=outcome.clarification)

    itinerary = outcome.itinerary

    if itinerary is None:
        raise invalid_planner_outcome

    return ItineraryResult(itinerary=itinerary)
