# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

import trip_planner.agents.graph as graph_module
from trip_planner.agents.graph import (
    PlannerOutcome,
    _dedupe_flights,
    _route_after_reason,
    _route_after_triage,
    format_node,
    init_graph,
    plan_turn,
    reason_node,
    run_planner,
    triage_node,
)
from trip_planner.agents.state import TripPlannerState, UpdateScope
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Activity, DayPlan, FlightOption, HotelOption, Itinerary
from trip_planner.services.types import FlightOffer, FlightSearchResult, ToolResult


def _make_state(messages: list[object]) -> TripPlannerState:
    return TripPlannerState(
        messages=messages,  # type: ignore[arg-type]
        trip_request="Paris 7 days",
    )


def _make_itinerary() -> Itinerary:
    activity = Activity(time="Morning", description="Visit the Eiffel Tower")
    day = DayPlan(day=1, location="Paris", activities=[activity])
    return Itinerary(destination="Paris", total_days=1, summary="A great trip.", days=[day])


def _make_multi_day_itinerary(days_count: int, total_days: int) -> Itinerary:
    """Return an itinerary with days_count DayPlan entries but a stated total_days."""
    days = [
        DayPlan(
            day=i,
            location="Paris",
            activities=[Activity(time="Morning", description=f"Day {i} activity")],
        )
        for i in range(1, days_count + 1)
    ]

    return Itinerary(
        destination="Paris", total_days=total_days, summary="A great trip.", days=days
    )


def _make_flight(airline: str = "British Airways", price: float = 250.00) -> FlightOption:
    return FlightOption(
        airline=airline,
        stops=0,
        duration_min=90,
        price=price,
        currency="GBP",
        outbound_date="2026-08-01",
        return_date="2026-08-08",
    )


def _make_hotel(name: str = "Hotel Le Marais") -> HotelOption:
    return HotelOption(name=name, nightly_price=95.00, currency="EUR")


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


async def test_reason_node_counts_tool_calls_against_the_budget() -> None:
    ai_response = AIMessage(
        content="",
        tool_calls=[
            {"name": "web_search", "args": {"query": "Paris"}, "id": "call_1"},
            {"name": "weather", "args": {"city": "Paris"}, "id": "call_2"},
        ],
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days")],
        trip_request="Paris 7 days",
        tool_call_count=3,
    )

    with patch("trip_planner.agents.graph._llm_with_tools") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=ai_response)
        result = await reason_node(state)

    assert result.get("tool_call_count") == 5


async def test_reason_node_drops_tools_once_budget_is_exhausted() -> None:
    from trip_planner.agents.graph import _MAX_TOOL_CALLS

    final_answer = AIMessage(content="Here is your itinerary.")
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days")],
        trip_request="Paris 7 days",
        tool_call_count=_MAX_TOOL_CALLS,
    )

    with (
        patch("trip_planner.agents.graph._reasoning_llm") as mock_reasoning,
        patch("trip_planner.agents.graph._llm_with_tools") as mock_with_tools,
    ):
        mock_reasoning.ainvoke = AsyncMock(return_value=final_answer)
        mock_with_tools.ainvoke = AsyncMock()
        result = await reason_node(state)

    mock_reasoning.ainvoke.assert_awaited_once()
    mock_with_tools.ainvoke.assert_not_awaited()
    assert _route_after_reason(result) == "format"
    assert result.get("tool_call_count") == _MAX_TOOL_CALLS


async def test_reason_node_injects_hotel_constraint_reminder_when_price_set() -> None:
    ai_response = AIMessage(content="")
    state = TripPlannerState(
        messages=[HumanMessage(content="cheaper hotels please")],
        trip_request="cheaper hotels please",
        hotel_max_nightly_price=150.0,
    )

    with patch("trip_planner.agents.graph._llm_with_tools") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=ai_response)
        await reason_node(state)

    await_args = mock_llm.ainvoke.await_args
    assert await_args is not None
    sent_messages = await_args.args[0]
    reminder = sent_messages[-1]
    assert "max_nightly_price=150.0" in reminder.content


