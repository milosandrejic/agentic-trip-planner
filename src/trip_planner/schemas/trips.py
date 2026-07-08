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


class FlightOption(BaseModel):
    airline: str = Field(description="Airline name, e.g. 'British Airways'.")
    stops: int = Field(description="Number of stops (0 = direct).")
    duration_min: int | None = Field(default=None, description="Total flight duration in minutes.")
    price: str = Field(description="Total ticket price as a string, e.g. '250.00'.")
    currency: str = Field(description="ISO currency code, e.g. 'GBP'.")
    outbound_date: str = Field(description="Outbound departure date in ISO format.")
    return_date: str | None = Field(default=None, description="Return departure date for round trips.")
    booking_url: str | None = Field(default=None, description="Direct booking URL if available.")


class Itinerary(BaseModel):
    destination: str
    total_days: int
    summary: str
    days: list[DayPlan]
    flights: list[FlightOption] = Field(
        default_factory=lambda: [],
        description="Top flight options found for this trip.",
    )
    sources: list[Source] = Field(default_factory=lambda: [])


class TripPlanResponse(BaseModel):
    itinerary: Itinerary
