# pyright: reportMissingTypeStubs=false
from typing import Protocol

from pydantic import BaseModel, Field


class HotelSearchQuery(BaseModel):
    """A provider-independent hotel search request.

    Carries the optional price/rating constraints so a follow-up ('cheaper', '3 or 4-star')
    changes the search instead of repeating it unchanged.
    """

    city_name: str
    country_code: str
    checkin: str
    checkout: str
    adults: int = 2
    currency: str
    max_nightly_price: float | None = Field(
        default=None, description="Reject hotels priced above this per-night amount."
    )
    min_star_rating: float | None = Field(
        default=None, description="Reject hotels below this star rating."
    )


class ProviderHotel(BaseModel):
    """A hotel normalised across providers, before client-side filtering and ranking.

    Star rating (1-5) and review rating (provider review score) are kept distinct because
    providers report them separately and callers filter on the star rating.
    """

    hotel_id: str
    name: str
    address: str | None = None
    star_rating: float | None = None
    review_rating: float | None = None
    nightly_price: float | None = None
    total_price: float | None = None
    currency: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    booking_url: str | None = None


class HotelProvider(Protocol):
    """A hotel search backend. LiteAPI implements this today; Booking/Amadeus can later.

    Keeping the planner and graph behind this abstraction means swapping providers never
    touches the agent — only a new implementation of `search` is required.
    """

    async def search(self, query: HotelSearchQuery) -> list[ProviderHotel]:
        """Return normalised hotels for the query, without applying client-side filters."""
        ...
