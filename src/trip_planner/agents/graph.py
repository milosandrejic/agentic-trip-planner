# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false
import uuid
from typing import Literal, cast

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from pydantic import SecretStr

from trip_planner.agents.state import TripPlannerState
from trip_planner.config import get_settings
from trip_planner.schemas.trips import Itinerary
from trip_planner.tools.web_search import web_search_tool
from trip_planner.tools.weather import weather_tool

_TOOLS = [web_search_tool, weather_tool]

_SYSTEM_PROMPT = (
    "You are an expert trip planner. "
    "Create detailed, practical travel itineraries based on the user's request. "
    "Use the web_search tool to find current information about destinations, attractions, and local events. "
    "Use the weather tool to get forecasts when the user provides travel dates. "
    "Always cite your sources by including the URL and title of pages you reference. "
    "Ask clarifying questions if the request is too vague to plan well."
)

_FORMAT_PROMPT = (
    "Based on the trip planning conversation above, produce a complete structured itinerary. "
    "Include all days, activities, weather information, and sources discussed."
)

_settings = get_settings()

_llm = ChatOpenAI(
    model=_settings.openai_model,
    api_key=SecretStr(_settings.openai_api_key),
    temperature=0.7,
)

_llm_with_tools = _llm.bind_tools(_TOOLS)
_llm_structured = _llm.with_structured_output(Itinerary)


def _route_after_reason(state: TripPlannerState) -> Literal["tools", "format"]:
    """Route to tools if the last message has pending tool calls, else to format."""
    last_message = state["messages"][-1]
    is_ai_message = isinstance(last_message, AIMessage)

    has_pending_tool_calls = is_ai_message and bool(last_message.tool_calls)

    return "tools" if has_pending_tool_calls else "format"


async def reason_node(state: TripPlannerState) -> TripPlannerState:
    """Reason about the current state: call tools or produce a final answer."""
    system_message = SystemMessage(content=_SYSTEM_PROMPT)
    messages_with_system = [system_message] + list(state["messages"])

    response = await _llm_with_tools.ainvoke(messages_with_system)

    return TripPlannerState(
        messages=[response],
        trip_request=state["trip_request"],
        draft_itinerary=state["draft_itinerary"],
    )


async def format_node(state: TripPlannerState) -> TripPlannerState:
    """Force the conversation into a structured Itinerary via with_structured_output."""
    format_instruction = SystemMessage(content=_FORMAT_PROMPT)
    messages_with_instruction = list(state["messages"]) + [format_instruction]

    itinerary = cast(Itinerary, await _llm_structured.ainvoke(messages_with_instruction))

    return TripPlannerState(
        messages=[],
        trip_request=state["trip_request"],
        draft_itinerary=state["draft_itinerary"],
        itinerary=itinerary,
    )


_compiled_graph: CompiledStateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState] | None = None


def init_graph(checkpointer: AsyncPostgresSaver) -> None:
    """Compile the graph with the given checkpointer and store it module-wide."""
    global _compiled_graph
    _compiled_graph = build_graph(checkpointer=checkpointer)


def build_graph(
    checkpointer: AsyncPostgresSaver | None = None,
) -> CompiledStateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState]:
    """Build and compile the ReAct trip planner graph."""
    graph: StateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState] = StateGraph(TripPlannerState)

    graph.add_node("reason", reason_node)
    graph.add_node("tools", ToolNode(_TOOLS))
    graph.add_node("format", format_node)

    graph.set_entry_point("reason")
    graph.add_conditional_edges("reason", _route_after_reason)
    graph.add_edge("tools", "reason")
    graph.add_edge("format", END)

    return graph.compile(checkpointer=checkpointer)


async def run_planner(state: TripPlannerState, thread_id: str | None = None) -> TripPlannerState:
    """Invoke the compiled graph with an optional thread_id for checkpointed state."""
    compiled = _compiled_graph

    if compiled is None:
        raise RuntimeError("Graph has not been initialized — call init_graph() at startup.")

    resolved_thread_id = thread_id or str(uuid.uuid4())
    config = RunnableConfig(configurable={"thread_id": resolved_thread_id})
    result = await compiled.ainvoke(state, config)
    return cast(TripPlannerState, result)

