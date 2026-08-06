# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false
import asyncio
import uuid
from datetime import date
from enum import Enum
from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field, SecretStr

from trip_planner.agents.state import TripPlannerState, UpdateScope
from trip_planner.config import get_settings
from trip_planner.logging_config import get_logger
from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import DayPlan, FlightOption, HotelOption, Itinerary
from trip_planner.services.types import ToolResult
from trip_planner.tools.discover_places import discover_places_tool
from trip_planner.tools.find_place_by_name import find_place_by_name_tool
from trip_planner.tools.flight_search import flight_search_tool
from trip_planner.tools.hotel_search import hotel_search_tool
from trip_planner.tools.place_details import place_details_tool
from trip_planner.tools.web_search import web_search_tool
from trip_planner.tools.weather import weather_tool

_logger = get_logger(__name__)

_TOOLS = [
    web_search_tool,
    weather_tool,
    flight_search_tool,
    hotel_search_tool,
    discover_places_tool,
    find_place_by_name_tool,
    place_details_tool,
]

_TRIAGE_PROMPT_TEMPLATE = (
    "Today is {today}. "
    "You are the triage step of a trip-planning assistant. Read the ENTIRE conversation so far, "
    "then classify the user's latest message into exactly one intent:\n"
    "- 'new_trip': a request to plan a brand-new trip.\n"
    "- 'itinerary_modification': a change to an itinerary already being planned (add, remove, or "
    "swap days, activities, budget, or dates).\n"
    "- 'clarification_answer': the user is answering a question you asked in an earlier turn.\n"
    "- 'trip_question': a question about the trip or destination that does not change the plan.\n"
    "{itinerary_state}\n"
    "Only set should_clarify=true for a 'new_trip' that is missing critical information — at minimum "
    "a destination and an approximate duration or travel dates. "
    "Never ask for clarification for itinerary_modification, clarification_answer, or trip_question; "
    "for those, set should_clarify=false and act on what the user said. "
    "Travel dates must be in the future relative to today ({today}); if the user mentions only a "
    "month with no year, infer the nearest future occurrence, and treat past or unresolvable dates "
    "as missing. "
    "When you clarify, provide a friendly, conversational message and list the missing fields by "
    "their machine-readable names (e.g. 'destination', 'travel_dates', 'duration', 'budget', "
    "'traveler_count'). "
    "Otherwise set should_clarify=false and leave clarification as null. "
    "For an itinerary_modification, also set update_scope to the narrowest section the user wants "
    "changed: 'flights' when only flights change, 'hotels' when only hotels change, 'itinerary' when "
    "only the day-by-day plan (days or activities) changes. Use 'full' for a brand-new trip or a "
    "change that touches several sections at once. For every other intent, leave update_scope as 'full'. "
    "Also extract hotel_max_nightly_price and hotel_min_star_rating whenever the user's message implies "
    "a hotel price or quality constraint, whether for a new trip or a modification. Look back through "
    "the conversation's prior hotel search results for concrete prices to ground a relative request "
    "like 'cheaper' or 'budget-friendly' in an actual number; leave both null when hotels are not "
    "mentioned or no constraint is implied."
)

_SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert trip planner. Today is {today}. "
    "Create detailed, practical travel itineraries based on the user's request. "
    "All travel dates must be on or after {today} — never use past dates for weather forecasts or flight searches. "
    "If a user mentions only a month, use the nearest future occurrence of that month. "
    "Use the web_search tool to find current information about destinations, attractions, and local events. "
    "Use the weather tool to get forecasts when the user provides travel dates. "
    "Use the flight_search tool to find available flights when the user provides an origin city and travel dates. "
    "Always convert city names to IATA airport codes before calling flight_search (e.g. London → LHR, Paris → CDG). "
    "Use the hotel_search tool to find accommodation when the user provides a destination and travel dates. "
    "Pass the destination city name and its ISO 3166-1 alpha-2 country code (e.g. Paris → FR, Tokyo → JP). "
    "Use the discover_places tool to discover points of interest (attractions, restaurants, museums) in the "
    "destination via Geoapify category keys (e.g. 'tourism.sights', 'catering.restaurant', 'entertainment.museum'). "
    "Use the find_place_by_name tool to resolve a specific named place to its Google place_id. "
    "Use the place_details tool with that place_id to fetch rich details (rating, opening hours, price level, "
    "website) for your top picks only, since each detail lookup is a paid call. "
    "Always cite your sources by including the URL and title of pages you reference. "
    "Ask clarifying questions if the request is too vague to plan well."
)

