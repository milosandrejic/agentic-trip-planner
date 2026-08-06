from difflib import SequenceMatcher

from trip_planner.services.places.provider import ProviderPlace


def _quality_key(place: ProviderPlace) -> tuple[float, float, float]:
    """Higher is better: operational status, rating, review count."""
    is_operational = place.business_status is None or place.business_status == "OPERATIONAL"
    rating = place.rating or 0.0
    review_count = float(place.user_rating_count or 0)
    return (1.0 if is_operational else 0.0), rating, review_count


def rank_by_quality(places: list[ProviderPlace]) -> list[ProviderPlace]:
    """Rank places by confidence signals alone: business status, rating, review count.

    Used for category-based discovery, where there is no name to match against.
    """
    return sorted(places, key=_quality_key, reverse=True)


def rank_by_name_match(places: list[ProviderPlace], query: str) -> list[ProviderPlace]:
    """Rank places by how well their name matches a free-text query, then by quality signals.

    Google Places Text Search does not guarantee the best match is returned first, so a named
    lookup re-ranks candidates to put the highest-confidence match first instead of trusting the
    provider's default ordering.
    """

    def _key(place: ProviderPlace) -> tuple[float, float, float, float]:
        name_score = SequenceMatcher(None, place.name.lower(), query.lower()).ratio()
        return (name_score, *_quality_key(place))

    return sorted(places, key=_key, reverse=True)
