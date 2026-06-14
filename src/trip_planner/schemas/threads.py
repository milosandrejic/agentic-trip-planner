import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from trip_planner.schemas.clarification import ClarificationRequest
from trip_planner.schemas.trips import Itinerary


class CreateThreadRequest(BaseModel):
    query: str = Field(min_length=10, max_length=1000)


class SendMessageRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class ThreadSummary(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    itinerary: Itinerary | None
    created_at: datetime


class ItineraryResult(BaseModel):
    type: Literal["itinerary"] = "itinerary"
    itinerary: Itinerary


class ClarificationResult(BaseModel):
    type: Literal["clarification"] = "clarification"
    clarification: ClarificationRequest


PlannerResult = Annotated[ItineraryResult | ClarificationResult, Field(discriminator="type")]


class CreateThreadResponse(BaseModel):
    thread: ThreadSummary
    result: PlannerResult


class SendMessageResponse(BaseModel):
    result: PlannerResult


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary]


class ThreadDetailResponse(BaseModel):
    thread: ThreadSummary
    messages: list[MessageOut]