_FORMAT_PROMPT = (
    "Based on the trip planning conversation above, produce a complete structured itinerary. "
    "You MUST include every single day — if the user asked for 3 days, the itinerary must have exactly 3 DayPlan entries. "
    "For each day include at least 3 activities. "
    "Include weather summaries where the weather tool provided data. "
    "Populate the flights field with every flight option returned by the flight_search tool. "
    "Populate the hotels field with every hotel option returned by the hotel_search tool. "
    "For each activity, populate the place fields (place_id, latitude, longitude, address, rating, "
    "opening_hours, price_level, ticket_url) whenever the places tools provided that data. "
    "Include all sources discussed. "
    "Do not truncate or summarise days — output the full itinerary. "
    "The summary field must describe the trip itself (destination highlights, pace, what the days "
    "cover) in 2-4 sentences. Never mention prices, tool or provider names, or search/API details in "
    "the summary — that information belongs only in the flights and hotels fields."
)

# Section-only prompts back the partial-regeneration path: a scoped follow-up (hotels, flights,
# or the day plan) only asks the model to extract the section it touched, instead of the whole
# trip, so unrelated sections are never at risk of silently changing.
_HOTELS_FORMAT_PROMPT = (
    "Based on the trip planning conversation above, extract ONLY the hotel options returned by "
    "the hotel_search tool. Populate the hotels field with every hotel option found; do not invent "
    "hotels the tool did not return."
)

_FLIGHTS_FORMAT_PROMPT = (
    "Based on the trip planning conversation above, extract ONLY the flight options returned by "
    "the flight_search tool. Populate the flights field with every flight option found; do not "
    "invent flights the tool did not return."
)

_DAYS_FORMAT_PROMPT = (
    "Based on the trip planning conversation above, produce ONLY the day-by-day plan. "
    "You MUST include every single day — if the trip is N days, output exactly N DayPlan entries. "
    "For each day include at least 3 activities. Include weather summaries where the weather tool "
    "provided data. For each activity, populate the place fields (place_id, latitude, longitude, "
    "address, rating, opening_hours, price_level, ticket_url) whenever the places tools provided "
    "that data. Do not truncate or summarise days — output the full day-by-day plan."
)

_settings = get_settings()

_REASONING_TEMPERATURE = 0.7
_DETERMINISTIC_TEMPERATURE = 0.0

# Safety limits guard against runaway agent loops and hung provider calls.
# _MAX_TOOL_CALLS caps how many tool invocations a single run may make before the reasoner is
# forced to answer from what it already gathered; it also seeds a per-run cost-tracking counter.
# _RECURSION_LIMIT is LangGraph's superstep backstop, and _RUN_TIMEOUT_SECONDS bounds wall time.
_MAX_TOOL_CALLS = 8
_RECURSION_LIMIT = 25
_RUN_TIMEOUT_SECONDS = 120.0

# The formatter is re-invoked up to this many times when it emits fewer days than requested.
_MAX_FORMAT_ATTEMPTS = 3


def _build_llm(temperature: float, model: str | None = None) -> ChatOpenAI:
    """Create a ChatOpenAI client for the given model at the given temperature.

    Falls back to the default configured model when none is supplied.
    """
    return ChatOpenAI(
        model=model or _settings.openai_model,
        api_key=SecretStr(_settings.openai_api_key),
        temperature=temperature,
    )


