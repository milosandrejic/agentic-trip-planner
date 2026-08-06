# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places import (
    GooglePlacesProvider,
    PlaceProvider,
    PlaceSearchQuery,
    ProviderPlace,
)
from trip_planner.services.types import PlaceResult, PlacesResult, ToolResult

_MAX_RESULTS = 5
_PROVIDER = "google-places"

# The planner talks only to this abstraction, so Google Places can later be swapped or given a
# fallback provider without touching the tool, graph, or prompts.
_provider: PlaceProvider = GooglePlacesProvider()


class _PlacesTextSearchInput(BaseModel):
    query: str = Field(
        description="Free-text place lookup, e.g. 'Eiffel Tower' or 'sushi near Shibuya, Tokyo'."
    )
    max_results: int = Field(
        default=_MAX_RESULTS, ge=1, le=20, description="Maximum matching places to return."
    )


def _format_results(places: list[ProviderPlace]) -> str:
    """Format Google Places text-search matches into a summary for the LLM."""
    if not places:
        return "No places found for this query."

    lines: list[str] = []

    for i, place in enumerate(places, start=1):
        lines.append(f"Option {i}: {place.name}")
        lines.append(f"  place_id: {place.place_id or ''}")

        if place.address:
            lines.append(f"  Address: {place.address}")

        if place.rating is not None:
            rating_line = f"  Rating: {place.rating}"
            if place.user_rating_count is not None:
                rating_line += f" ({place.user_rating_count} reviews)"
            lines.append(rating_line)

    return "\n".join(lines)


def _to_place_result(place: ProviderPlace) -> PlaceResult:
    """Map a normalised ProviderPlace into the typed PlaceResult carried in tool state."""
    return PlaceResult(
        name=place.name,
        place_id=place.place_id,
        address=place.address,
        latitude=place.latitude,
        longitude=place.longitude,
        rating=place.rating,
        user_rating_count=place.user_rating_count,
        price_level=place.price_level,
        opening_hours=place.opening_hours,
        website_url=place.website_url,
        phone=place.phone,
    )


def _build_places_payload(query: str, places: list[ProviderPlace]) -> PlacesResult:
    """Map the normalised ProviderPlace matches into a typed PlacesResult payload."""
    place_results = [_to_place_result(place) for place in places]
    return PlacesResult(query=query, places=place_results)


@tool(args_schema=_PlacesTextSearchInput, response_format="content_and_artifact")
async def find_place_by_name_tool(
    query: str, max_results: int = _MAX_RESULTS
) -> tuple[str, ToolResult[PlacesResult]]:
    """Look up places by name or free-text query using Google Places Text Search.

    Returns matching places with their Google place_id, name, address, and rating. Use the
    returned place_id with the place_details tool to fetch full details for a chosen place.
    """
    start = time.perf_counter()

    try:
        places = await _provider.search_places(
            PlaceSearchQuery(text_query=query, max_results=max_results)
        )
    except GooglePlacesError as exc:
        content = f"Place lookup unavailable: {exc.detail}"
        result: ToolResult[PlacesResult] = ToolResult[PlacesResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        content = f"Unexpected response from Google Places: {exc}"
        result = ToolResult[PlacesResult].fail(provider=_PROVIDER, message=content)
    else:
        payload = _build_places_payload(query, places)
        content = _format_results(places)
        if payload.places:
            result = ToolResult.ok(provider=_PROVIDER, data=payload)
        else:
            result = ToolResult[PlacesResult].empty(provider=_PROVIDER)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