async def test_reason_node_injects_hotel_constraint_reminder_when_stars_set() -> None:
    ai_response = AIMessage(content="")
    state = TripPlannerState(
        messages=[HumanMessage(content="3 or 4-star hotels please")],
        trip_request="3 or 4-star hotels please",
        hotel_min_star_rating=3.0,
    )

    with patch("trip_planner.agents.graph._llm_with_tools") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=ai_response)
        await reason_node(state)

    await_args = mock_llm.ainvoke.await_args
    assert await_args is not None
    sent_messages = await_args.args[0]
    reminder = sent_messages[-1]
    assert "min_star_rating=3.0" in reminder.content


async def test_reason_node_omits_hotel_constraint_reminder_when_unset() -> None:
    ai_response = AIMessage(content="")
    state = _make_state([HumanMessage(content="Paris 7 days")])

    with patch("trip_planner.agents.graph._llm_with_tools") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=ai_response)
        await reason_node(state)

    await_args = mock_llm.ainvoke.await_args
    assert await_args is not None
    sent_messages = await_args.args[0]
    assert not any("hotel_search_tool" in getattr(m, "content", "") for m in sent_messages)


async def test_reason_node_logs_trailing_tool_results() -> None:
    """A ToolMessage batch appended by the tools node must be logged before reasoning again."""
    structured_result = ToolResult.ok(
        provider="duffel",
        data=FlightSearchResult(
            origin="LHR", destination="CDG", departure_date="2026-08-01", passengers=1, offers=[]
        ),
    )
    structured_tool_msg = ToolMessage(
        content="No flights found.",
        tool_call_id="call_1",
        name="flight_search_tool",
        artifact=structured_result,
    )
    web_tool_msg = ToolMessage(
        content="Raw web search text", tool_call_id="call_2", name="web_search"
    )
    state = _make_state([HumanMessage(content="Paris"), structured_tool_msg, web_tool_msg])

    with (
        patch("trip_planner.agents.graph._llm_with_tools") as mock_llm,
        patch("trip_planner.agents.graph._logger") as mock_logger,
    ):
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Done."))
        await reason_node(state)

    logged_tools = [
        call.kwargs["tool"]
        for call in mock_logger.debug.call_args_list
        if call.args and call.args[0] == "followup.tool_result"
    ]
    assert logged_tools == ["flight_search_tool", "web_search"]


# --- format_node ---


async def test_format_node_returns_structured_itinerary() -> None:
    itinerary = _make_itinerary()
    state = _make_state([AIMessage(content="Here is your itinerary.")])

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=itinerary)
        result = await format_node(state)

    assert result.get("current_itinerary") == itinerary
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
    assert result.get("current_itinerary") == itinerary
    # the typed tool payloads are surfaced on the state, web-search text is excluded
    assert result.get("tool_results") == [flight_result]


# --- _dedupe_flights ---


def test_dedupe_flights_removes_identical_offers_preserving_order() -> None:
    first = _make_flight()
    duplicate = _make_flight()
    other = _make_flight(airline="Ryanair", price=90.00)

    result = _dedupe_flights([first, duplicate, other])

    assert result == [first, other]


def test_dedupe_flights_keeps_offers_differing_by_price() -> None:
    cheap = _make_flight(price=90.00)
    pricey = _make_flight(price=250.00)

    result = _dedupe_flights([cheap, pricey])

    assert result == [cheap, pricey]


async def test_format_node_deduplicates_flight_offers() -> None:
    itinerary = _make_itinerary().model_copy(
        update={"flights": [_make_flight(), _make_flight(), _make_flight(airline="Ryanair")]}
    )
    state = _make_state([AIMessage(content="Here is your itinerary.")])

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=itinerary)
        result = await format_node(state)

    flights = result["current_itinerary"].flights  # type: ignore[union-attr]
    assert [flight.airline for flight in flights] == ["British Airways", "Ryanair"]


