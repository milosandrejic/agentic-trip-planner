# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class TripPlannerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    trip_request: str
    draft_itinerary: str
