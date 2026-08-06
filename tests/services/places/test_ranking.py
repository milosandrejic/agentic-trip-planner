from trip_planner.services.places.provider import ProviderPlace
from trip_planner.services.places.ranking import rank_by_name_match, rank_by_quality


def _place(
    name: str,
    rating: float | None = None,
    user_rating_count: int | None = None,
    business_status: str | None = None,
) -> ProviderPlace:
    return ProviderPlace(
        name=name,
        rating=rating,
        user_rating_count=user_rating_count,
        business_status=business_status,
    )


# --- rank_by_quality ---


def test_rank_by_quality_orders_highest_rating_first() -> None:
    places = [_place("Low", rating=3.5), _place("High", rating=4.8)]

    result = rank_by_quality(places)

    assert [place.name for place in result] == ["High", "Low"]


def test_rank_by_quality_breaks_rating_ties_by_review_count() -> None:
    places = [
        _place("FewReviews", rating=4.5, user_rating_count=10),
        _place("ManyReviews", rating=4.5, user_rating_count=5000),
    ]

    result = rank_by_quality(places)

    assert [place.name for place in result] == ["ManyReviews", "FewReviews"]


def test_rank_by_quality_deprioritises_non_operational_places() -> None:
    places = [
        _place("Closed", rating=4.9, business_status="CLOSED_PERMANENTLY"),
        _place("Open", rating=3.5, business_status="OPERATIONAL"),
    ]

    result = rank_by_quality(places)

    assert [place.name for place in result] == ["Open", "Closed"]


def test_rank_by_quality_treats_missing_business_status_as_operational() -> None:
    places = [_place("Unknown", rating=4.0, business_status=None), _place("Closed", rating=4.9, business_status="CLOSED_TEMPORARILY")]

    result = rank_by_quality(places)

    assert [place.name for place in result] == ["Unknown", "Closed"]


# --- rank_by_name_match ---


def test_rank_by_name_match_orders_exact_match_first() -> None:
    places = [
        _place("Eiffel Tower Restaurant", rating=4.0),
        _place("Eiffel Tower", rating=3.0),
    ]

    result = rank_by_name_match(places, "Eiffel Tower")

    assert result[0].name == "Eiffel Tower"


def test_rank_by_name_match_breaks_ties_by_quality() -> None:
    places = [
        _place("Louvre Museum", rating=3.0, user_rating_count=10),
        _place("Louvre Museum", rating=4.5, user_rating_count=500),
    ]

    result = rank_by_name_match(places, "Louvre Museum")

    assert result[0].rating == 4.5
