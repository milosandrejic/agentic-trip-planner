# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings

_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
_PLACES_URL = "https://api.geoapify.com/v2/places"
_MAX_PLACES = 5
_DEFAULT_RADIUS_M = 5000

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


@tool(args_schema=_PlacesSearchInput)
async def places_search_tool(
    city: str,
    categories: str,
    radius_m: int = _DEFAULT_RADIUS_M,
    limit: int = _MAX_PLACES,
) -> str:
    """Search for points of interest (attractions, restaurants, museums) in a city.

    Provide Geoapify category keys such as 'tourism.sights', 'catering.restaurant', or
    'entertainment.museum'. Returns a formatted summary of nearby places with their name,
    categories, and address.
    """
    try:
        lat, lon = await _geocode(city)
        places = await _search_places(lat, lon, categories, radius_m, limit)
        return _format_places(places)

    except ValueError as exc:
        return f"Places search unavailable: {exc}"

    except httpx.HTTPStatusError as exc:
        return f"Places search unavailable: Geoapify returned {exc.response.status_code}"

    except (KeyError, TypeError) as exc:
        return f"Unexpected response from Geoapify: {exc}"
