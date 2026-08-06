# pyright: reportPrivateUsage=false
from typing import Any
from unittest.mock import AsyncMock

from trip_planner.services.hotels.liteapi_provider import (
    LiteApiHotelProvider,
    _build_rates_request,
    _extract_lowest_total,
    _nights_between,
)
from trip_planner.services.hotels.provider import HotelSearchQuery

_HOTELS_RESPONSE: dict[str, Any] = {
    "data": [
        {
            "id": "lp1",
            "name": "Hotel Le Marais",
            "stars": 4,
            "rating": 8.6,
            "address": "12 Rue de Rivoli",
            "latitude": 48.85,
            "longitude": 2.36,
            "main_photo": "https://example.com/lp1.jpg",
        },
        {
            "id": "lp2",
            "name": "Grand Louvre Hotel",
            "stars": 5,
            "rating": 9.1,
            "address": "5 Rue Saint-Honore",
        },
    ]
}

_RATES_RESPONSE: dict[str, Any] = {
    "data": [
        {
            "hotelId": "lp1",
            "roomTypes": [
                {
                    "rates": [
                        {"retailRate": {"total": [{"amount": 420.0, "currency": "EUR"}]}},
                        {"retailRate": {"total": [{"amount": 380.0, "currency": "EUR"}]}},
                    ]
                }
            ],
        },
        {
            "hotelId": "lp2",
            "roomTypes": [
                {"rates": [{"retailRate": {"total": [{"amount": 960.0, "currency": "EUR"}]}}]}
            ],
        },
    ]
}


def _query() -> HotelSearchQuery:
    return HotelSearchQuery(
        city_name="Paris",
        country_code="FR",
        checkin="2026-07-01",
        checkout="2026-07-05",
        currency="EUR",
    )


def test_nights_between_counts_calendar_nights() -> None:
    assert _nights_between("2026-07-01", "2026-07-05") == 4


def test_nights_between_clamps_to_at_least_one() -> None:
    assert _nights_between("2026-07-05", "2026-07-05") == 1


def test_build_rates_request_includes_dates_occupancy_and_currency() -> None:
    payload = _build_rates_request(_query(), ["lp1", "lp2"])

    assert payload["hotelIds"] == ["lp1", "lp2"]
    assert payload["checkin"] == "2026-07-01"
    assert payload["checkout"] == "2026-07-05"
    assert payload["occupancies"] == [{"adults": 2}]
    assert payload["currency"] == "EUR"


def test_extract_lowest_total_returns_cheapest_rate() -> None:
    amount, currency = _extract_lowest_total(_RATES_RESPONSE["data"][0])

    assert amount == 380.0
    assert currency == "EUR"


def test_extract_lowest_total_returns_none_when_no_rates() -> None:
    amount, currency = _extract_lowest_total({"roomTypes": []})

    assert amount is None
    assert currency is None


async def test_search_maps_hotels_and_nightly_prices() -> None:
    client = AsyncMock()
    client.get.return_value = _HOTELS_RESPONSE
    client.post.return_value = _RATES_RESPONSE
    provider = LiteApiHotelProvider(client=client)

    hotels = await provider.search(_query())

    assert [hotel.name for hotel in hotels] == ["Hotel Le Marais", "Grand Louvre Hotel"]
    first = hotels[0]
    assert first.star_rating == 4
    assert first.review_rating == 8.6
    assert first.total_price == 380.0
    assert first.nightly_price == 95.0  # 380 over 4 nights
    assert first.currency == "EUR"
    assert first.latitude == 48.85
    assert first.photo_url == "https://example.com/lp1.jpg"


async def test_search_maps_missing_photo_to_none() -> None:
    client = AsyncMock()
    client.get.return_value = _HOTELS_RESPONSE
    client.post.return_value = _RATES_RESPONSE
    provider = LiteApiHotelProvider(client=client)

    hotels = await provider.search(_query())

    assert hotels[1].photo_url is None


async def test_search_returns_empty_when_no_hotels() -> None:
    client = AsyncMock()
    client.get.return_value = {"data": []}
    provider = LiteApiHotelProvider(client=client)

    hotels = await provider.search(_query())

    assert hotels == []
    client.post.assert_not_awaited()
