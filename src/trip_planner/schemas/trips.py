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
    place_id: str | None = Field(default=None, description="Google Places place ID, if known.")
    latitude: float | None = Field(default=None, description="Latitude of the place.")
    longitude: float | None = Field(default=None, description="Longitude of the place.")
    address: str | None = Field(default=None, description="Formatted address of the place.")
    rating: float | None = Field(default=None, description="Rating out of 5, if available.")
    opening_hours: list[str] = Field(
        default_factory=lambda: [],
        description="Weekday opening-hours descriptions, if available.",
    )
    price_level: str | None = Field(
        default=None, description="Relative price level, e.g. 'PRICE_LEVEL_MODERATE'."
    )
    price_eur: float | None = Field(default=None, description="Approximate entry/ticket price in EUR.")
    ticket_url: str | None = Field(default=None, description="Booking or ticket URL, if available.")
    photo_url: str | None = Field(default=None, description="Representative photo URL, if available.")
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


class HotelOption(BaseModel):
    name: str = Field(description="Hotel name, e.g. 'Hotel Le Marais'.")
    area: str | None = Field(default=None, description="Neighbourhood or address of the hotel.")
    rating: float | None = Field(default=None, description="Star rating, e.g. 4.5.")
    nightly_price: str | None = Field(
        default=None, description="Price per night as a string, e.g. '95.00'."
    )
    total_price: str = Field(description="Total price for the stay as a string, e.g. '380.00'.")
    currency: str = Field(description="ISO currency code, e.g. 'USD'.")
    latitude: float | None = Field(default=None, description="Latitude of the hotel.")
    longitude: float | None = Field(default=None, description="Longitude of the hotel.")
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
    hotels: list[HotelOption] = Field(
        default_factory=lambda: [],
        description="Top hotel options found for this trip.",
    )
    sources: list[Source] = Field(default_factory=lambda: [])


class TripPlanResponse(BaseModel):
    itinerary: Itinerary
