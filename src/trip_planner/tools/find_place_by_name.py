# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings
from trip_planner.services.types import PlaceResult, PlacesResult, ToolResult

_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.userRatingCount,places.primaryType"
)
_MAX_RESULTS = 5
_PROVIDER = "google-places"

_settings = get_settings()


class _PlacesTextSearchInput(BaseModel):
    query: str = Field(
        description="Free-text place lookup, e.g. 'Eiffel Tower' or 'sushi near Shibuya, Tokyo'."
    )
    max_results: int = Field(
        default=_MAX_RESULTS, ge=1, le=20, description="Maximum matching places to return."
    )


def _format_results(places: list[dict[str, Any]]) -> str:
    """Format Google Places text-search matches into a summary for the LLM."""
    if not places:
        return "No places found for this query."

    lines: list[str] = []

    for i, place in enumerate(places, start=1):
        display_name: dict[str, Any] = place.get("displayName", {})
        name = display_name.get("text") or "Unknown place"
        place_id = place.get("id", "")
        address = place.get("formattedAddress", "")
        rating = place.get("rating")
        rating_count = place.get("userRatingCount")

        lines.append(f"Option {i}: {name}")
        lines.append(f"  place_id: {place_id}")

        if address:
            lines.append(f"  Address: {address}")

        if rating is not None:
            rating_line = f"  Rating: {rating}"
            if rating_count is not None:
                rating_line += f" ({rating_count} reviews)"
            lines.append(rating_line)

    return "\n".join(lines)


def _build_places_payload(query: str, places: list[dict[str, Any]]) -> PlacesResult:
    """Map raw Google Places text-search matches into a typed PlacesResult payload."""
    place_results: list[PlaceResult] = []

    for place in places:
        display_name: dict[str, Any] = place.get("displayName", {})
        primary_type = place.get("primaryType")
        categories = [primary_type] if primary_type else []

        place_results.append(
            PlaceResult(
                name=display_name.get("text") or "Unknown place",
                place_id=place.get("id") or None,
                categories=categories,
                address=place.get("formattedAddress") or None,
                rating=place.get("rating"),
                user_rating_count=place.get("userRatingCount"),
            )
        )

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
    headers = {
        "X-Goog-Api-Key": _settings.google_places_api_key,
        "X-Goog-FieldMask": _FIELD_MASK,
        "Content-Type": "application/json",
    }
    body = {"textQuery": query, "pageSize": max_results}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(_TEXT_SEARCH_URL, headers=headers, json=body, timeout=10.0)
            response.raise_for_status()

        data: dict[str, Any] = response.json()
        places: list[dict[str, Any]] = data.get("places", [])
    except httpx.HTTPStatusError as exc:
        content = f"Place lookup unavailable: Google Places returned {exc.response.status_code}"
        result: ToolResult[PlacesResult] = ToolResult[PlacesResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError) as exc:
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