# Reasoning stays creative; triage and structured formatting are deterministic (temperature 0)
# so completeness checks and the final itinerary are stable across runs. Itinerary formatting uses
# a dedicated, stronger model that reliably emits every requested day.
_reasoning_llm = _build_llm(_REASONING_TEMPERATURE)
_triage_llm = _build_llm(_DETERMINISTIC_TEMPERATURE)
_format_llm = _build_llm(_DETERMINISTIC_TEMPERATURE, model=_settings.itinerary_model)

_llm_with_tools = _reasoning_llm.bind_tools(_TOOLS)
_llm_structured = _format_llm.with_structured_output(Itinerary)


class _HotelsOnly(BaseModel):
    hotels: list[HotelOption] = Field(
        default_factory=lambda: [], description="Top hotel options found for this trip."
    )


class _FlightsOnly(BaseModel):
    flights: list[FlightOption] = Field(
        default_factory=lambda: [], description="Top flight options found for this trip."
    )


class _DaysOnly(BaseModel):
    total_days: int
    days: list[DayPlan]


# Section-only structured outputs back the partial-regeneration path (see format_node): a scoped
# follow-up only pays for the section it changed instead of the full itinerary.
_llm_hotels_only = _format_llm.with_structured_output(_HotelsOnly)
_llm_flights_only = _format_llm.with_structured_output(_FlightsOnly)
_llm_days_only = _format_llm.with_structured_output(_DaysOnly)


class _TriageIntent(str, Enum):
    NEW_TRIP = "new_trip"
    ITINERARY_MODIFICATION = "itinerary_modification"
    CLARIFICATION_ANSWER = "clarification_answer"
    TRIP_QUESTION = "trip_question"


class _TriageDecision(BaseModel):
    intent: _TriageIntent = Field(
        description="The classified intent of the user's latest message given the conversation."
    )
    should_clarify: bool = Field(
        description="True only for a new_trip missing critical information to plan a trip."
    )
    clarification: ClarificationRequest | None = Field(
        default=None,
        description="Required when should_clarify is True. Must be null otherwise.",
    )
    update_scope: UpdateScope = Field(
        default=UpdateScope.FULL,
        description=(
            "For an itinerary_modification, the narrowest section to change: 'flights', 'hotels', "
            "or 'itinerary' (day-by-day plan). 'full' for a new trip or a broad, multi-section change."
        ),
    )
    hotel_max_nightly_price: float | None = Field(
        default=None,
        description=(
            "Set only when the user requests cheaper, budget, or a specific price ceiling for "
            "hotels. Infer a concrete number from the conversation (e.g. below the cheapest hotel "
            "nightly price already shown) when the user is relative ('cheaper') rather than exact. "
            "Null when the user did not mention hotel price."
        ),
    )
    hotel_min_star_rating: float | None = Field(
        default=None,
        description=(
            "Set only when the user requests a star-rating floor for hotels, e.g. 3 for '3-star or "
            "better', or 3 for '3 or 4-star'. Null when the user did not mention hotel star rating."
        ),
    )


_llm_triage = _triage_llm.with_structured_output(_TriageDecision)


def _route_after_triage(state: TripPlannerState) -> Literal["reason", "__end__"]:
    """Route to reason if the request is complete, or end with a clarification response."""
    has_clarification = state.get("pending_clarification") is not None
    return "__end__" if has_clarification else "reason"


def _route_after_reason(state: TripPlannerState) -> Literal["tools", "format"]:
    """Route to tools if the last message has pending tool calls, else to format."""
    last_message = state["messages"][-1]
    is_ai_message = isinstance(last_message, AIMessage)

    has_pending_tool_calls = is_ai_message and bool(last_message.tool_calls)

    return "tools" if has_pending_tool_calls else "format"


