# pyright: reportPrivateUsage=false
from typing import Any
from unittest.mock import AsyncMock

from trip_planner.services.places.google_places_provider import (
    GooglePlacesProvider,
    _extract_display_name,
    _extract_editorial_summary,
    _extract_location,
    _extract_photo_reference,
    _to_provider_place,
)
from trip_planner.services.places.provider import NearbyPlacesQuery, PlaceSearchQuery

_RAW_PLACE: dict[str, Any] = {
    "id": "place-1",
    "displayName": {"text": "Eiffel Tower"},
    "formattedAddress": "Champ de Mars, 5 Av. Anatole France, 75007 Paris",
    "location": {"latitude": 48.8584, "longitude": 2.2945},
    "rating": 4.6,
    "userRatingCount": 340000,
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "businessStatus": "OPERATIONAL",
    "types": ["tourist_attraction", "point_of_interest"],
    "regularOpeningHours": {"weekdayDescriptions": ["Monday: 9:00 AM - 11:45 PM"]},
    "websiteUri": "https://www.toureiffel.paris/en",
    "internationalPhoneNumber": "+33 8 92 70 12 39",
    "editorialSummary": {"text": "Iconic 1889 iron lattice tower."},
    "photos": [{"name": "places/place-1/photos/photo-abc"}],
    "googleMapsUri": "https://maps.google.com/?cid=123",
}


def _search_response(places: list[dict[str, Any]]) -> dict[str, Any]:
    return {"places": places}


# --- extraction helpers ---


def test_extract_location_returns_coordinates() -> None:
    assert _extract_location(_RAW_PLACE) == (48.8584, 2.2945)


def test_extract_location_returns_none_when_missing() -> None:
    assert _extract_location({}) == (None, None)


def test_extract_photo_reference_returns_first_photo_name() -> None:
    assert _extract_photo_reference(_RAW_PLACE) == "places/place-1/photos/photo-abc"


def test_extract_photo_reference_returns_none_when_no_photos() -> None:
    assert _extract_photo_reference({"photos": []}) is None


def test_extract_editorial_summary_returns_text() -> None:
    assert _extract_editorial_summary(_RAW_PLACE) == "Iconic 1889 iron lattice tower."


def test_extract_editorial_summary_returns_none_when_missing() -> None:
    assert _extract_editorial_summary({}) is None


def test_extract_display_name_falls_back_when_missing() -> None:
    assert _extract_display_name({}) == "Unknown place"


# --- _to_provider_place ---


def test_to_provider_place_maps_every_field() -> None:
    place = _to_provider_place(_RAW_PLACE)

    assert place.place_id == "place-1"
    assert place.name == "Eiffel Tower"
    assert place.address == "Champ de Mars, 5 Av. Anatole France, 75007 Paris"
    assert place.latitude == 48.8584
    assert place.longitude == 2.2945
    assert place.rating == 4.6
    assert place.user_rating_count == 340000
    assert place.price_level == "PRICE_LEVEL_MODERATE"
    assert place.opening_hours == ["Monday: 9:00 AM - 11:45 PM"]
    assert place.website_url == "https://www.toureiffel.paris/en"
    assert place.phone == "+33 8 92 70 12 39"
    assert place.business_status == "OPERATIONAL"
    assert place.types == ["tourist_attraction", "point_of_interest"]
    assert place.editorial_summary == "Iconic 1889 iron lattice tower."
    assert place.photo_reference == "places/place-1/photos/photo-abc"
    assert place.google_maps_url == "https://maps.google.com/?cid=123"


def test_to_provider_place_handles_sparse_data() -> None:
    place = _to_provider_place({"id": "place-2"})

    assert place.name == "Unknown place"
    assert place.address is None
    assert place.rating is None
    assert place.opening_hours == []


# --- GooglePlacesProvider ---


async def test_search_places_maps_results_and_uses_search_field_mask() -> None:
    client = AsyncMock()
    client.post.return_value = _search_response([_RAW_PLACE])
    provider = GooglePlacesProvider(client=client)

    places = await provider.search_places(PlaceSearchQuery(text_query="Eiffel Tower"))

    assert [place.name for place in places] == ["Eiffel Tower"]
    args, _ = client.post.call_args
    assert args[0] == "/places:searchText"
    assert args[1]["textQuery"] == "Eiffel Tower"


async def test_search_places_returns_empty_when_no_matches() -> None:
    client = AsyncMock()
    client.post.return_value = _search_response([])
    provider = GooglePlacesProvider(client=client)

    places = await provider.search_places(PlaceSearchQuery(text_query="nonexistent place"))

    assert places == []


async def test_nearby_places_sends_location_restriction_and_types() -> None:
    client = AsyncMock()
    client.post.return_value = _search_response([_RAW_PLACE])
    provider = GooglePlacesProvider(client=client)

    places = await provider.nearby_places(
        NearbyPlacesQuery(latitude=48.85, longitude=2.35, radius_m=2000, included_types=["museum"])
    )

    assert [place.name for place in places] == ["Eiffel Tower"]
    args, _ = client.post.call_args
    assert args[0] == "/places:searchNearby"
    assert args[1]["includedTypes"] == ["museum"]
    assert args[1]["locationRestriction"]["circle"]["radius"] == 2000
    assert args[1]["locationRestriction"]["circle"]["center"] == {
        "latitude": 48.85,
        "longitude": 2.35,
    }


async def test_get_place_details_maps_full_details() -> None:
    client = AsyncMock()
    client.get.return_value = _RAW_PLACE
    provider = GooglePlacesProvider(client=client)

    place = await provider.get_place_details("place-1")

    assert place.name == "Eiffel Tower"
    assert place.photo_reference == "places/place-1/photos/photo-abc"
    args, _ = client.get.call_args
    assert args[0] == "/places/place-1"
