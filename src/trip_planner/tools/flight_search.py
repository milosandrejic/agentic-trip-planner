# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.services.duffel_client import DuffelClient, DuffelError

_MAX_OFFERS = 3
_CABIN_CLASS = "economy"

_client = DuffelClient()


class _FlightSearchInput(BaseModel):
    origin: str = Field(description="IATA airport code for the origin, e.g. 'LHR'.")
    destination: str = Field(description="IATA airport code for the destination, e.g. 'CDG'.")
    departure_date: str = Field(description="Departure date in ISO format, e.g. '2024-07-01'.")
    return_date: str | None = Field(
        default=None, description="Return date in ISO format for round trips. Omit for one-way."
    )
    passengers: int = Field(default=1, ge=1, le=9, description="Number of adult passengers.")


def _build_offer_request(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    passengers: int,
) -> dict[str, Any]:
    """Build the Duffel offer request payload for a one-way or return journey."""
    outbound_slice: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
    }

    slices: list[dict[str, Any]] = [outbound_slice]

    if return_date is not None:
        return_slice: dict[str, Any] = {
            "origin": destination,
            "destination": origin,
            "departure_date": return_date,
        }
        slices.append(return_slice)

    passenger_list = [{"type": "adult"} for _ in range(passengers)]

    return {
        "data": {
            "slices": slices,
            "passengers": passenger_list,
            "cabin_class": _CABIN_CLASS,
        }
    }


def _format_offers(offers: list[dict[str, Any]]) -> str:
    """Format the top flight offers into a human-readable summary for the LLM."""
    if not offers:
        return "No flights found for this route and dates."

    lines: list[str] = []

    for i, offer in enumerate(offers[:_MAX_OFFERS], start=1):
        slices: list[dict[str, Any]] = offer.get("slices", [])
        total_amount = offer.get("total_amount", "N/A")
        total_currency = offer.get("total_currency", "")
        owner_name = offer.get("owner", {}).get("name", "Unknown airline")

        first_slice = slices[0] if slices else {}
        segments: list[dict[str, Any]] = first_slice.get("segments", [])
        stops = max(0, len(segments) - 1)
        duration = first_slice.get("duration", "")

        lines.append(f"Option {i}: {owner_name}")
        lines.append(f"  Price: {total_amount} {total_currency}")
        lines.append(f"  Stops: {stops}")

        if duration:
            lines.append(f"  Duration: {duration}")

    return "\n".join(lines)


@tool(args_schema=_FlightSearchInput)
async def flight_search_tool(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    passengers: int = 1,
) -> str:
    """Search for available flights between two airports on given dates.

    Returns a formatted summary of the top available offers including airline,
    price, number of stops, and flight duration. Use IATA airport codes.
    """
    offer_request_body = _build_offer_request(
        origin, destination, departure_date, return_date, passengers
    )

    try:
        request_response = await _client.post("/air/offer_requests", offer_request_body)
        offer_request_id: str = request_response["data"]["id"]

        offers_response = await _client.get(
            "/air/offers",
            params={"offer_request_id": offer_request_id, "limit": str(_MAX_OFFERS)},
        )
        offers: list[dict[str, Any]] = offers_response.get("data", [])

        return _format_offers(offers)

    except DuffelError as exc:
        return f"Flight search unavailable: {exc.detail}"

    except (KeyError, TypeError) as exc:
        return f"Unexpected response from Duffel API: {exc}"
