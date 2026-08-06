from unittest.mock import AsyncMock, MagicMock

from trip_planner.schemas.trips import Activity
from trip_planner.services.google_places_client import GooglePlacesError
from trip_planner.services.places.enrichment import enrich_activities
from trip_planner.services.places.provider import PlaceProvider, ProviderPlace


def _activity(**overrides: object) -> Activity:
    defaults: dict[str, object] = {"time": "Morning", "description": "Visit the Eiffel Tower"}
    defaults.update(overrides)
    return Activity(**defaults)  # type: ignore[arg-type]


def _complete_activity() -> Activity:
    return _activity(
        place_id="place-1",
        latitude=48.8,
        longitude=2.3,
        address="Champ de Mars, Paris",
        rating=4.7,
        photo_url="/places/photos/existing",
    )


def _provider_place(**overrides: object) -> ProviderPlace:
    defaults: dict[str, object] = {"name": "Eiffel Tower"}
    defaults.update(overrides)
    return ProviderPlace(**defaults)  # type: ignore[arg-type]


def _make_provider(
    search_results: list[ProviderPlace] | Exception | None = None,
    details_result: ProviderPlace | Exception | None = None,
) -> MagicMock:
    provider = MagicMock(spec=PlaceProvider)

    if isinstance(search_results, Exception):
        provider.search_places = AsyncMock(side_effect=search_results)
    else:
        provider.search_places = AsyncMock(return_value=search_results or [])

    if isinstance(details_result, Exception):
        provider.get_place_details = AsyncMock(side_effect=details_result)
    else:
        provider.get_place_details = AsyncMock(return_value=details_result)

    return provider


# --- enrich_activities: nothing to do ---


async def test_leaves_complete_activity_untouched_and_skips_provider_calls() -> None:
    activity = _complete_activity()
    provider = _make_provider()

    result = await enrich_activities([activity], "Paris", provider)

    assert result == [activity]
    provider.search_places.assert_not_awaited()
    provider.get_place_details.assert_not_awaited()


# --- enrich_activities: resolving an unknown place ---


async def test_resolves_place_id_via_search_then_fills_details() -> None:
    activity = _activity()
    found = _provider_place(place_id="place-1")
    details = _provider_place(
        place_id="place-1",
        latitude=48.8584,
        longitude=2.2945,
        address="Champ de Mars, 5 Av. Anatole France, Paris",
        rating=4.7,
        user_rating_count=300000,
        opening_hours=["Monday: 9AM-11PM"],
        website_url="https://www.toureiffel.paris",
        phone="+33 892 70 12 39",
        business_status="OPERATIONAL",
        types=["tourist_attraction"],
        editorial_summary="Iconic iron lattice tower.",
        photo_reference="places/place-1/photos/photo-1",
        google_maps_url="https://maps.google.com/?cid=1",
    )
    provider = _make_provider(search_results=[found], details_result=details)

    result = await enrich_activities([activity], "Paris", provider)

    enriched = result[0]
    provider.search_places.assert_awaited_once()
    provider.get_place_details.assert_awaited_once_with("place-1")
    assert enriched.place_id == "place-1"
    assert enriched.latitude == 48.8584
    assert enriched.longitude == 2.2945
    assert enriched.address == "Champ de Mars, 5 Av. Anatole France, Paris"
    assert enriched.rating == 4.7
    assert enriched.user_rating_count == 300000
    assert enriched.opening_hours == ["Monday: 9AM-11PM"]
    assert enriched.website_url == "https://www.toureiffel.paris"
    assert enriched.phone == "+33 892 70 12 39"
    assert enriched.business_status == "OPERATIONAL"
    assert enriched.categories == ["tourist_attraction"]
    assert enriched.editorial_summary == "Iconic iron lattice tower."
    assert enriched.google_maps_url == "https://maps.google.com/?cid=1"
    assert enriched.photo_url == "/places/photos/places/place-1/photos/photo-1"


async def test_reuses_existing_place_id_instead_of_searching() -> None:
    activity = _activity(place_id="place-1")
    details = _provider_place(place_id="place-1", rating=4.7, photo_reference="ref-1")
    provider = _make_provider(details_result=details)

    result = await enrich_activities([activity], "Paris", provider)

    provider.search_places.assert_not_awaited()
    provider.get_place_details.assert_awaited_once_with("place-1")
    assert result[0].rating == 4.7
    assert result[0].photo_url == "/places/photos/ref-1"


async def test_never_overwrites_fields_the_formatter_already_set() -> None:
    activity = _activity(rating=3.0, address="Original address")
    details = _provider_place(
        place_id="place-1", rating=5.0, address="Different address", photo_reference="ref-1"
    )
    provider = _make_provider(search_results=[_provider_place(place_id="place-1")], details_result=details)

    result = await enrich_activities([activity], "Paris", provider)

    assert result[0].rating == 3.0
    assert result[0].address == "Original address"
    assert result[0].photo_url == "/places/photos/ref-1"


# --- enrich_activities: no match / failures are silent ---


async def test_returns_activity_unchanged_when_search_finds_no_candidates() -> None:
    activity = _activity()
    provider = _make_provider(search_results=[])

    result = await enrich_activities([activity], "Paris", provider)

    assert result == [activity]
    provider.get_place_details.assert_not_awaited()


async def test_merges_search_result_when_candidate_has_no_place_id() -> None:
    activity = _activity()
    found = _provider_place(rating=4.2)  # no place_id, so no details lookup is possible
    provider = _make_provider(search_results=[found])

    result = await enrich_activities([activity], "Paris", provider)

    assert result[0].rating == 4.2
    provider.get_place_details.assert_not_awaited()


async def test_returns_activity_unchanged_when_search_raises_google_places_error() -> None:
    activity = _activity()
    provider = _make_provider(search_results=GooglePlacesError(500, "boom"))

    result = await enrich_activities([activity], "Paris", provider)

    assert result == [activity]


async def test_returns_activity_unchanged_when_details_raises_google_places_error() -> None:
    activity = _activity(place_id="place-1")
    provider = _make_provider(details_result=GooglePlacesError(500, "boom"))

    result = await enrich_activities([activity], "Paris", provider)

    assert result == [activity]


async def test_returns_activity_unchanged_when_search_raises_value_error() -> None:
    activity = _activity()
    provider = _make_provider(search_results=ValueError("bad response"))

    result = await enrich_activities([activity], "Paris", provider)

    assert result == [activity]


# --- enrich_activities: batching ---


async def test_enriches_multiple_activities_concurrently() -> None:
    activities = [_activity(description="A"), _complete_activity(), _activity(description="C")]
    details = _provider_place(place_id="place-1", rating=4.0, photo_reference="ref-1")
    provider = _make_provider(search_results=[_provider_place(place_id="place-1")], details_result=details)

    result = await enrich_activities(activities, "Paris", provider)

    assert len(result) == 3
    assert result[1] == activities[1]
    assert provider.search_places.await_count == 2
    assert provider.get_place_details.await_count == 2
