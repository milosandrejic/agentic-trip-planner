# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

import trip_planner.agents.graph as graph_module
from trip_planner.agents.graph import (
    _route_after_reason,
    _route_after_triage,
    format_node,
    init_graph,
    reason_node,
    run_planner,
    triage_node,
)
from trip_planner.agents.state import TripPlannerState
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, Itinerary
from trip_planner.services.types import FlightOffer, FlightSearchResult, ToolResult


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


async def test_format_node_feeds_structured_tool_results_to_llm() -> None:
    itinerary = _make_itinerary()
    offer = FlightOffer(
        offer_id="off_1",
        airline="British Airways",
        stops=0,
        total_amount="250.00",
        currency="GBP",
        outbound_date="2026-08-01",
    )
    payload = FlightSearchResult(
        origin="LHR",
        destination="CDG",
        departure_date="2026-08-01",
        passengers=1,
        offers=[offer],
    )
    flight_result = ToolResult.ok(provider="duffel", data=payload)

    structured_tool_msg = ToolMessage(
        content="Option 1: British Airways",
        tool_call_id="call_1",
        name="flight_search_tool",
        artifact=flight_result,
    )
    web_tool_msg = ToolMessage(
        content="Raw web search text", tool_call_id="call_2", name="web_search"
    )
    state = _make_state([HumanMessage(content="Paris"), structured_tool_msg, web_tool_msg])

    captured: dict[str, list[BaseMessage]] = {}

    async def capture(messages: list[BaseMessage]) -> Itinerary:
        captured["messages"] = messages
        return itinerary

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(side_effect=capture)
        result = await format_node(state)

    sent = captured["messages"]
    flight_sent = next(
        m for m in sent if isinstance(m, ToolMessage) and m.tool_call_id == "call_1"
    )
    web_sent = next(m for m in sent if isinstance(m, ToolMessage) and m.tool_call_id == "call_2")

    # the structured tool message now carries the authoritative typed payload, not the summary
    assert flight_sent.content == flight_result.model_dump_json()
    assert "off_1" in flight_sent.content
    assert "Option 1" not in flight_sent.content
    # text-only tool output (web search) is left untouched
    assert web_sent.content == "Raw web search text"
    assert result.get("itinerary") == itinerary


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


# --- run_planner graph selection ---


async def test_run_planner_uses_stateful_graph_with_thread_id() -> None:
    state = _make_state([HumanMessage(content="Paris 7 days")])
    compiled = MagicMock()
    compiled.ainvoke = AsyncMock(return_value=state)

    with patch("trip_planner.agents.graph._compiled_graph", compiled):
        await run_planner(state, thread_id="abc-123")

    compiled.ainvoke.assert_awaited_once()
    config = compiled.ainvoke.call_args.args[1]
    assert config["configurable"]["thread_id"] == "abc-123"


async def test_run_planner_generates_thread_id_when_missing() -> None:
    state = _make_state([HumanMessage(content="Paris 7 days")])
    compiled = MagicMock()
    compiled.ainvoke = AsyncMock(return_value=state)

    with patch("trip_planner.agents.graph._compiled_graph", compiled):
        await run_planner(state)

    config = compiled.ainvoke.call_args.args[1]
    assert config["configurable"]["thread_id"]


async def test_run_planner_raises_when_not_initialized() -> None:
    state = _make_state([HumanMessage(content="Paris")])

    with (
        patch("trip_planner.agents.graph._compiled_graph", None),
        pytest.raises(RuntimeError, match="init_graph"),
    ):
        await run_planner(state)


def test_init_graph_compiles_graph_with_checkpointer() -> None:
    checkpointer = MagicMock()
    compiled = MagicMock()

    with (
        patch("trip_planner.agents.graph._compiled_graph", None),
        patch("trip_planner.agents.graph.build_graph", return_value=compiled) as mock_build,
    ):
        init_graph(checkpointer)

        assert graph_module._compiled_graph is compiled

    mock_build.assert_called_once_with(checkpointer=checkpointer)


# --- per-node LLM configuration ---


def test_triage_llm_is_deterministic() -> None:
    assert graph_module._triage_llm.temperature == 0.0


def test_format_llm_is_deterministic() -> None:
    assert graph_module._format_llm.temperature == 0.0


def test_reasoning_llm_is_creative() -> None:
    assert graph_module._reasoning_llm.temperature == 0.7


def test_per_node_llms_are_distinct_instances() -> None:
    llms = {id(graph_module._triage_llm), id(graph_module._format_llm), id(graph_module._reasoning_llm)}
    assert len(llms) == 3