async def test_format_node_retries_until_all_requested_days_present() -> None:
    short = _make_multi_day_itinerary(1, 3)
    full = _make_multi_day_itinerary(3, 3)
    state = _make_state([AIMessage(content="Here is your itinerary.")])

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(side_effect=[short, full])
        result = await format_node(state)

    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert len(itinerary.days) == 3
    assert mock_llm.ainvoke.await_count == 2


async def test_format_node_does_not_retry_when_all_days_present() -> None:
    full = _make_multi_day_itinerary(3, 3)
    state = _make_state([AIMessage(content="Here is your itinerary.")])

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=full)
        result = await format_node(state)

    assert result.get("current_itinerary") is not None
    assert mock_llm.ainvoke.await_count == 1


async def test_format_node_keeps_fullest_itinerary_after_max_attempts() -> None:
    first = _make_multi_day_itinerary(1, 3)
    second = _make_multi_day_itinerary(2, 3)
    third = _make_multi_day_itinerary(1, 3)
    state = _make_state([AIMessage(content="Here is your itinerary.")])

    with patch("trip_planner.agents.graph._llm_structured") as mock_llm:
        mock_llm.ainvoke = AsyncMock(side_effect=[first, second, third])
        result = await format_node(state)

    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert len(itinerary.days) == 2
    assert mock_llm.ainvoke.await_count == 3