async def triage_node(state: TripPlannerState) -> TripPlannerState:
    """Classify the latest message against the conversation and decide whether to clarify.

    Triage reads the full history so follow-ups (modifications, answers, questions) flow straight
    to reasoning. Once an itinerary exists the user is iterating, so clarification is never asked
    again regardless of the model's suggestion.
    """
    today = date.today().isoformat()
    has_itinerary = state.get("current_itinerary") is not None
    itinerary_state = (
        "An itinerary already exists for this conversation; never ask for clarification — apply the "
        "requested change or answer directly."
        if has_itinerary
        else "No itinerary exists yet for this conversation."
    )
    triage_message = SystemMessage(
        content=_TRIAGE_PROMPT_TEMPLATE.format(today=today, itinerary_state=itinerary_state)
    )
    conversation = list(state["messages"])

    decision = cast(_TriageDecision, await _llm_triage.ainvoke([triage_message] + conversation))

    should_clarify = decision.should_clarify and not has_itinerary
    clarification = decision.clarification if should_clarify else None

    # A scoped follow-up only applies when modifying an existing itinerary; otherwise regenerate fully.
    is_modification = decision.intent is _TriageIntent.ITINERARY_MODIFICATION
    update_scope = decision.update_scope if has_itinerary and is_modification else UpdateScope.FULL

    _logger.info(
        "followup.triage",
        intent=decision.intent.value,
        has_itinerary=has_itinerary,
        should_clarify=should_clarify,
        update_scope=update_scope.value,
        hotel_max_nightly_price=decision.hotel_max_nightly_price,
        hotel_min_star_rating=decision.hotel_min_star_rating,
    )

    # Reset transient outputs so a resumed thread never reads a previous turn's itinerary
    # or tool results (this graph is checkpointed and re-entered on follow-up messages). The
    # previous itinerary is carried forward so the formatter can splice a scoped change into it.
    return TripPlannerState(
        messages=[],
        trip_request=state["trip_request"],
        tool_call_count=0,
        tool_results=[],
        current_itinerary=None,
        previous_itinerary=state.get("current_itinerary"),
        update_scope=update_scope,
        hotel_max_nightly_price=decision.hotel_max_nightly_price,
        hotel_min_star_rating=decision.hotel_min_star_rating,
        pending_clarification=clarification,
    )


def _hotel_constraint_reminder(max_nightly_price: float | None, min_star_rating: float | None) -> SystemMessage:
    """Force hotel_search_tool to receive the constraints extracted from the user's request.

    Triage extracts price/rating constraints deterministically; without this explicit
    instruction the reasoning LLM tends to repeat the previous, unconstrained tool call.
    """
    constraints: list[str] = []
    if max_nightly_price is not None:
        constraints.append(f"max_nightly_price={max_nightly_price}")
    if min_star_rating is not None:
        constraints.append(f"min_star_rating={min_star_rating}")

    return SystemMessage(
        content=(
            "When calling hotel_search_tool this turn, you MUST set "
            f"{' and '.join(constraints)} exactly as given, so the search reflects the user's "
            "latest request instead of repeating the previous, unconstrained search."
        )
    )


def _trailing_tool_messages(messages: list[BaseMessage]) -> list[ToolMessage]:
    """Collect the run of ToolMessages most recently appended, in original order.

    The tools node appends one ToolMessage per requested call directly after the AIMessage that
    requested them, so this is exactly the batch reason_node is about to reason over again.
    """
    trailing: list[ToolMessage] = []
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break
        trailing.append(message)
    trailing.reverse()
    return trailing


