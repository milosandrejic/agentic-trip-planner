# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import re
import time
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from trip_planner.config import get_settings
from trip_planner.services.currency_service import CurrencyConverter, CurrencyError
from trip_planner.services.duffel_client import DuffelClient, DuffelError
from trip_planner.services.types import FlightOffer, FlightSearchResult, ToolResult

_MAX_OFFERS = 3
_CABIN_CLASS = "economy"
_PROVIDER = "duffel"

_client = DuffelClient()
_converter = CurrencyConverter()

_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


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


async def _convert_offer_currencies(
    offers: list[dict[str, Any]], target_currency: str
) -> list[dict[str, Any]]:
    """Return offers with total_amount/total_currency converted to the target currency.

    Duffel prices each offer in the airline's currency, so an itinerary can mix currencies;
    normalising here keeps every price in one currency. On conversion failure the provider's
    original price is kept so the offer still surfaces.
    """
    normalized: list[dict[str, Any]] = []

    for offer in offers:
        raw_amount = offer.get("total_amount")
        raw_currency = offer.get("total_currency", "")
        converted = dict(offer)

        if raw_amount is not None and raw_currency:
            try:
                amount = await _converter.convert(
                    float(raw_amount), raw_currency, target_currency
                )
            except (CurrencyError, ValueError):
                pass
            else:
                converted["total_amount"] = f"{amount:.2f}"
                converted["total_currency"] = target_currency

        normalized.append(converted)

    return normalized


def _parse_duration_minutes(duration: str) -> int | None:
    """Parse an ISO 8601 duration (e.g. 'PT9H5M') into whole minutes, or None if unparseable."""
    match = _ISO8601_DURATION_RE.match(duration)
    if not match:
        return None

    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)

    return round(days * 24 * 60 + hours * 60 + minutes + seconds / 60)


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


def _build_flight_payload(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    passengers: int,
    offers: list[dict[str, Any]],
) -> FlightSearchResult:
    """Map raw Duffel offers into a typed FlightSearchResult payload for graph state."""
    flight_offers: list[FlightOffer] = []

    for offer in offers[:_MAX_OFFERS]:
        slices: list[dict[str, Any]] = offer.get("slices", [])
        first_slice = slices[0] if slices else {}
        segments: list[dict[str, Any]] = first_slice.get("segments", [])
        stops = max(0, len(segments) - 1)

        flight_offers.append(
            FlightOffer(
                offer_id=str(offer.get("id", "")),
                airline=offer.get("owner", {}).get("name", "Unknown airline"),
                stops=stops,
                total_amount=str(offer.get("total_amount", "")),
                currency=offer.get("total_currency", ""),
                outbound_date=departure_date,
                return_date=return_date,
                duration_min=_parse_duration_minutes(first_slice.get("duration", "")),
            )
        )

    return FlightSearchResult(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        passengers=passengers,
        return_date=return_date,
        offers=flight_offers,
    )


@tool(args_schema=_FlightSearchInput, response_format="content_and_artifact")
async def flight_search_tool(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    passengers: int = 1,
) -> tuple[str, ToolResult[FlightSearchResult]]:
    """Search for available flights between two airports on given dates.

    Returns a formatted summary of the top available offers including airline,
    price, number of stops, and flight duration. Use IATA airport codes.
    """
    start = time.perf_counter()
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
        offers = await _convert_offer_currencies(offers, get_settings().default_currency)
    except DuffelError as exc:
        content = f"Flight search unavailable: {exc.detail}"
        result: ToolResult[FlightSearchResult] = ToolResult[FlightSearchResult].fail(
            provider=_PROVIDER, message=content, retryable=True
        )
    except (KeyError, TypeError) as exc:
        content = f"Unexpected response from Duffel API: {exc}"
        result = ToolResult[FlightSearchResult].fail(provider=_PROVIDER, message=content)
    else:
        payload = _build_flight_payload(
            origin, destination, departure_date, return_date, passengers, offers
        )
        content = _format_offers(offers)
        if payload.offers:
            result = ToolResult.ok(provider=_PROVIDER, data=payload)
        else:
            result = ToolResult[FlightSearchResult].empty(provider=_PROVIDER)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
