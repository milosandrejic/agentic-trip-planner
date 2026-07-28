# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.services.liteapi_client import LiteApiClient, LiteApiError

_MAX_HOTELS = 3
_CURRENCY = "USD"
_GUEST_NATIONALITY = "US"

_client = LiteApiClient()


class _HotelSearchInput(BaseModel):
    city_name: str = Field(description="City to search hotels in, e.g. 'Paris'.")
    country_code: str = Field(description="ISO 3166-1 alpha-2 country code, e.g. 'FR'.")
    checkin: str = Field(description="Check-in date in ISO format, e.g. '2024-07-01'.")
    checkout: str = Field(description="Check-out date in ISO format, e.g. '2024-07-05'.")
    adults: int = Field(default=2, ge=1, le=8, description="Number of adult guests.")


def _build_rates_request(
    hotel_ids: list[str],
    checkin: str,
    checkout: str,
    adults: int,
) -> dict[str, Any]:
    """Build the LiteAPI rates request payload for the given hotels and stay."""
    return {
        "hotelIds": hotel_ids,
        "checkin": checkin,
        "checkout": checkout,
        "occupancies": [{"adults": adults}],
        "currency": _CURRENCY,
        "guestNationality": _GUEST_NATIONALITY,
    }


def _extract_lowest_price(hotel_rate: dict[str, Any]) -> tuple[str, str]:
    """Return the (amount, currency) of the cheapest rate for a hotel, or ('N/A', '')."""
    room_types: list[dict[str, Any]] = hotel_rate.get("roomTypes", [])

    amounts: list[float] = []
    currency = ""

    for room_type in room_types:
        rates: list[dict[str, Any]] = room_type.get("rates", [])
        for rate in rates:
            total = rate.get("retailRate", {}).get("total", [])
            first_total = total[0] if total else {}
            amount = first_total.get("amount")
            if amount is not None:
                amounts.append(float(amount))
                currency = first_total.get("currency", currency)

    if not amounts:
        return "N/A", ""

    return f"{min(amounts):.2f}", currency


def _format_hotels(
    hotels: list[dict[str, Any]], price_by_id: dict[str, tuple[str, str]]
) -> str:
    """Format the top hotels with their lowest available price for the LLM."""
    if not hotels:
        return "No hotels found for this city and dates."

    lines: list[str] = []

    for i, hotel in enumerate(hotels[:_MAX_HOTELS], start=1):
        hotel_id = str(hotel.get("id", ""))
        name = hotel.get("name", "Unknown hotel")
        rating = hotel.get("rating", hotel.get("stars", "N/A"))
        address = hotel.get("address", "")

        amount, currency = price_by_id.get(hotel_id, ("N/A", ""))

        lines.append(f"Option {i}: {name}")
        lines.append(f"  Price: {amount} {currency} total")
        lines.append(f"  Rating: {rating}")

        if address:
            lines.append(f"  Address: {address}")

    return "\n".join(lines)


@tool(args_schema=_HotelSearchInput)
async def hotel_search_tool(
    city_name: str,
    country_code: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
) -> str:
    """Search for available hotels in a city for the given check-in and check-out dates.

    Returns a formatted summary of the top available hotels including name, total
    price for the stay, star rating, and address.
    """
    try:
        hotels_response = await _client.get(
            "/data/hotels",
            params={
                "cityName": city_name,
                "countryCode": country_code,
                "limit": str(_MAX_HOTELS),
            },
        )
        hotels: list[dict[str, Any]] = hotels_response.get("data", [])

        if not hotels:
            return "No hotels found for this city and dates."

        hotel_ids = [str(hotel.get("id", "")) for hotel in hotels]
        rates_body = _build_rates_request(hotel_ids, checkin, checkout, adults)

        rates_response = await _client.post("/hotels/rates", rates_body)
        hotel_rates: list[dict[str, Any]] = rates_response.get("data", [])

        price_by_id = {
            str(rate.get("hotelId", "")): _extract_lowest_price(rate) for rate in hotel_rates
        }

        return _format_hotels(hotels, price_by_id)

    except LiteApiError as exc:
        return f"Hotel search unavailable: {exc.detail}"

    except (KeyError, TypeError, ValueError) as exc:
        return f"Unexpected response from LiteAPI: {exc}"