async def reason_node(state: TripPlannerState) -> TripPlannerState:
    """Reason about the current state: call tools or produce a final answer.

    Once the run has spent its tool-call budget the reasoner is invoked without tools bound,
    forcing it to answer from the evidence already gathered instead of looping indefinitely.
    """
    for tool_message in _trailing_tool_messages(state["messages"]):
        artifact = tool_message.artifact
        status = artifact.status.value if isinstance(artifact, ToolResult) else None
        _logger.debug(
            "followup.tool_result",
            tool=tool_message.name,
            status=status,
            content_preview=str(tool_message.content)[:200],
        )

    today = date.today().isoformat()
    system_message = SystemMessage(content=_SYSTEM_PROMPT_TEMPLATE.format(today=today))
    messages_with_system = [system_message] + list(state["messages"])

    max_nightly_price = state.get("hotel_max_nightly_price")
    min_star_rating = state.get("hotel_min_star_rating")
    if max_nightly_price is not None or min_star_rating is not None:
        messages_with_system.append(
            _hotel_constraint_reminder(max_nightly_price, min_star_rating)
        )

    calls_so_far = state.get("tool_call_count", 0)
    budget_exhausted = calls_so_far >= _MAX_TOOL_CALLS
    reasoner = _reasoning_llm if budget_exhausted else _llm_with_tools

    _logger.debug(
        "followup.reason_context",
        message_count=len(messages_with_system),
        budget_exhausted=budget_exhausted,
        final_message_preview=str(messages_with_system[-1].content)[:200],
    )

    response = await reasoner.ainvoke(messages_with_system)

    new_tool_calls = len(response.tool_calls)

    if new_tool_calls:
        selected_tools = [
            {"name": call["name"], "args": call["args"]} for call in response.tool_calls
        ]
        _logger.info("followup.tools_selected", tools=selected_tools)
    else:
        _logger.info("followup.final_answer", calls_so_far=calls_so_far)

    return TripPlannerState(
        messages=[response],
        trip_request=state["trip_request"],
        tool_call_count=calls_so_far + new_tool_calls,
    )

def _as_structured_tool_message(message: ToolMessage) -> ToolMessage:
    """Replace a tool message's human-readable text with its structured ToolResult payload.

    The formatter reads authoritative typed data (provider IDs, prices, coordinates) straight
    from the tool's artifact instead of reparsing the summary text the tool produced for the
    reasoning LLM. The artifact is preserved so downstream consumers keep the typed object.
    """
    result = message.artifact
    return ToolMessage(
        content=result.model_dump_json(),
        tool_call_id=message.tool_call_id,
        name=message.name,
        artifact=result,
    )


