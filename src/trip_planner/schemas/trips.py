from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def _blank_to_none(value: object) -> object:
    """Treat empty or whitespace-only strings as unknown so they serialize as null, not ''."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _fresh_id(value: object) -> str:
    """Keep a genuinely assigned UUID, but mint a fresh one for anything else.

    Structured-output schemas mark every field required, so the LLM always emits something for
    id even though it has a default_factory (which only fires when the field is omitted
    entirely) — and it has been observed echoing a hotel provider's own id straight through. An
    id is only trusted when it's already a valid UUID, e.g. one this app assigned on an earlier
    turn and is now round-tripping through the checkpointer or the database. Anything else
    (a hallucinated or provider id) is replaced with a fresh one.
    """
    if isinstance(value, str):
        try:
            UUID(value)
        except ValueError:
            pass
        else:
            return value
    return str(uuid4())


class Source(BaseModel):
    title: str
    url: str


def _keep_valid_sources(sources: list[Source]) -> list[Source]:
    """Drop sources without a usable http(s) URL instead of surfacing empty or broken links."""
    return [source for source in sources if source.url.startswith(("http://", "https://"))]


class Activity(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Stable identifier for this activity, used by the frontend to edit, delete, "
        "reorder, and diff itinerary versions. Never set this yourself.",
    )
    time: str = Field(description="Time of day, e.g. 'Morning', '09:00'")
    description: str
    duration_hours: float | None = None
    place_id: str | None = Field(default=None, description="Google Places place ID, if known.")
    latitude: float | None = Field(default=None, description="Latitude of the place.")
    longitude: float | None = Field(default=None, description="Longitude of the place.")
    address: str | None = Field(default=None, description="Formatted address of the place.")
    rating: float | None = Field(default=None, description="Rating out of 5, if available.")
    user_rating_count: int | None = Field(default=None, description="Number of ratings, if available.")
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
    website_url: str | None = Field(default=None, description="Official website URL, if available.")
    phone: str | None = Field(default=None, description="Contact phone number, if available.")
    business_status: str | None = Field(
        default=None, description="e.g. 'OPERATIONAL', 'CLOSED_TEMPORARILY', if available."
    )
    categories: list[str] = Field(
        default_factory=lambda: [], description="Place types/categories, if available."
    )
    editorial_summary: str | None = Field(
        default=None, description="A short editorial description of the place, if available."
    )
    google_maps_url: str | None = Field(default=None, description="Google Maps URL, if available.")
    sources: list[Source] = Field(default_factory=lambda: [])

    @field_validator("id", mode="before")
    @classmethod
    def _assign_fresh_id(cls, value: object) -> str:
        return _fresh_id(value)

    @field_validator("sources", mode="after")
    @classmethod
    def _drop_invalid_sources(cls, sources: list[Source]) -> list[Source]:
        return _keep_valid_sources(sources)


class DayPlan(BaseModel):
    day: int = Field(description="Day number, starting from 1")
    date: str | None = Field(default=None, description="ISO date, e.g. '2024-07-01'")
    location: str
    weather_summary: str | None = None
    activities: list[Activity]


class FlightOption(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Stable identifier for this flight option, used by the frontend to diff "
        "itinerary versions. Never set this yourself.",
    )
    airline: str = Field(description="Airline name, e.g. 'British Airways'.")
    stops: int = Field(description="Number of stops (0 = direct).")
    duration_min: int | None = Field(default=None, description="Total flight duration in minutes.")
    price: float | None = Field(default=None, description="Total ticket price, e.g. 250.00. Null if unknown.")
    currency: str | None = Field(default=None, description="ISO currency code, e.g. 'GBP'. Null if unknown.")
    outbound_date: str = Field(description="Outbound departure date in ISO format.")
    return_date: str | None = Field(default=None, description="Return departure date for round trips.")
    booking_url: str | None = Field(default=None, description="Direct booking URL if available.")

    @field_validator("id", mode="before")
    @classmethod
    def _assign_fresh_id(cls, value: object) -> str:
        return _fresh_id(value)

    @field_validator("price", "currency", "duration_min", "return_date", "booking_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class HotelOption(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Stable identifier for this hotel option, used by the frontend to diff "
        "itinerary versions. Never set this yourself.",
    )
    name: str = Field(description="Hotel name, e.g. 'Hotel Le Marais'.")
    area: str | None = Field(default=None, description="Neighbourhood or address of the hotel.")
    rating: float | None = Field(default=None, description="Star rating, e.g. 4.5.")
    nightly_price: float | None = Field(default=None, description="Price per night, e.g. 95.00. Null if unknown.")
    is_estimated: bool = Field(default=False, description="True when nightly_price is an estimate, not a quoted rate.")
    total_price: float | None = Field(default=None, description="Total price for the stay, e.g. 380.00. Null if unknown.")
    currency: str | None = Field(default=None, description="ISO currency code, e.g. 'USD'. Null if unknown.")
    latitude: float | None = Field(default=None, description="Latitude of the hotel.")
    longitude: float | None = Field(default=None, description="Longitude of the hotel.")
    booking_url: str | None = Field(default=None, description="Direct booking URL if available.")

    @model_validator(mode="before")
    @classmethod
    def _split_estimate_marker(cls, data: object) -> object:
        """A leading '~' on nightly_price marks an estimate; lift that into is_estimated."""
        if not isinstance(data, dict):
            return data
        fields = cast("dict[str, object]", data)
        raw = fields.get("nightly_price")
        if isinstance(raw, str) and raw.strip().startswith("~"):
            return {
                **fields,
                "nightly_price": raw.strip()[1:],
                "is_estimated": True,
            }
        return fields

    @field_validator("id", mode="before")
    @classmethod
    def _assign_fresh_id(cls, value: object) -> str:
        return _fresh_id(value)

    @field_validator(
        "area", "nightly_price", "total_price", "currency", "booking_url", mode="before"
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class Itinerary(BaseModel):
    destination: str
    total_days: int
    summary: str = Field(
        description=(
            "A trip-focused overview (2-4 sentences) of the destination and plan highlights. "
            "Must not mention prices, tool or provider names, or search/API details."
        )
    )
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

    @field_validator("sources", mode="after")
    @classmethod
    def _drop_invalid_sources(cls, sources: list[Source]) -> list[Source]:
        return _keep_valid_sources(sources)
