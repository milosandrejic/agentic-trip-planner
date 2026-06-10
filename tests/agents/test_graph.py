# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from trip_planner.agents.graph import _route_after_reason, reason_node, format_node
from trip_planner.agents.state import TripPlannerState
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
