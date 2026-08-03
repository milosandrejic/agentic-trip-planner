# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from datetime import date
from typing import Any

from trip_planner.services.hotels.provider import HotelSearchQuery, ProviderHotel
from trip_planner.services.liteapi_client import LiteApiClient

# Fetch a wide pool so client-side filtering/ranking has candidates to work with; the tool
# narrows this down to the handful of options it shows the planner.
_FETCH_LIMIT = 20
_GUEST_NATIONALITY = "US"


def _nights_between(checkin: str, checkout: str) -> int:
    """Return the number of nights for the stay, clamped to at least one."""
    stay = (date.fromisoformat(checkout) - date.fromisoformat(checkin)).days
    return max(stay, 1)


def _build_rates_request(query: HotelSearchQuery, hotel_ids: list[str]) -> dict[str, Any]:
    """Build the LiteAPI rates request payload for the given hotels and stay."""
    return {
        "hotelIds": hotel_ids,
        "checkin": query.checkin,
        "checkout": query.checkout,
        "occupancies": [{"adults": query.adults}],
        "currency": query.currency,
        "guestNationality": _GUEST_NATIONALITY,
    }


def _extract_lowest_total(hotel_rate: dict[str, Any]) -> tuple[float | None, str | None]:
    """Return the cheapest total price and its currency for a hotel, or (None, None)."""
    room_types: list[dict[str, Any]] = hotel_rate.get("roomTypes", [])

    amounts: list[float] = []
    currency: str | None = None

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
        return None, None

    return min(amounts), currency


def _to_provider_hotel(
    hotel: dict[str, Any],
    price_by_id: dict[str, tuple[float | None, str | None]],
    nights: int,
) -> ProviderHotel:
    """Map one raw LiteAPI hotel plus its rate into a normalised ProviderHotel."""
    hotel_id = str(hotel.get("id", ""))
    total_price, currency = price_by_id.get(hotel_id, (None, None))
    nightly_price = round(total_price / nights, 2) if total_price is not None else None

    return ProviderHotel(
        hotel_id=hotel_id,
        name=hotel.get("name", "Unknown hotel"),
        address=hotel.get("address") or None,
        star_rating=hotel.get("stars"),
        review_rating=hotel.get("rating"),
        nightly_price=nightly_price,
        total_price=total_price,
        currency=currency,
        latitude=hotel.get("latitude"),
        longitude=hotel.get("longitude"),
    )


class LiteApiHotelProvider:
    """LiteAPI-backed implementation of the HotelProvider protocol."""

    def __init__(self, client: LiteApiClient | None = None) -> None:
        """Initialise with an optional injected LiteAPI client for testing."""
        self._client = client or LiteApiClient()

    async def search(self, query: HotelSearchQuery) -> list[ProviderHotel]:
        """Fetch hotels and their rates from LiteAPI and normalise them to ProviderHotel."""
        hotels_response = await self._client.get(
            "/data/hotels",
            params={
                "cityName": query.city_name,
                "countryCode": query.country_code,
                "limit": str(_FETCH_LIMIT),
            },
        )
        hotels: list[dict[str, Any]] = hotels_response.get("data", [])
        if not hotels:
            return []

        hotel_ids = [str(hotel.get("id", "")) for hotel in hotels]
        rates_response = await self._client.post(
            "/hotels/rates", _build_rates_request(query, hotel_ids)
        )
        rates: list[dict[str, Any]] = rates_response.get("data", [])
        price_by_id = {
            str(rate.get("hotelId", "")): _extract_lowest_total(rate) for rate in rates
        }

        nights = _nights_between(query.checkin, query.checkout)
        return [_to_provider_hotel(hotel, price_by_id, nights) for hotel in hotels]
