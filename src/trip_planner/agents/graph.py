# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from typing import cast

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from trip_planner.agents.state import TripPlannerState
from trip_planner.config import get_settings

_settings = get_settings()

_SYSTEM_PROMPT = (
    "You are an expert trip planner. "
    "Create detailed, practical travel itineraries based on the user's request. "
    "Ask clarifying questions if the request is too vague to plan well."
)

_llm = ChatOpenAI(
    model=_settings.openai_model,
    api_key=SecretStr(_settings.openai_api_key),
    temperature=0.7,
)


async def chat_node(state: TripPlannerState) -> TripPlannerState:
    """Call the LLM with the current message history and return the updated state."""
    system_message = SystemMessage(content=_SYSTEM_PROMPT)
    messages_with_system = [system_message] + list(state["messages"])

    response = await _llm.ainvoke(messages_with_system)

    content = response.content
    draft_itinerary = content if isinstance(content, str) else str(content)

    return TripPlannerState(
        messages=[response],
        trip_request=state["trip_request"],
        draft_itinerary=draft_itinerary,
    )


def build_graph() -> CompiledStateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState]:
    """Build and compile the trip planner graph."""
    graph: StateGraph[TripPlannerState, None, TripPlannerState, TripPlannerState] = StateGraph(TripPlannerState)

    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)

    return graph.compile()


graph = build_graph()


async def run_planner(initial_state: TripPlannerState) -> TripPlannerState:
    """Invoke the compiled graph and return the final state."""
    result = await graph.ainvoke(initial_state)
    return cast(TripPlannerState, result)
