from pydantic import BaseModel, Field


class TripPlanRequest(BaseModel):
    query: str = Field(min_length=10, max_length=1000)


class TripPlanResponse(BaseModel):
    itinerary: str
