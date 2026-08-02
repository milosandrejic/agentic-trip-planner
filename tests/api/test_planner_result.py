import pytest
from fastapi import HTTPException

from trip_planner.agents.graph import PlannerOutcome
from trip_planner.api.planner_result import to_planner_result
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary


def make_itinerary() -> Itinerary:
    """Return a minimal valid itinerary."""
    activity = Activity(time="Morning", description="Visit the Eiffel Tower")

    return Itinerary(
        destination="Paris",
        total_days=1,
        summary="One day in Paris",
        days=[DayPlan(day=1, location="Paris", activities=[activity])],
    )


def test_maps_itinerary_outcome_to_itinerary_result() -> None:
    itinerary = make_itinerary()

    result = to_planner_result(PlannerOutcome(itinerary=itinerary))

    assert result.type == "itinerary"


def test_maps_clarification_outcome_to_clarification_result() -> None:
    clarification = ClarificationRequest(message="Where to?", missing_fields=["destination"])

    result = to_planner_result(PlannerOutcome(clarification=clarification))

    assert result.type == "clarification"


def test_raises_500_for_empty_outcome() -> None:
    with pytest.raises(HTTPException) as exc_info:
        to_planner_result(PlannerOutcome())

    assert exc_info.value.status_code == 500
