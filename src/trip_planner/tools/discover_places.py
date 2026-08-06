# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedFunction=false
import time
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings
from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places import (
    GooglePlacesProvider,
    PlaceProvider,
    PlaceSearchQuery,
    ProviderPlace,
)
from trip_planner.services.types import PlaceResult, PlacesResult, ToolResult

_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
_PLACES_URL = "https://api.geoapify.com/v2/places"
_MAX_PLACES = 5
_DEFAULT_RADIUS_M = 5000
_PROVIDER = "google-places"

_settings = get_settings()

# The planner talks only to this abstraction, so Google Places can later be swapped or given a
# fallback provider without touching the tool, graph, or prompts.
_provider: PlaceProvider = GooglePlacesProvider()


class _PlacesSearchInput(BaseModel):
    city: str = Field(description="City to search points of interest in, e.g. 'Paris'.")
    categories: str = Field(
        description=(
            "Comma-separated place categories or keywords to search for, e.g. "
            "'tourist attractions, restaurants, museums'."
        )
    )
    radius_m: int = Field(
        default=_DEFAULT_RADIUS_M,
        ge=100,
        le=50000,
        description="Search radius in metres around the city centre.",
    )
    limit: int = Field(default=_MAX_PLACES, ge=1, le=20, description="Maximum places to return.")


# --- Geoapify implementation, kept as an unwired fallback provider (not used by default) ---


async def _geocode(city: str) -> tuple[float, float]:
    """Resolve a city name to (latitude, longitude) via the Geoapify geocoding API."""
    params = {"text": city, "limit": 1, "apiKey": _settings.geoapify_api_key}

    async with httpx.AsyncClient() as client:
        response = await client.get(_GEOCODE_URL, params=params, timeout=10.0)
        response.raise_for_status()

    data: dict[str, Any] = response.json()
    features: list[dict[str, Any]] = data.get("features") or []

    if not features:
        raise ValueError(f"City not found: {city!r}")

    properties: dict[str, Any] = features[0]["properties"]
    return float(properties["lat"]), float(properties["lon"])


async def _search_places(
    lat: float, lon: float, categories: str, radius_m: int, limit: int
) -> list[dict[str, Any]]:
    """Search Geoapify Places within a radius of a coordinate for the given categories."""
    params = {
        "categories": categories,
        "filter": f"circle:{lon},{lat},{radius_m}",
        "bias": f"proximity:{lon},{lat}",
        "limit": limit,
        "apiKey": _settings.geoapify_api_key,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(_PLACES_URL, params=params, timeout=10.0)
        response.raise_for_status()

    data: dict[str, Any] = response.json()
    features: list[dict[str, Any]] = data.get("features") or []

    return [feature.get("properties", {}) for feature in features]


# --- Google Places (default) implementation ---


def _format_places(places: list[ProviderPlace]) -> str:
    """Format the found places into a human-readable summary for the LLM."""
    if not places:
        return "No places found for these categories and location."

    lines: list[str] = []

    for i, place in enumerate(places, start=1):
        lines.append(f"Option {i}: {place.name}")

        if place.types:
            lines.append(f"  Categories: {', '.join(place.types)}")

        if place.address:
            lines.append(f"  Address: {place.address}")

    return "\n".join(lines)


def _to_place_result(place: ProviderPlace) -> PlaceResult:
    """Map a normalised ProviderPlace into the typed PlaceResult carried in tool state."""
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
    )


def _build_places_payload(query: str, places: list[ProviderPlace]) -> PlacesResult:
    """Map the normalised ProviderPlace matches into a typed PlacesResult payload."""
    place_results = [_to_place_result(place) for place in places]
    return PlacesResult(query=query, places=place_results)


@tool(args_schema=_PlacesSearchInput, response_format="content_and_artifact")
async def discover_places_tool(
    city: str,
    categories: str,
    radius_m: int = _DEFAULT_RADIUS_M,
    limit: int = _MAX_PLACES,
) -> tuple[str, ToolResult[PlacesResult]]:
    """Discover points of interest (attractions, restaurants, museums) in a city by category.

    Provide free-text categories such as 'tourist attractions', 'restaurants', or 'museums'.
    Returns a formatted summary of nearby places with their name, categories, and address.
    """
    start = time.perf_counter()
    query_text = f"{categories} in {city}"

    try:
        # Google Places Text Search resolves the city itself, so no separate geocoding step
        # (and no radius_m filter, which Text Search does not support) is needed here.
        places = await _provider.search_places(
            PlaceSearchQuery(text_query=query_text, max_results=limit)
        )
    except GooglePlacesError as exc:
        content = f"Places search unavailable: {exc.detail}"
        result: ToolResult[PlacesResult] = ToolResult[PlacesResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        content = f"Unexpected response from Google Places: {exc}"
        result = ToolResult[PlacesResult].fail(provider=_PROVIDER, message=content)
    else:
        payload = _build_places_payload(query_text, places)
        content = _format_places(places)
        if payload.places:
            result = ToolResult.ok(provider=_PROVIDER, data=payload)
        else:
            result = ToolResult[PlacesResult].empty(provider=_PROVIDER)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
