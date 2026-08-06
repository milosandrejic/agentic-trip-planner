# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from typing import Any

from trip_planner.services.google_places_client import GooglePlacesClient
from trip_planner.services.places.provider import (
    NearbyPlacesQuery,
    PlaceSearchQuery,
    ProviderPlace,
)

# Search/nearby results stay lean (no photos/opening-hours/editorial-summary) since those are
# billed as a pricier Places SKU; the full mask is reserved for get_place_details, called only
# for the candidate a caller has already ranked as the best match.
_SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,places.rating,"
    "places.userRatingCount,places.priceLevel,places.businessStatus,places.types"
)
_DETAILS_FIELD_MASK = (
    "id,displayName,formattedAddress,location,rating,userRatingCount,priceLevel,"
    "businessStatus,types,regularOpeningHours.weekdayDescriptions,websiteUri,"
    "internationalPhoneNumber,editorialSummary,photos,googleMapsUri"
)


def _extract_location(place: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return the (latitude, longitude) Google reported for a place, or (None, None)."""
    location: dict[str, Any] = place.get("location", {})
    return location.get("latitude"), location.get("longitude")


def _extract_photo_reference(place: dict[str, Any]) -> str | None:
    """Return the resource name of the place's first photo, if Google returned any."""
    photos: list[dict[str, Any]] = place.get("photos", [])
    if not photos:
        return None
    return photos[0].get("name") or None


def _extract_editorial_summary(place: dict[str, Any]) -> str | None:
    """Return Google's editorial summary text for a place, if it provided one."""
    editorial: dict[str, Any] = place.get("editorialSummary", {})
    return editorial.get("text") or None


def _extract_display_name(place: dict[str, Any]) -> str:
    """Return the place's display name, falling back when Google omits it."""
    display_name: dict[str, Any] = place.get("displayName", {})
    return display_name.get("text") or "Unknown place"


def _to_provider_place(place: dict[str, Any]) -> ProviderPlace:
    """Map one raw Google Places (New) place object into a normalised ProviderPlace."""
    latitude, longitude = _extract_location(place)
    opening_hours: dict[str, Any] = place.get("regularOpeningHours", {})

    return ProviderPlace(
        place_id=place.get("id") or None,
        name=_extract_display_name(place),
        address=place.get("formattedAddress") or None,
        latitude=latitude,
        longitude=longitude,
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
        price_level=place.get("priceLevel") or None,
        opening_hours=opening_hours.get("weekdayDescriptions", []),
        website_url=place.get("websiteUri") or None,
        phone=place.get("internationalPhoneNumber") or None,
        business_status=place.get("businessStatus") or None,
        types=place.get("types", []),
        editorial_summary=_extract_editorial_summary(place),
        photo_reference=_extract_photo_reference(place),
        google_maps_url=place.get("googleMapsUri") or None,
    )


class GooglePlacesProvider:
    """Google Places (New)-backed implementation of the PlaceProvider protocol."""

    def __init__(self, client: GooglePlacesClient | None = None) -> None:
        """Initialise with an optional injected Google Places client for testing."""
        self._client = client or GooglePlacesClient()

    async def search_places(self, query: PlaceSearchQuery) -> list[ProviderPlace]:
        """Text-search Google Places and normalise the matches to ProviderPlace."""
        body: dict[str, Any] = {
            "textQuery": query.text_query,
            "maxResultCount": query.max_results,
        }
        response = await self._client.post("/places:searchText", body, _SEARCH_FIELD_MASK)
        places: list[dict[str, Any]] = response.get("places", [])
        return [_to_provider_place(place) for place in places]

    async def nearby_places(self, query: NearbyPlacesQuery) -> list[ProviderPlace]:
        """Search Google Places for the given types near a coordinate."""
        body: dict[str, Any] = {
            "includedTypes": query.included_types,
            "maxResultCount": query.max_results,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": query.latitude, "longitude": query.longitude},
                    "radius": query.radius_m,
                }
            },
        }
        response = await self._client.post("/places:searchNearby", body, _SEARCH_FIELD_MASK)
        places: list[dict[str, Any]] = response.get("places", [])
        return [_to_provider_place(place) for place in places]

    async def get_place_details(self, place_id: str) -> ProviderPlace:
        """Fetch full Google Place details and normalise them to a ProviderPlace."""
        place = await self._client.get(f"/places/{place_id}", _DETAILS_FIELD_MASK)
        return _to_provider_place(place)