def _with_structured_tool_results(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Swap each artifact-bearing tool message for its structured ToolResult representation.

    Tool messages without a ToolResult artifact (e.g. web search) keep their original text.
    """
    structured: list[BaseMessage] = []
    for message in messages:
        is_structured_tool = isinstance(message, ToolMessage) and isinstance(
            message.artifact, ToolResult
        )
        if is_structured_tool:
            structured.append(_as_structured_tool_message(cast(ToolMessage, message)))
        else:
            structured.append(message)
    return structured


def _collect_tool_results(messages: list[BaseMessage]) -> list[ToolResult[BaseModel]]:
    """Gather the structured ToolResult artifacts attached to the conversation's tool messages.

    Exposing the typed provider payloads on the state (rather than only as message artifacts)
    gives the API layer and future cost tracking a first-class handle on what the tools returned.
    """
    results: list[ToolResult[BaseModel]] = []
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.artifact, ToolResult):
            results.append(cast("ToolResult[BaseModel]", message.artifact))
    return results


def _dedupe_flights(flights: list[FlightOption]) -> list[FlightOption]:
    """Drop identical flight offers, keeping the first occurrence in order.

    Providers and the LLM occasionally emit the same offer twice; the frontend must never receive
    duplicates. Two offers are identical when airline, dates, duration, and price all match.
    """
    seen: set[tuple[str, str, str | None, int | None, float | None, str | None]] = set()
    unique: list[FlightOption] = []

    for flight in flights:
        key = (
            flight.airline,
            flight.outbound_date,
            flight.return_date,
            flight.duration_min,
            flight.price,
            flight.currency,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(flight)

    return unique


def _completeness_reminder(total_days: int, produced: int) -> SystemMessage:
    """Build a reminder telling the model to regenerate every missing day."""
    content = (
        f"The itinerary must contain exactly {total_days} DayPlan entries, but the previous "
        f"attempt produced only {produced}. Regenerate the COMPLETE itinerary now with all "
        f"{total_days} days (day 1 through day {total_days}), each with at least 3 activities. "
        "Do not stop early, truncate, or summarise."
    )

    return SystemMessage(content=content)


async def _format_complete_itinerary(messages: list[BaseMessage]) -> Itinerary:
    """Generate the itinerary, retrying with a reminder until every requested day is present.

    gpt-4o-mini sometimes emits only the first day of a multi-day trip; when the DayPlan count
    falls short of total_days we regenerate with an explicit reminder and keep the fullest result,
    bounded by _MAX_FORMAT_ATTEMPTS to cap latency and cost.
    """
    itinerary = cast(Itinerary, await _llm_structured.ainvoke(messages))

    for _ in range(_MAX_FORMAT_ATTEMPTS - 1):
        if len(itinerary.days) >= itinerary.total_days:
            break
        reminder = _completeness_reminder(itinerary.total_days, len(itinerary.days))
        candidate = cast(Itinerary, await _llm_structured.ainvoke([*messages, reminder]))
        if len(candidate.days) > len(itinerary.days):
            itinerary = candidate

    return itinerary


async def _format_complete_days(messages: list[BaseMessage]) -> _DaysOnly:
    """Generate the day-by-day plan, retrying with a reminder until every requested day is present.

    Mirrors _format_complete_itinerary's completeness retry, but for the days-only section used
    by a scoped itinerary follow-up.
    """
    result = cast(_DaysOnly, await _llm_days_only.ainvoke(messages))

    for _ in range(_MAX_FORMAT_ATTEMPTS - 1):
        if len(result.days) >= result.total_days:
            break
        reminder = _completeness_reminder(result.total_days, len(result.days))
        candidate = cast(_DaysOnly, await _llm_days_only.ainvoke([*messages, reminder]))
        if len(candidate.days) > len(result.days):
            result = candidate

    return result


async def _format_scoped_section(
    messages: list[BaseMessage], previous: Itinerary, scope: UpdateScope
) -> Itinerary:
    """Generate and splice only the section a scoped follow-up targeted.

    Only the affected section is sent to the LLM, instead of the whole itinerary, cutting tokens
    and guaranteeing the untouched sections are byte-identical to the previous turn.
    """
    if scope is UpdateScope.HOTELS:
        hotels_only = cast(
            _HotelsOnly, await _llm_hotels_only.ainvoke([*messages, SystemMessage(content=_HOTELS_FORMAT_PROMPT)])
        )
        return previous.model_copy(update={"hotels": hotels_only.hotels or previous.hotels})

    if scope is UpdateScope.FLIGHTS:
        flights_only = cast(
            _FlightsOnly,
            await _llm_flights_only.ainvoke([*messages, SystemMessage(content=_FLIGHTS_FORMAT_PROMPT)]),
        )
        flights = _dedupe_flights(flights_only.flights) if flights_only.flights else previous.flights
        return previous.model_copy(update={"flights": flights})

    # UpdateScope.ITINERARY: regenerate only the day-by-day plan, keeping flights and hotels as-is.
    days_only = await _format_complete_days([*messages, SystemMessage(content=_DAYS_FORMAT_PROMPT)])
    if not days_only.days:
        return previous
    return previous.model_copy(update={"days": days_only.days, "total_days": days_only.total_days})


async def format_node(state: TripPlannerState) -> TripPlannerState:
    """Produce this turn's itinerary.

    A brand-new trip (or a change touching several sections) formats the whole itinerary. A
    scoped follow-up on an existing itinerary instead formats and splices only the section the
    user asked to change (see _format_scoped_section), leaving the rest exactly as it was.
    """
    conversation = list(state["messages"])
    structured_messages = _with_structured_tool_results(conversation)

    scope = state.get("update_scope", UpdateScope.FULL)
    previous = state.get("previous_itinerary")

    if previous is not None and scope is not UpdateScope.FULL:
        _logger.info("followup.format", scope=scope.value, mode="section_only")
        itinerary = await _format_scoped_section(structured_messages, previous, scope)
    else:
        _logger.info("followup.format", scope=scope.value, mode="full")
        messages_with_instruction = structured_messages + [SystemMessage(content=_FORMAT_PROMPT)]
        itinerary = await _format_complete_itinerary(messages_with_instruction)
        itinerary = itinerary.model_copy(update={"flights": _dedupe_flights(itinerary.flights)})

    return TripPlannerState(
        messages=[],
        trip_request=state["trip_request"],
        tool_results=_collect_tool_results(conversation),
        current_itinerary=itinerary,
    )


_compiled_graph: CompiledStateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState] | None = None


def init_graph(checkpointer: AsyncPostgresSaver) -> None:
    """Compile the stateful graph with the given checkpointer and store it module-wide."""
    global _compiled_graph
    _compiled_graph = build_graph(checkpointer=checkpointer)


def build_graph(
    checkpointer: AsyncPostgresSaver | None = None,
) -> CompiledStateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState]:
    """Build and compile the ReAct trip planner graph."""
    graph: StateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState] = StateGraph(TripPlannerState)

    graph.add_node("triage", triage_node)
    graph.add_node("reason", reason_node)
    graph.add_node("tools", ToolNode(_TOOLS))
    graph.add_node("format", format_node)

    graph.set_entry_point("triage")
    graph.add_conditional_edges("triage", _route_after_triage)
    graph.add_conditional_edges("reason", _route_after_reason)
    graph.add_edge("tools", "reason")
    graph.add_edge("format", END)

    return graph.compile(checkpointer=checkpointer)


async def run_planner(state: TripPlannerState, thread_id: str | None = None) -> TripPlannerState:
    """Invoke the stateful trip planner graph.

    Every run is checkpointed. `thread_id` resumes an existing conversation; when omitted a
    fresh id is generated for a new one. The run is bounded by a recursion limit and an overall
    wall-clock timeout so a stuck agent or hung provider call cannot block a request forever.
    """
    compiled = _compiled_graph

    if compiled is None:
        raise RuntimeError("Graph has not been initialized — call init_graph() at startup.")

    resolved_thread_id = thread_id or str(uuid.uuid4())
    config = RunnableConfig(
        configurable={"thread_id": resolved_thread_id},
        recursion_limit=_RECURSION_LIMIT,
    )

    try:
        result = await asyncio.wait_for(
            compiled.ainvoke(state, config),
            timeout=_RUN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"Trip planner run exceeded the {_RUN_TIMEOUT_SECONDS:.0f}s time limit."
        ) from exc

    return cast(TripPlannerState, result)


class PlannerOutcome(BaseModel):
    """The user-visible result of a planning turn — the only agent output the app may consume.

    Execution state (the accumulated message history, tool results, and tool-call budget) is
    owned by the LangGraph checkpoint and is deliberately excluded here so it can never leak
    into the application database. See docs/ARCHITECTURE.md ("Memory ownership").
    """
    clarification: ClarificationRequest | None = None
    itinerary: Itinerary | None = None


async def plan_turn(query: str, thread_id: str | None = None) -> PlannerOutcome:
    """Run one planning turn and return only the user-visible outcome.

    This is the sole boundary between the agent and the application. Callers pass the user's
    message and the owning thread id; the agent's execution state lives entirely in the
    checkpoint keyed by that thread id and is never exposed to the caller. A new turn only ever
    contributes the latest human message — prior context is restored from the checkpoint.
    """
    state = TripPlannerState(
        messages=[HumanMessage(content=query)],
        trip_request=query,
    )
    result = await run_planner(state, thread_id=thread_id)

    return PlannerOutcome(
        clarification=result.get("pending_clarification"),
        itinerary=result.get("current_itinerary"),
    )


