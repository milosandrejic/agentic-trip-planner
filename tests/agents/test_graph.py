# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from trip_planner.agents.graph import (
    _route_after_reason,
    _route_after_triage,
    format_node,
    reason_node,
    triage_node,
)
from trip_planner.agents.state import TripPlannerState
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary


def _make_state(messages: list[object], *, draft: str = "") -> TripPlannerState:
    return TripPlannerState(
        messages=messages,  # type: ignore[arg-type]
        trip_request="Paris 7 days",
        draft_itinerary=draft,
    )


def _make_itinerary() -> Itinerary:
    activity = Activity(time="Morning", description="Visit the Eiffel Tower")
    day = DayPlan(day=1, location="Paris", activities=[activity])
    return Itinerary(destination="Paris", total_days=1, summary="A great trip.", days=[day])


# --- _route_after_agent ---


def test_route_returns_tools_when_last_message_has_tool_calls() -> None:
    ai_message = AIMessage(
        content="",
        tool_calls=[{"name": "web_search", "args": {"query": "Paris"}, "id": "call_123"}],
    )
    state = _make_state([ai_message])

    result = _route_after_reason(state)

    assert result == "tools"


def test_route_returns_format_when_last_message_has_no_tool_calls() -> None:
    ai_message = AIMessage(content="Here is your itinerary.")
    state = _make_state([ai_message])

    result = _route_after_reason(state)

    assert result == "format"


def test_route_returns_format_for_non_ai_message() -> None:
    state = _make_state([HumanMessage(content="Paris 7 days")])

    result = _route_after_reason(state)

    assert result == "format"


# --- agent_node ---


async def test_agent_node_returns_updated_messages() -> None:
    ai_response = AIMessage(content="Let me search for that.")
    state = _make_state([HumanMessage(content="Paris 7 days")])

    with patch("trip_planner.agents.graph._llm_with_tools") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=ai_response)
        result = await reason_node(state)

    assert ai_response in result["messages"]
    assert result["trip_request"] == "Paris 7 days"
    assert result["draft_itinerary"] == ""


# --- format_node ---


async def test_format_node_returns_structured_itinerary() -> None:
    itinerary = _make_itinerary()
    state = _make_state([AIMessage(content="Here is your itinerary.")])

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=itinerary)
        result = await format_node(state)

    assert result.get("itinerary") == itinerary
    assert result["trip_request"] == "Paris 7 days"


# --- _route_after_triage ---


def test_route_after_triage_returns_end_when_clarification_is_set() -> None:
    clarification = ClarificationRequest(
        message="Could you tell me where and how long?",
        missing_fields=["destination", "duration"],
    )
    state = TripPlannerState(
        messages=[],
        trip_request="plan me a trip",
        draft_itinerary="",
        clarification=clarification,
    )

    result = _route_after_triage(state)

    assert result == "__end__"


def test_route_after_triage_returns_reason_when_no_clarification() -> None:
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days")],
        trip_request="Paris 7 days",
        draft_itinerary="",
    )

    result = _route_after_triage(state)

    assert result == "reason"


# --- triage_node ---


async def test_triage_node_sets_clarification_when_llm_decides_to_clarify() -> None:
    clarification = ClarificationRequest(
        message="Could you tell me where and how long?",
        missing_fields=["destination", "duration"],
    )

    from trip_planner.agents.graph import _TriageDecision

    decision = _TriageDecision(should_clarify=True, clarification=clarification)
    state = TripPlannerState(
        messages=[HumanMessage(content="plan me a trip")],
        trip_request="plan me a trip",
        draft_itinerary="",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("clarification") == clarification
    assert result["trip_request"] == "plan me a trip"


async def test_triage_node_sets_clarification_to_none_when_request_is_complete() -> None:
    from trip_planner.agents.graph import _TriageDecision

    decision = _TriageDecision(should_clarify=False, clarification=None)
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days in July, I like history")],
        trip_request="Paris 7 days in July, I like history",
        draft_itinerary="",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("clarification") is None
    assert result["trip_request"] == "Paris 7 days in July, I like history"
