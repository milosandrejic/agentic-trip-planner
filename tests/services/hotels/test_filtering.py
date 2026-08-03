from trip_planner.services.hotels.filtering import filter_and_rank_hotels
from trip_planner.services.hotels.provider import HotelSearchQuery, ProviderHotel


def _query(max_nightly_price: float | None = None, min_star_rating: float | None = None) -> HotelSearchQuery:
    return HotelSearchQuery(
        city_name="Paris",
        country_code="FR",
        checkin="2026-07-01",
        checkout="2026-07-05",
        currency="EUR",
        max_nightly_price=max_nightly_price,
        min_star_rating=min_star_rating,
    )


def _hotel(
    name: str,
    nightly_price: float | None = None,
    star_rating: float | None = None,
    review_rating: float | None = None,
) -> ProviderHotel:
    return ProviderHotel(
        hotel_id=name,
        name=name,
        nightly_price=nightly_price,
        star_rating=star_rating,
        review_rating=review_rating,
        currency="EUR",
    )


def test_filter_drops_hotels_above_max_nightly_price() -> None:
    hotels = [_hotel("Cheap", 90.0), _hotel("Pricey", 300.0)]

    result = filter_and_rank_hotels(hotels, _query(max_nightly_price=150.0))

    assert [hotel.name for hotel in result] == ["Cheap"]


def test_filter_drops_hotels_below_min_star_rating() -> None:
    hotels = [_hotel("Budget", 90.0, star_rating=2), _hotel("Boutique", 120.0, star_rating=4)]

    result = filter_and_rank_hotels(hotels, _query(min_star_rating=3))

    assert [hotel.name for hotel in result] == ["Boutique"]


def test_filter_drops_hotels_with_unknown_star_rating_when_min_required() -> None:
    hotels = [_hotel("Unknown", 90.0, star_rating=None), _hotel("Rated", 120.0, star_rating=4)]

    result = filter_and_rank_hotels(hotels, _query(min_star_rating=3))

    assert [hotel.name for hotel in result] == ["Rated"]


def test_ranking_orders_cheapest_first() -> None:
    hotels = [_hotel("Mid", 200.0), _hotel("Low", 100.0), _hotel("High", 300.0)]

    result = filter_and_rank_hotels(hotels, _query())

    assert [hotel.name for hotel in result] == ["Low", "Mid", "High"]


def test_ranking_places_unpriced_hotels_last() -> None:
    hotels = [_hotel("NoPrice", None), _hotel("Priced", 150.0)]

    result = filter_and_rank_hotels(hotels, _query())

    assert [hotel.name for hotel in result] == ["Priced", "NoPrice"]


def test_ranking_breaks_price_ties_by_higher_rating() -> None:
    hotels = [
        _hotel("LowRated", 100.0, review_rating=7.0),
        _hotel("HighRated", 100.0, review_rating=9.0),
    ]

    result = filter_and_rank_hotels(hotels, _query())

    assert [hotel.name for hotel in result] == ["HighRated", "LowRated"]


def test_no_constraints_keeps_all_hotels() -> None:
    hotels = [_hotel("A", 100.0), _hotel("B", 200.0)]

    result = filter_and_rank_hotels(hotels, _query())

    assert len(result) == 2
