# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from enum import Enum
from typing import Annotated, NotRequired

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from typing_extensions import TypedDict

from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Itinerary
from trip_planner.services.types import ToolResult


class UpdateScope(str, Enum):
    """Which section of an existing itinerary a follow-up turn is allowed to change."""

    FULL = "full"
    FLIGHTS = "flights"
    HOTELS = "hotels"
    ITINERARY = "itinerary"


class TripPlannerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    trip_request: str
    tool_call_count: NotRequired[int]
    tool_results: NotRequired[list[ToolResult[BaseModel]]]
    current_itinerary: NotRequired[Itinerary | None]
    previous_itinerary: NotRequired[Itinerary | None]
    update_scope: NotRequired[UpdateScope]
    hotel_max_nightly_price: NotRequired[float | None]
    hotel_min_star_rating: NotRequired[float | None]
    pending_clarification: NotRequired[ClarificationRequest | None]
