# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings
from trip_planner.services.types import PlaceResult, PlacesResult, ToolResult

_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
_PLACES_URL = "https://api.geoapify.com/v2/places"
_MAX_PLACES = 5
_DEFAULT_RADIUS_M = 5000
_PROVIDER = "geoapify"

_settings = get_settings()


class _PlacesSearchInput(BaseModel):
    city: str = Field(description="City to search points of interest in, e.g. 'Paris'.")
    categories: str = Field(
        description=(
            "Comma-separated Geoapify category keys, e.g. "
            "'tourism.sights,catering.restaurant,entertainment.museum'."
        )
    )
    radius_m: int = Field(
        default=_DEFAULT_RADIUS_M,
        ge=100,
        le=50000,
        description="Search radius in metres around the city centre.",
    )
    limit: int = Field(default=_MAX_PLACES, ge=1, le=20, description="Maximum places to return.")


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


def _format_places(places: list[dict[str, Any]]) -> str:
    """Format the found places into a human-readable summary for the LLM."""
    if not places:
        return "No places found for these categories and location."

    lines: list[str] = []

    for i, place in enumerate(places, start=1):
        name = place.get("name") or "Unnamed place"
        categories: list[str] = place.get("categories", [])
        address = place.get("formatted") or place.get("address_line2") or ""

        lines.append(f"Option {i}: {name}")

        if categories:
            lines.append(f"  Categories: {', '.join(categories)}")

        if address:
            lines.append(f"  Address: {address}")

    return "\n".join(lines)


def _build_places_payload(query: str, places: list[dict[str, Any]]) -> PlacesResult:
    """Map raw Geoapify place properties into a typed PlacesResult payload."""
    place_results: list[PlaceResult] = []

    for place in places:
        categories: list[str] = place.get("categories", [])
        address = place.get("formatted") or place.get("address_line2") or None

        place_results.append(
            PlaceResult(
                name=place.get("name") or "Unnamed place",
                place_id=place.get("place_id"),
                categories=categories,
                address=address,
                latitude=place.get("lat"),
                longitude=place.get("lon"),
            )
        )

    return PlacesResult(query=query, places=place_results)


@tool(args_schema=_PlacesSearchInput, response_format="content_and_artifact")
async def discover_places_tool(
    city: str,
    categories: str,
    radius_m: int = _DEFAULT_RADIUS_M,
    limit: int = _MAX_PLACES,
) -> tuple[str, ToolResult[PlacesResult]]:
    """Discover points of interest (attractions, restaurants, museums) in a city by category.

    Provide Geoapify category keys such as 'tourism.sights', 'catering.restaurant', or
    'entertainment.museum'. Returns a formatted summary of nearby places with their name,
    categories, and address.
    """
    start = time.perf_counter()

    try:
        lat, lon = await _geocode(city)
        places = await _search_places(lat, lon, categories, radius_m, limit)
    except ValueError as exc:
        content = f"Places search unavailable: {exc}"
        result: ToolResult[PlacesResult] = ToolResult[PlacesResult].fail(
            provider=_PROVIDER, message=content
        )
    except httpx.HTTPStatusError as exc:
        content = f"Places search unavailable: Geoapify returned {exc.response.status_code}"
        result = ToolResult[PlacesResult].fail(provider=_PROVIDER, message=content, retryable=True)
    except (KeyError, TypeError) as exc:
        content = f"Unexpected response from Geoapify: {exc}"
        result = ToolResult[PlacesResult].fail(provider=_PROVIDER, message=content)
    else:
        payload = _build_places_payload(f"{categories} in {city}", places)
        content = _format_places(places)
        if payload.places:
            result = ToolResult.ok(provider=_PROVIDER, data=payload)
        else:
            result = ToolResult[PlacesResult].empty(provider=_PROVIDER)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