async def test_format_node_hotels_scope_formats_only_hotels_section() -> None:
    previous = _make_multi_day_itinerary(3, 3).model_copy(
        update={"flights": [_make_flight()], "hotels": [_make_hotel("Old Hotel")]}
    )
    hotels_only = graph_module._HotelsOnly(hotels=[_make_hotel("New Hotel")])
    state = _make_state([AIMessage(content="Swapped the hotel.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.HOTELS

    with (
        patch("trip_planner.agents.graph._llm_hotels_only") as mock_hotels,
        patch("trip_planner.agents.graph._llm_structured") as mock_full,
    ):
        mock_hotels.ainvoke = AsyncMock(return_value=hotels_only)
        result = await format_node(state)

    mock_full.ainvoke.assert_not_called()
    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert len(itinerary.days) == 3
    assert [hotel.name for hotel in itinerary.hotels] == ["New Hotel"]
    assert [flight.airline for flight in itinerary.flights] == ["British Airways"]


async def test_format_node_hotels_scope_falls_back_to_previous_when_empty() -> None:
    previous = _make_itinerary().model_copy(update={"hotels": [_make_hotel("Stay")]})
    state = _make_state([AIMessage(content="Swapped the hotel.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.HOTELS

    with patch("trip_planner.agents.graph._llm_hotels_only") as mock_hotels:
        mock_hotels.ainvoke = AsyncMock(return_value=graph_module._HotelsOnly(hotels=[]))
        result = await format_node(state)

    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert [hotel.name for hotel in itinerary.hotels] == ["Stay"]


async def test_format_node_flights_scope_formats_only_flights_section() -> None:
    previous = _make_multi_day_itinerary(3, 3).model_copy(
        update={"flights": [_make_flight("Old Air")], "hotels": [_make_hotel("Stay")]}
    )
    flights_only = graph_module._FlightsOnly(flights=[_make_flight("New Air")])
    state = _make_state([AIMessage(content="Swapped the flight.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.FLIGHTS

    with (
        patch("trip_planner.agents.graph._llm_flights_only") as mock_flights,
        patch("trip_planner.agents.graph._llm_structured") as mock_full,
    ):
        mock_flights.ainvoke = AsyncMock(return_value=flights_only)
        result = await format_node(state)

    mock_full.ainvoke.assert_not_called()
    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert len(itinerary.days) == 3
    assert [flight.airline for flight in itinerary.flights] == ["New Air"]
    assert [hotel.name for hotel in itinerary.hotels] == ["Stay"]


async def test_format_node_flights_scope_dedupes_and_falls_back_when_empty() -> None:
    previous = _make_itinerary().model_copy(update={"flights": [_make_flight("Old Air")]})
    duplicate_flight = _make_flight("New Air")
    state = _make_state([AIMessage(content="Swapped the flight.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.FLIGHTS

    with patch("trip_planner.agents.graph._llm_flights_only") as mock_flights:
        mock_flights.ainvoke = AsyncMock(
            return_value=graph_module._FlightsOnly(flights=[duplicate_flight, duplicate_flight])
        )
        result = await format_node(state)

    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert [flight.airline for flight in itinerary.flights] == ["New Air"]


async def test_format_node_itinerary_scope_formats_only_days_section() -> None:
    previous = _make_multi_day_itinerary(3, 3).model_copy(
        update={"flights": [_make_flight()], "hotels": [_make_hotel("Stay")]}
    )
    new_days = _make_multi_day_itinerary(2, 2)
    days_only = graph_module._DaysOnly(total_days=2, days=new_days.days)
    state = _make_state([AIMessage(content="Shorten the trip.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.ITINERARY

    with (
        patch("trip_planner.agents.graph._llm_days_only") as mock_days,
        patch("trip_planner.agents.graph._llm_structured") as mock_full,
    ):
        mock_days.ainvoke = AsyncMock(return_value=days_only)
        result = await format_node(state)

    mock_full.ainvoke.assert_not_called()
    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert itinerary.total_days == 2
    assert len(itinerary.days) == 2
    assert [flight.airline for flight in itinerary.flights] == ["British Airways"]
    assert [hotel.name for hotel in itinerary.hotels] == ["Stay"]


async def test_format_node_itinerary_scope_retries_until_all_days_present() -> None:
    previous = _make_itinerary()
    short = graph_module._DaysOnly(total_days=3, days=_make_multi_day_itinerary(1, 3).days)
    full = graph_module._DaysOnly(total_days=3, days=_make_multi_day_itinerary(3, 3).days)
    state = _make_state([AIMessage(content="Extend the trip.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.ITINERARY

    with patch("trip_planner.agents.graph._llm_days_only") as mock_days:
        mock_days.ainvoke = AsyncMock(side_effect=[short, full])
        result = await format_node(state)

    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert len(itinerary.days) == 3
    assert mock_days.ainvoke.await_count == 2


async def test_format_node_itinerary_scope_falls_back_to_previous_when_empty() -> None:
    previous = _make_itinerary()
    state = _make_state([AIMessage(content="Change the plan.")])
    state["previous_itinerary"] = previous
    state["update_scope"] = UpdateScope.ITINERARY

    with patch("trip_planner.agents.graph._llm_days_only") as mock_days:
        mock_days.ainvoke = AsyncMock(return_value=graph_module._DaysOnly(total_days=0, days=[]))
        result = await format_node(state)

    itinerary = result.get("current_itinerary")
    assert itinerary is not None
    assert itinerary.days == previous.days


# --- _route_after_triage ---


def test_route_after_triage_returns_end_when_clarification_is_set() -> None:
    clarification = ClarificationRequest(
        message="Could you tell me where and how long?",
        missing_fields=["destination", "duration"],
    )
    state = TripPlannerState(
        messages=[],
        trip_request="plan me a trip",
        pending_clarification=clarification,
    )

    result = _route_after_triage(state)

    assert result == "__end__"


def test_route_after_triage_returns_reason_when_no_clarification() -> None:
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days")],
        trip_request="Paris 7 days",
    )

    result = _route_after_triage(state)

    assert result == "reason"


# --- triage_node ---


async def test_triage_node_sets_clarification_when_llm_decides_to_clarify() -> None:
    clarification = ClarificationRequest(
        message="Could you tell me where and how long?",
        missing_fields=["destination", "duration"],
    )

    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.NEW_TRIP, should_clarify=True, clarification=clarification
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="plan me a trip")],
        trip_request="plan me a trip",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("pending_clarification") == clarification
    assert result["trip_request"] == "plan me a trip"


async def test_triage_node_sets_clarification_to_none_when_request_is_complete() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.NEW_TRIP, should_clarify=False, clarification=None
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days in July, I like history")],
        trip_request="Paris 7 days in July, I like history",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("pending_clarification") is None
    assert result["trip_request"] == "Paris 7 days in July, I like history"


async def test_triage_node_resets_transient_state_for_resumed_threads() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.NEW_TRIP, should_clarify=False, clarification=None
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days in July")],
        trip_request="Paris 7 days in July",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("current_itinerary") is None
    assert result.get("tool_results") == []
    assert result.get("tool_call_count") == 0


async def test_triage_node_never_reclarifies_when_itinerary_already_exists() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    clarification = ClarificationRequest(
        message="Where would you like to go?",
        missing_fields=["destination"],
    )
    # The model still asks to clarify, but an itinerary already exists on the resumed thread.
    decision = _TriageDecision(
        intent=_TriageIntent.NEW_TRIP, should_clarify=True, clarification=clarification
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="actually plan me something else")],
        trip_request="actually plan me something else",
        current_itinerary=_make_itinerary(),
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("pending_clarification") is None


async def test_triage_node_lets_modifications_proceed_without_clarifying() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.ITINERARY_MODIFICATION, should_clarify=False, clarification=None
    )
    state = TripPlannerState(
        messages=[
            HumanMessage(content="Paris 7 days"),
            AIMessage(content="Here is your Paris itinerary..."),
            HumanMessage(content="swap day 2 for a food tour"),
        ],
        trip_request="swap day 2 for a food tour",
        current_itinerary=_make_itinerary(),
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("pending_clarification") is None
    assert _route_after_triage(result) == "reason"


async def test_triage_node_carries_scope_and_previous_itinerary_for_modifications() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    previous = _make_itinerary()
    decision = _TriageDecision(
        intent=_TriageIntent.ITINERARY_MODIFICATION,
        should_clarify=False,
        clarification=None,
        update_scope=UpdateScope.HOTELS,
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="find me cheaper hotels")],
        trip_request="find me cheaper hotels",
        current_itinerary=previous,
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("update_scope") is UpdateScope.HOTELS
    assert result.get("previous_itinerary") is previous
    assert result.get("current_itinerary") is None


async def test_triage_node_forces_full_scope_for_new_trips() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.NEW_TRIP,
        should_clarify=False,
        clarification=None,
        update_scope=UpdateScope.HOTELS,
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days")],
        trip_request="Paris 7 days",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("update_scope") is UpdateScope.FULL
    assert result.get("previous_itinerary") is None


async def test_triage_node_ignores_scope_without_existing_itinerary() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    # The model may mislabel a first turn as a modification; without an itinerary, force full.
    decision = _TriageDecision(
        intent=_TriageIntent.ITINERARY_MODIFICATION,
        should_clarify=False,
        clarification=None,
        update_scope=UpdateScope.FLIGHTS,
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days")],
        trip_request="Paris 7 days",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("update_scope") is UpdateScope.FULL


async def test_triage_node_carries_hotel_constraints_into_state() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.ITINERARY_MODIFICATION,
        should_clarify=False,
        clarification=None,
        update_scope=UpdateScope.HOTELS,
        hotel_max_nightly_price=150.0,
        hotel_min_star_rating=3.0,
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="cheaper 3-star hotels")],
        trip_request="cheaper 3-star hotels",
        current_itinerary=_make_itinerary(),
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("hotel_max_nightly_price") == 150.0
    assert result.get("hotel_min_star_rating") == 3.0


async def test_triage_node_resets_hotel_constraints_when_not_mentioned() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.ITINERARY_MODIFICATION, should_clarify=False, clarification=None
    )
    state = TripPlannerState(
        messages=[HumanMessage(content="add a day trip to Versailles")],
        trip_request="add a day trip to Versailles",
        current_itinerary=_make_itinerary(),
        hotel_max_nightly_price=150.0,
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("hotel_max_nightly_price") is None


async def test_triage_node_lets_clarification_answers_proceed_without_reclarifying() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    # The thread previously asked for missing details; the user is now answering, so proceed.
    decision = _TriageDecision(
        intent=_TriageIntent.CLARIFICATION_ANSWER, should_clarify=False, clarification=None
    )
    state = TripPlannerState(
        messages=[
            HumanMessage(content="plan me a trip"),
            AIMessage(content="Where would you like to go and for how long?"),
            HumanMessage(content="Paris, 7 days in July"),
        ],
        trip_request="Paris, 7 days in July",
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        result = await triage_node(state)

    assert result.get("pending_clarification") is None
    assert _route_after_triage(result) == "reason"


async def test_triage_node_feeds_conversation_history_to_the_llm() -> None:
    from trip_planner.agents.graph import _TriageDecision, _TriageIntent

    decision = _TriageDecision(
        intent=_TriageIntent.TRIP_QUESTION, should_clarify=False, clarification=None
    )
    history = [
        HumanMessage(content="Paris 7 days"),
        AIMessage(content="Here is your Paris itinerary..."),
        HumanMessage(content="what's the weather like there?"),
    ]
    state = TripPlannerState(
        messages=history,  # type: ignore[arg-type]
        trip_request="what's the weather like there?",
        current_itinerary=_make_itinerary(),
    )

    with patch("trip_planner.agents.graph._llm_triage") as mock_triage:
        mock_triage.ainvoke = AsyncMock(return_value=decision)
        await triage_node(state)

    await_args = mock_triage.ainvoke.await_args
    assert await_args is not None
    passed_messages = await_args.args[0]
    # System triage prompt is prepended, followed by the full conversation history.
    assert passed_messages[1:] == history


# --- run_planner graph selection ---


async def test_plan_turn_returns_only_the_user_visible_outcome() -> None:
    itinerary = _make_itinerary()
    # run_planner hands back full execution state; plan_turn must expose only clarification/itinerary.
    planner_state = TripPlannerState(
        messages=[HumanMessage(content="Paris 7 days"), AIMessage(content="Here is your plan.")],
        trip_request="Paris 7 days",
        current_itinerary=itinerary,
        tool_call_count=3,
        tool_results=[],
    )

    with patch("trip_planner.agents.graph.run_planner", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = planner_state
        outcome = await plan_turn("Paris 7 days", thread_id="abc-123")

    assert isinstance(outcome, PlannerOutcome)
    assert outcome.itinerary == itinerary
    assert outcome.clarification is None

    called_state = mock_run.call_args[0][0]
    assert called_state["trip_request"] == "Paris 7 days"
    assert called_state["messages"][0].content == "Paris 7 days"
    assert mock_run.call_args[1]["thread_id"] == "abc-123"


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


async def test_run_planner_applies_recursion_limit() -> None:
    from trip_planner.agents.graph import _RECURSION_LIMIT

    state = _make_state([HumanMessage(content="Paris 7 days")])
    compiled = MagicMock()
    compiled.ainvoke = AsyncMock(return_value=state)

    with patch("trip_planner.agents.graph._compiled_graph", compiled):
        await run_planner(state, thread_id="abc-123")

    config = compiled.ainvoke.call_args.args[1]
    assert config["recursion_limit"] == _RECURSION_LIMIT


async def test_run_planner_raises_timeout_when_run_exceeds_limit() -> None:
    state = _make_state([HumanMessage(content="Paris 7 days")])
    compiled = MagicMock()

    async def _never_finish(*_args: object, **_kwargs: object) -> TripPlannerState:
        await asyncio.Event().wait()
        return state

    compiled.ainvoke = _never_finish

    with (
        patch("trip_planner.agents.graph._compiled_graph", compiled),
        patch("trip_planner.agents.graph._RUN_TIMEOUT_SECONDS", 0.01),
        pytest.raises(TimeoutError, match="time limit"),
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


def test_format_llm_uses_dedicated_itinerary_model() -> None:
    assert graph_module._format_llm.model_name == graph_module._settings.itinerary_model
    assert graph_module._reasoning_llm.model_name == graph_module._settings.openai_model


def test_reasoning_llm_is_creative() -> None:
    assert graph_module._reasoning_llm.temperature == 0.7


def test_per_node_llms_are_distinct_instances() -> None:
    llms = {id(graph_module._triage_llm), id(graph_module._format_llm), id(graph_module._reasoning_llm)}
    assert len(llms) == 3
