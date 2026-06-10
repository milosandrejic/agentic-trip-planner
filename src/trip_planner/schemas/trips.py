from pydantic import BaseModel, Field


class TripPlanRequest(BaseModel):
    query: str = Field(min_length=10, max_length=1000)


class Source(BaseModel):
    title: str
    url: str


class Activity(BaseModel):
    time: str = Field(description="Time of day, e.g. 'Morning', '09:00'")
    description: str
    duration_hours: float | None = None
    sources: list[Source] = Field(default_factory=lambda: [])


class DayPlan(BaseModel):
    day: int = Field(description="Day number, starting from 1")
    date: str | None = Field(default=None, description="ISO date, e.g. '2024-07-01'")
    location: str
    weather_summary: str | None = None
    activities: list[Activity]


class Itinerary(BaseModel):
    destination: str
    total_days: int
    summary: str
    days: list[DayPlan]
    sources: list[Source] = Field(default_factory=lambda: [])


class TripPlanResponse(BaseModel):
    itinerary: Itinerary
