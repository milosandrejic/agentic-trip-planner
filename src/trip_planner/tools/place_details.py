# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings
from trip_planner.services.types import PlaceResult, ToolResult

_DETAILS_URL = "https://places.googleapis.com/v1/places"
_FIELD_MASK = (
    "displayName,formattedAddress,rating,userRatingCount,priceLevel,"
    "regularOpeningHours.weekdayDescriptions,websiteUri,internationalPhoneNumber,location"
)
_PROVIDER = "google-places"

_settings = get_settings()


class _PlaceDetailsInput(BaseModel):
    place_id: str = Field(
        description="Google Places place ID, e.g. 'ChIJD3uTd9hx5kcR1IQvGfr8dbk'."
    )


def _format_details(place: dict[str, Any]) -> str:
    """Format Google Place details into a human-readable summary for the LLM."""
    display_name: dict[str, Any] = place.get("displayName", {})
    name = display_name.get("text") or "Unknown place"
    address = place.get("formattedAddress", "")
    rating = place.get("rating")
    rating_count = place.get("userRatingCount")
    price_level = place.get("priceLevel", "")
    website = place.get("websiteUri", "")
    phone = place.get("internationalPhoneNumber", "")

    opening_hours: dict[str, Any] = place.get("regularOpeningHours", {})
    weekday_descriptions: list[str] = opening_hours.get("weekdayDescriptions", [])

    lines: list[str] = [name]

    if address:
        lines.append(f"  Address: {address}")

    if rating is not None:
        rating_line = f"  Rating: {rating}"
        if rating_count is not None:
            rating_line += f" ({rating_count} reviews)"
        lines.append(rating_line)

    if price_level:
        lines.append(f"  Price level: {price_level}")

    if phone:
        lines.append(f"  Phone: {phone}")

    if website:
        lines.append(f"  Website: {website}")

    if weekday_descriptions:
        lines.append("  Opening hours:")
        lines.extend(f"    {day}" for day in weekday_descriptions)

    return "\n".join(lines)


def _build_place_payload(place: dict[str, Any]) -> PlaceResult:
    """Map a raw Google Place details response into a typed PlaceResult payload."""
    display_name: dict[str, Any] = place.get("displayName", {})
    location: dict[str, Any] = place.get("location", {})
    opening_hours: dict[str, Any] = place.get("regularOpeningHours", {})
    weekday_descriptions: list[str] = opening_hours.get("weekdayDescriptions", [])
    price_level = place.get("priceLevel") or None

    return PlaceResult(
        name=display_name.get("text") or "Unknown place",
        address=place.get("formattedAddress") or None,
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
        price_level=price_level,
        opening_hours=weekday_descriptions,
        website_url=place.get("websiteUri") or None,
        phone=place.get("internationalPhoneNumber") or None,
    )


@tool(args_schema=_PlaceDetailsInput, response_format="content_and_artifact")
async def place_details_tool(place_id: str) -> tuple[str, ToolResult[PlaceResult]]:
    """Get detailed information about a specific place using its Google Places place ID.

    Returns the place's name, address, rating, price level, contact details, and opening
    hours. Use this only for the top few places you have already selected, since each call
    consumes a paid detail lookup.
    """
    start = time.perf_counter()
    headers = {
        "X-Goog-Api-Key": _settings.google_places_api_key,
        "X-Goog-FieldMask": _FIELD_MASK,
    }
    url = f"{_DETAILS_URL}/{place_id}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()

        place: dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        content = f"Place details unavailable: Google Places returned {exc.response.status_code}"
        result: ToolResult[PlaceResult] = ToolResult[PlaceResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError) as exc:
        content = f"Unexpected response from Google Places: {exc}"
        result = ToolResult[PlaceResult].fail(provider=_PROVIDER, message=content)
    else:
        payload = _build_place_payload(place)
        content = _format_details(place)
        result = ToolResult.ok(provider=_PROVIDER, data=payload)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
