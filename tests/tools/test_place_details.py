# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, patch

from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places import ProviderPlace
from trip_planner.services.types import ToolStatus
from trip_planner.tools.place_details import _format_details, place_details_tool

_LOUVRE = ProviderPlace(
    place_id="ChIJ123",
    name="Louvre Museum",
    address="Rue de Rivoli, 75001 Paris, France",
    rating=4.7,
    user_rating_count=320000,
    price_level="PRICE_LEVEL_MODERATE",
    website_url="https://www.louvre.fr/",
    phone="+33 1 40 20 50 50",
    opening_hours=["Monday: 9:00 AM – 6:00 PM", "Tuesday: Closed"],
    business_status="OPERATIONAL",
    types=["museum", "tourist_attraction"],
    editorial_summary="A former royal palace turned world-famous art museum.",
    google_maps_url="https://maps.google.com/?cid=123",
)

_PATCH_DETAILS = "trip_planner.tools.place_details._provider.get_place_details"


# --- _format_details ---


def test_format_details_includes_all_available_fields() -> None:
    result = _format_details(_LOUVRE)

    assert "Louvre Museum" in result
    assert "Rue de Rivoli, 75001 Paris, France" in result
    assert "4.7" in result
    assert "320000 reviews" in result
    assert "PRICE_LEVEL_MODERATE" in result
    assert "+33 1 40 20 50 50" in result
    assert "https://www.louvre.fr/" in result
    assert "Monday: 9:00 AM – 6:00 PM" in result
    assert "Tuesday: Closed" in result


def test_format_details_handles_missing_optional_fields() -> None:
    result = _format_details(ProviderPlace(name="Small Cafe"))

    assert result == "Small Cafe"


def test_format_details_rating_without_count() -> None:
    result = _format_details(ProviderPlace(name="Place", rating=4.2))

    assert "Rating: 4.2" in result
    assert "reviews" not in result


# --- place_details_tool ---


async def test_place_details_tool_returns_formatted_string_on_success() -> None:
    with patch(_PATCH_DETAILS, new_callable=AsyncMock) as mock_details:
        mock_details.return_value = _LOUVRE

        result = await place_details_tool.ainvoke({"place_id": "ChIJ123"})

    assert "Louvre Museum" in result
    assert "4.7" in result


async def test_place_details_tool_returns_error_string_on_provider_error() -> None:
    with patch(_PATCH_DETAILS, new_callable=AsyncMock) as mock_details:
        mock_details.side_effect = GooglePlacesError(404, "not found")

        result = await place_details_tool.ainvoke({"place_id": "unknown"})

    assert "unavailable" in result
    assert "not found" in result


async def test_place_details_tool_returns_error_string_on_unexpected_response() -> None:
    with patch(_PATCH_DETAILS, new_callable=AsyncMock) as mock_details:
        mock_details.side_effect = KeyError("displayName")

        result = await place_details_tool.ainvoke({"place_id": "ChIJ123"})

    assert "Unexpected response" in result


# --- place_details_tool ToolResult envelope ---


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "place_details_tool", "args": args, "id": "call_1"}


async def test_place_details_tool_success_envelope_carries_typed_place() -> None:
    with patch(_PATCH_DETAILS, new_callable=AsyncMock) as mock_details:
        mock_details.return_value = _LOUVRE

        message = await place_details_tool.ainvoke(_tool_call({"place_id": "ChIJ123"}))

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "google-places"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert result.data.name == "Louvre Museum"


async def test_place_details_tool_envelope_carries_rich_metadata() -> None:
    with patch(_PATCH_DETAILS, new_callable=AsyncMock) as mock_details:
        mock_details.return_value = _LOUVRE

        message = await place_details_tool.ainvoke(_tool_call({"place_id": "ChIJ123"}))

    place = message.artifact.data
    assert place is not None
    assert place.business_status == "OPERATIONAL"
    assert place.categories == ["museum", "tourist_attraction"]
    assert place.editorial_summary is not None
    assert place.google_maps_url == "https://maps.google.com/?cid=123"


async def test_place_details_tool_error_envelope_is_retryable_on_provider_error() -> None:
    with patch(_PATCH_DETAILS, new_callable=AsyncMock) as mock_details:
        mock_details.side_effect = GooglePlacesError(503, "unavailable")

        message = await place_details_tool.ainvoke(_tool_call({"place_id": "unknown"}))

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "google-places"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True
