# pyright: reportMissingTypeStubs=false
from typing import Protocol

from pydantic import BaseModel, Field


class PlaceSearchQuery(BaseModel):
    """A free-text place lookup, provider-independent."""

    text_query: str
    max_results: int = 5


class NearbyPlacesQuery(BaseModel):
    """A category-based nearby search around a coordinate, provider-independent."""

    latitude: float
    longitude: float
    radius_m: int = 5000
    included_types: list[str] = Field(
        default_factory=lambda: [], description="Provider-native place type keys to search for."
    )
    max_results: int = 5


class ProviderPlace(BaseModel):
    """A point of interest normalised across providers.

    Carries every metadata field the provider returned so callers never need a second lookup
    for data that was already available from the first call.
    """

    place_id: str | None = None
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    price_level: str | None = None
    opening_hours: list[str] = Field(default_factory=lambda: [])
    website_url: str | None = None
    phone: str | None = None
    business_status: str | None = None
    types: list[str] = Field(default_factory=lambda: [])
    editorial_summary: str | None = None
    photo_reference: str | None = None
    google_maps_url: str | None = None


class PlaceProvider(Protocol):
    """A place search/details backend. Google Places implements this today.

    Keeping the planner and tools behind this abstraction means swapping or adding a place
    provider (e.g. a Geoapify fallback) never touches the agent -- only a new implementation
    of this protocol is required.
    """

    async def search_places(self, query: PlaceSearchQuery) -> list[ProviderPlace]:
        """Return normalised places matching a free-text query."""
        ...

    async def nearby_places(self, query: NearbyPlacesQuery) -> list[ProviderPlace]:
        """Return normalised places of the given types near a coordinate."""
        ...

    async def get_place_details(self, place_id: str) -> ProviderPlace:
        """Return full normalised details for a place."""
        ...
