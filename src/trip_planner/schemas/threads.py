import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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


class CreateThreadResponse(BaseModel):
    thread: ThreadSummary
    itinerary: Itinerary


class SendMessageResponse(BaseModel):
    itinerary: Itinerary


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary]


class ThreadDetailResponse(BaseModel):
    thread: ThreadSummary
    messages: list[MessageOut]
