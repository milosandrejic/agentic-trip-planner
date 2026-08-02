import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from trip_planner.models.trip import TripStatus
from trip_planner.schemas.threads import PlannerResult


class TripSummary(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    destination: str | None
    status: TripStatus
    created_at: datetime
    updated_at: datetime


class CreateTripRequest(BaseModel):
    query: str = Field(min_length=10, max_length=1000)


class CreateTripResponse(BaseModel):
    trip: TripSummary
    thread_id: uuid.UUID
    result: PlannerResult
