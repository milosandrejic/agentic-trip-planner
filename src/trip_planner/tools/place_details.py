# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings

_DETAILS_URL = "https://places.googleapis.com/v1/places"
_FIELD_MASK = (
    "displayName,formattedAddress,rating,userRatingCount,priceLevel,"
    "regularOpeningHours.weekdayDescriptions,websiteUri,internationalPhoneNumber,location"
)

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


@tool(args_schema=_PlaceDetailsInput)
async def place_details_tool(place_id: str) -> str:
    """Get detailed information about a specific place using its Google Places place ID.

    Returns the place's name, address, rating, price level, contact details, and opening
    hours. Use this only for the top few places you have already selected, since each call
    consumes a paid detail lookup.
    """
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
        return _format_details(place)

    except httpx.HTTPStatusError as exc:
        return f"Place details unavailable: Google Places returned {exc.response.status_code}"

    except (KeyError, TypeError) as exc:
        return f"Unexpected response from Google Places: {exc}"
