from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

DataT = TypeVar("DataT")
PayloadT = TypeVar("PayloadT")


class ToolStatus(str, Enum):
    """Outcome of a single tool invocation."""

    SUCCESS = "success"
    EMPTY = "empty"
    ERROR = "error"


class ToolError(BaseModel):
    """Structured error detail attached to a failed ToolResult."""

    message: str
    retryable: bool = False
    code: str | None = None


class ToolResult(BaseModel, Generic[DataT]):
    """Canonical envelope returned by every tool.

    Wraps a provider call with a uniform contract so downstream graph nodes can consume tool
    output without reparsing free text. `data` carries the typed payload on success; `error`
    carries structured failure detail. Use the `ok`, `empty`, and `fail` constructors rather
    than building instances directly.
    """

    status: ToolStatus
    provider: str
    provider_request_id: str | None = None
    latency_ms: float | None = None
    cached: bool = False
    data: DataT | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def _check_status_invariants(self) -> "ToolResult[DataT]":
        """Enforce that `error` is present only for ERROR results and absent otherwise."""
        is_error_status = self.status is ToolStatus.ERROR

        if is_error_status and self.error is None:
            raise ValueError("ToolResult with status ERROR must include an error")

        if not is_error_status and self.error is not None:
            raise ValueError("ToolResult with a non-error status must not include an error")

        return self

    @classmethod
    def ok(
        cls,
        *,
        provider: str,
        data: PayloadT,
        provider_request_id: str | None = None,
        latency_ms: float | None = None,
        cached: bool = False,
    ) -> "ToolResult[PayloadT]":
        """Build a successful result carrying a typed payload."""
        return ToolResult(
            status=ToolStatus.SUCCESS,
            provider=provider,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
            cached=cached,
            data=data,
        )

    @classmethod
    def empty(
        cls,
        *,
        provider: str,
        provider_request_id: str | None = None,
        latency_ms: float | None = None,
        cached: bool = False,
    ) -> "ToolResult[DataT]":
        """Build a result for a call that succeeded but returned no data."""
        return cls(
            status=ToolStatus.EMPTY,
            provider=provider,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
            cached=cached,
            data=None,
        )

    @classmethod
    def fail(
        cls,
        *,
        provider: str,
        message: str,
        retryable: bool = False,
        code: str | None = None,
        provider_request_id: str | None = None,
        latency_ms: float | None = None,
    ) -> "ToolResult[DataT]":
        """Build a failed result with structured error detail."""
        error = ToolError(message=message, retryable=retryable, code=code)

        return cls(
            status=ToolStatus.ERROR,
            provider=provider,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
            error=error,
        )


class FlightOffer(BaseModel):
    """A single flight offer, preserving the provider offer ID and full price."""

    offer_id: str
    airline: str
    stops: int
    total_amount: str
    currency: str
    outbound_date: str
    duration_min: int | None = None
    return_date: str | None = None
    booking_url: str | None = None


class FlightSearchResult(BaseModel):
    """Typed payload for a flight search, carried as the `data` of a ToolResult."""

    origin: str
    destination: str
    departure_date: str
    passengers: int
    return_date: str | None = None
    offers: list[FlightOffer] = Field(default_factory=lambda: [])


class HotelResult(BaseModel):
    """A single hotel, preserving the provider hotel ID, coordinates, and pricing."""

    hotel_id: str
    name: str
    total_price: str
    currency: str
    address: str | None = None
    rating: float | None = None
    nightly_price: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    booking_url: str | None = None


class HotelSearchResult(BaseModel):
    """Typed payload for a hotel search, carried as the `data` of a ToolResult."""

    city: str
    country_code: str
    checkin: str
    checkout: str
    adults: int
    hotels: list[HotelResult] = Field(default_factory=lambda: [])


class WeatherDay(BaseModel):
    """Daily forecast values for a single date."""

    date: str
    temp_max_c: float | None = None
    temp_min_c: float | None = None
    precipitation_mm: float | None = None


class WeatherResult(BaseModel):
    """Typed payload for a weather forecast, carried as the `data` of a ToolResult."""

    location: str
    latitude: float | None = None
    longitude: float | None = None
    days: list[WeatherDay] = Field(default_factory=lambda: [])


class PlaceResult(BaseModel):
    """A single point of interest, preserving the provider ID, coordinates, and metadata."""

    name: str
    place_id: str | None = None
    categories: list[str] = Field(default_factory=lambda: [])
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    price_level: str | None = None
    opening_hours: list[str] = Field(default_factory=lambda: [])
    website_url: str | None = None
    phone: str | None = None


class PlacesResult(BaseModel):
    """Typed payload for a places search, carried as the `data` of a ToolResult."""

    query: str
    places: list[PlaceResult] = Field(default_factory=lambda: [])
