from trip_planner.services.hotels.provider import HotelSearchQuery, ProviderHotel


def _passes_filters(hotel: ProviderHotel, query: HotelSearchQuery) -> bool:
    """Return True when the hotel satisfies the query's price and star constraints."""
    exceeds_budget = (
        query.max_nightly_price is not None
        and hotel.nightly_price is not None
        and hotel.nightly_price > query.max_nightly_price
    )
    if exceeds_budget:
        return False

    below_stars = query.min_star_rating is not None and (
        hotel.star_rating is None or hotel.star_rating < query.min_star_rating
    )
    return not below_stars


def _rank_key(hotel: ProviderHotel) -> tuple[float, float]:
    """Rank cheapest-first (unpriced hotels last), breaking ties by higher rating."""
    price = hotel.nightly_price if hotel.nightly_price is not None else float("inf")
    # Prefer the review score; fall back to star rating so ranking stays deterministic.
    rating = hotel.review_rating if hotel.review_rating is not None else (hotel.star_rating or 0.0)
    return price, -rating


def filter_and_rank_hotels(
    hotels: list[ProviderHotel], query: HotelSearchQuery
) -> list[ProviderHotel]:
    """Drop hotels that violate the query's constraints and rank the rest deterministically.

    Client-side filtering guarantees a follow-up like 'cheaper' or '3-4 star' actually changes
    the results even when the underlying provider ignores those parameters.
    """
    matching: list[ProviderHotel] = []
    for hotel in hotels:
        if _passes_filters(hotel, query):
            matching.append(hotel)

    return sorted(matching, key=_rank_key)
