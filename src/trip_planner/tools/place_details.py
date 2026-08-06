# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places import GooglePlacesProvider, PlaceProvider, ProviderPlace
from trip_planner.services.types import PlaceResult, ToolResult

_PROVIDER = "google-places"

# The planner talks only to this abstraction, so Google Places can later be swapped or given a
# fallback provider without touching the tool, graph, or prompts.
_provider: PlaceProvider = GooglePlacesProvider()


class _PlaceDetailsInput(BaseModel):
    place_id: str = Field(
        description="Google Places place ID, e.g. 'ChIJD3uTd9hx5kcR1IQvGfr8dbk'."
    )


def _format_details(place: ProviderPlace) -> str:
    """Format Google Place details into a human-readable summary for the LLM."""
    lines: list[str] = [place.name]

    if place.address:
        lines.append(f"  Address: {place.address}")

    if place.rating is not None:
        rating_line = f"  Rating: {place.rating}"
        if place.user_rating_count is not None:
            rating_line += f" ({place.user_rating_count} reviews)"
        lines.append(rating_line)

    if place.price_level:
        lines.append(f"  Price level: {place.price_level}")

    if place.phone:
        lines.append(f"  Phone: {place.phone}")

    if place.website_url:
        lines.append(f"  Website: {place.website_url}")

    if place.opening_hours:
        lines.append("  Opening hours:")
        lines.extend(f"    {day}" for day in place.opening_hours)

    return "\n".join(lines)


def _build_place_payload(place: ProviderPlace) -> PlaceResult:
    """Map a normalised ProviderPlace into the typed PlaceResult payload."""
    return PlaceResult(
        name=place.name,
        place_id=place.place_id,
        categories=place.types,
        address=place.address,
        latitude=place.latitude,
        longitude=place.longitude,
        rating=place.rating,
        user_rating_count=place.user_rating_count,
        price_level=place.price_level,
        opening_hours=place.opening_hours,
        website_url=place.website_url,
        phone=place.phone,
        business_status=place.business_status,
        editorial_summary=place.editorial_summary,
        google_maps_url=place.google_maps_url,
    )


@tool(args_schema=_PlaceDetailsInput, response_format="content_and_artifact")
async def place_details_tool(place_id: str) -> tuple[str, ToolResult[PlaceResult]]:
    """Get detailed information about a specific place using its Google Places place ID.

    Returns the place's name, address, rating, price level, contact details, and opening
    hours. Use this only for the top few places you have already selected, since each call
    consumes a paid detail lookup.
    """
    start = time.perf_counter()

    try:
        place = await _provider.get_place_details(place_id)
    except GooglePlacesError as exc:
        content = f"Place details unavailable: {exc.detail}"
        result: ToolResult[PlaceResult] = ToolResult[PlaceResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        content = f"Unexpected response from Google Places: {exc}"
        result = ToolResult[PlaceResult].fail(provider=_PROVIDER, message=content)
    else:
        payload = _build_place_payload(place)
        content = _format_details(place)
        result = ToolResult.ok(provider=_PROVIDER, data=payload)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
