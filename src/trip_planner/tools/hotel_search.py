# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings
from trip_planner.logging_config import get_logger
from trip_planner.services.hotels import (
    HotelProvider,
    HotelSearchQuery,
    LiteApiHotelProvider,
    ProviderHotel,
    filter_and_rank_hotels,
)
from trip_planner.services.liteapi_client import LiteApiError
from trip_planner.services.types import HotelResult, HotelSearchResult, ToolResult

_MAX_HOTELS = 3
_PROVIDER = "liteapi"

_logger = get_logger(__name__)

# The planner talks only to this abstraction, so LiteAPI can later be swapped for another
# provider without touching the tool, graph, or prompts.
_provider: HotelProvider = LiteApiHotelProvider()


class _HotelSearchInput(BaseModel):
    city_name: str = Field(description="City to search hotels in, e.g. 'Paris'.")
    country_code: str = Field(description="ISO 3166-1 alpha-2 country code, e.g. 'FR'.")
    checkin: str = Field(description="Check-in date in ISO format, e.g. '2024-07-01'.")
    checkout: str = Field(description="Check-out date in ISO format, e.g. '2024-07-05'.")
    adults: int = Field(default=2, ge=1, le=8, description="Number of adult guests.")
    max_nightly_price: float | None = Field(
        default=None,
        description="Only return hotels at or below this price per night. Set it when the user "
        "asks for cheaper or budget-friendly hotels.",
    )
    min_star_rating: float | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Only return hotels at or above this star rating, e.g. 3 for '3+ star'.",
    )


def _format_hotels(hotels: list[ProviderHotel]) -> str:
    """Format the top hotels with their nightly price and rating for the LLM."""
    if not hotels:
        return "No hotels found matching the requested criteria."

    lines: list[str] = []
    for i, hotel in enumerate(hotels, start=1):
        price = f"{hotel.nightly_price:.2f}" if hotel.nightly_price is not None else "N/A"
        currency = hotel.currency or ""
        rating = hotel.star_rating if hotel.star_rating is not None else "N/A"

        lines.append(f"Option {i}: {hotel.name}")
        lines.append(f"  Price: {price} {currency} per night")
        lines.append(f"  Star rating: {rating}")
        if hotel.address:
            lines.append(f"  Address: {hotel.address}")

    return "\n".join(lines)


def _to_hotel_result(hotel: ProviderHotel) -> HotelResult:
    """Map a normalised ProviderHotel into the typed HotelResult carried in tool state."""
    nightly = f"{hotel.nightly_price:.2f}" if hotel.nightly_price is not None else None
    total = f"{hotel.total_price:.2f}" if hotel.total_price is not None else ""

    return HotelResult(
        hotel_id=hotel.hotel_id,
        name=hotel.name,
        total_price=total,
        currency=hotel.currency or "",
        address=hotel.address,
        rating=hotel.review_rating if hotel.review_rating is not None else hotel.star_rating,
        nightly_price=nightly,
        latitude=hotel.latitude,
        longitude=hotel.longitude,
        booking_url=hotel.booking_url,
    )


def _build_hotel_payload(
    query: HotelSearchQuery, hotels: list[ProviderHotel]
) -> HotelSearchResult:
    """Map the ranked ProviderHotel list into a typed HotelSearchResult payload."""
    hotel_results: list[HotelResult] = []
    for hotel in hotels:
        hotel_results.append(_to_hotel_result(hotel))

    return HotelSearchResult(
        city=query.city_name,
        country_code=query.country_code,
        checkin=query.checkin,
        checkout=query.checkout,
        adults=query.adults,
        hotels=hotel_results,
    )


@tool(args_schema=_HotelSearchInput, response_format="content_and_artifact")
async def hotel_search_tool(
    city_name: str,
    country_code: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    max_nightly_price: float | None = None,
    min_star_rating: float | None = None,
) -> tuple[str, ToolResult[HotelSearchResult]]:
    """Search for available hotels in a city for the given check-in and check-out dates.

    Accepts optional max_nightly_price and min_star_rating constraints so a follow-up asking
    for cheaper or higher-rated hotels returns a different set. Returns a formatted summary of
    the top matching hotels including name, nightly price, star rating, and address.
    """
    start = time.perf_counter()
    query = HotelSearchQuery(
        city_name=city_name,
        country_code=country_code,
        checkin=checkin,
        checkout=checkout,
        adults=adults,
        currency=get_settings().default_currency,
        max_nightly_price=max_nightly_price,
        min_star_rating=min_star_rating,
    )
    _logger.info(
        "hotel_search.request",
        city=city_name,
        country_code=country_code,
        checkin=checkin,
        checkout=checkout,
        adults=adults,
        max_nightly_price=max_nightly_price,
        min_star_rating=min_star_rating,
    )

    ranked: list[ProviderHotel] = []
    try:
        candidates = await _provider.search(query)
        ranked = filter_and_rank_hotels(candidates, query)[:_MAX_HOTELS]

        if not ranked:
            content = "No hotels found matching the requested criteria."
            result: ToolResult[HotelSearchResult] = ToolResult[HotelSearchResult].empty(
                provider=_PROVIDER
            )
        else:
            payload = _build_hotel_payload(query, ranked)
            content = _format_hotels(ranked)
            result = ToolResult.ok(provider=_PROVIDER, data=payload)
    except LiteApiError as exc:
        content = f"Hotel search unavailable: {exc.detail}"
        result = ToolResult[HotelSearchResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        content = f"Unexpected response from LiteAPI: {exc}"
        result = ToolResult[HotelSearchResult].fail(provider=_PROVIDER, message=content)

    _logger.info(
        "hotel_search.response",
        provider=_PROVIDER,
        status=result.status.value,
        returned=[(hotel.name, hotel.nightly_price) for hotel in ranked],
    )
    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
