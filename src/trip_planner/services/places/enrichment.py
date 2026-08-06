import asyncio

from trip_planner.schemas.trips import Activity
from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places.provider import PlaceProvider, PlaceSearchQuery, ProviderPlace


def _is_missing_key_fields(activity: Activity) -> bool:
    """True when a field a follow-up place lookup could fill in is still null."""
    return (
        activity.place_id is None
        or activity.latitude is None
        or activity.longitude is None
        or activity.address is None
        or activity.rating is None
        or activity.photo_url is None
    )


def _photo_url(photo_reference: str | None) -> str | None:
    """Build the backend redirect URL for a Google photo reference, if one was returned."""
    if not photo_reference:
        return None
    return f"/places/photos/{photo_reference}"


def _merge_place_metadata(activity: Activity, place: ProviderPlace) -> Activity:
    """Fill only the activity's still-missing fields from a resolved place; never overwrite."""
    return activity.model_copy(
        update={
            "place_id": activity.place_id or place.place_id,
            "latitude": activity.latitude if activity.latitude is not None else place.latitude,
            "longitude": activity.longitude if activity.longitude is not None else place.longitude,
            "address": activity.address or place.address,
            "rating": activity.rating if activity.rating is not None else place.rating,
            "user_rating_count": (
                activity.user_rating_count
                if activity.user_rating_count is not None
                else place.user_rating_count
            ),
            "opening_hours": activity.opening_hours or place.opening_hours,
            "price_level": activity.price_level or place.price_level,
            "website_url": activity.website_url or place.website_url,
            "phone": activity.phone or place.phone,
            "business_status": activity.business_status or place.business_status,
            "categories": activity.categories or place.types,
            "editorial_summary": activity.editorial_summary or place.editorial_summary,
            "google_maps_url": activity.google_maps_url or place.google_maps_url,
            "photo_url": activity.photo_url or _photo_url(place.photo_reference),
        }
    )


async def _enrich_activity(
    activity: Activity, destination: str, provider: PlaceProvider
) -> Activity:
    """Give one activity a single best-effort lookup to fill in missing place metadata.

    Reuses an already-known place_id when the formatter provided one; otherwise resolves it
    with a text search first. Either way, only one details call is made per activity, mirroring
    how find_place_by_name_tool + place_details_tool are meant to be chained by the reasoner, but
    automatic and silent on failure since this is a best-effort backfill, not a user-facing call.
    """
    if not _is_missing_key_fields(activity):
        return activity

    place_id = activity.place_id

    if place_id is None:
        query = PlaceSearchQuery(text_query=f"{activity.description} in {destination}", max_results=1)
        try:
            candidates = await provider.search_places(query)
        except (GooglePlacesError, KeyError, TypeError, ValueError):
            return activity

        if not candidates:
            return activity

        candidate = candidates[0]
        place_id = candidate.place_id
        if place_id is None:
            return _merge_place_metadata(activity, candidate)

    try:
        details = await provider.get_place_details(place_id)
    except (GooglePlacesError, KeyError, TypeError, ValueError):
        return activity

    return _merge_place_metadata(activity, details)


async def enrich_activities(
    activities: list[Activity], destination: str, provider: PlaceProvider
) -> list[Activity]:
    """Backfill missing place metadata for every activity that needs it, one attempt each.

    Runs concurrently so a day with several incomplete activities costs one round of latency
    instead of one lookup after another.
    """
    return list(
        await asyncio.gather(
            *(_enrich_activity(activity, destination, provider) for activity in activities)
        )
    )
