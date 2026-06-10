# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from typing import Annotated, NotRequired

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from trip_planner.schemas.trips import Itinerary


class TripPlannerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    trip_request: str
    draft_itinerary: str
    itinerary: NotRequired[Itinerary | None]
