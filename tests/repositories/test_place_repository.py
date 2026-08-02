import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from trip_planner.models.place import Place
from trip_planner.repositories import place_repository
from trip_planner.services.types import PlaceResult

_PROVIDER = "google_places"


def make_place_result(place_id: str | None = "gp_123") -> PlaceResult:
    """Return a fully populated PlaceResult for normalization tests."""
    return PlaceResult(
        name="Louvre Museum",
        place_id=place_id,
        categories=["museum", "tourist_attraction"],
        address="Rue de Rivoli, Paris",
        latitude=48.8606,
        longitude=2.3376,
        rating=4.7,
        user_rating_count=1000,
        price_level="PRICE_LEVEL_MODERATE",
        opening_hours=["Mon 09:00-18:00"],
        website_url="https://louvre.fr",
        phone="+33 1 40 20 50 50",
    )


def make_db() -> AsyncMock:
    """Return a fresh AsyncMock that mimics AsyncSession."""
    db = AsyncMock()
    # add() is synchronous on AsyncSession; prevent coroutine-never-awaited warnings
    db.add = MagicMock()
    return db


def _found(place: Place | None) -> MagicMock:
    """Build a mock execute() result whose scalar_one_or_none() returns place."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = place
    return result


# --- insert path ---


async def test_upsert_inserts_new_place_when_absent() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    await place_repository.upsert_place(db, _PROVIDER, make_place_result())

    added: Place = db.add.call_args[0][0]
    assert added.provider == _PROVIDER
    assert added.external_id == "gp_123"
    assert added.name == "Louvre Museum"
    assert added.latitude == 48.8606
    assert added.longitude == 2.3376
    assert added.address == "Rue de Rivoli, Paris"


async def test_upsert_folds_non_core_fields_into_metadata() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    await place_repository.upsert_place(db, _PROVIDER, make_place_result())

    added: Place = db.add.call_args[0][0]
    assert added.place_metadata["rating"] == 4.7
    assert added.place_metadata["categories"] == ["museum", "tourist_attraction"]
    assert added.place_metadata["price_level"] == "PRICE_LEVEL_MODERATE"
    assert added.place_metadata["opening_hours"] == ["Mon 09:00-18:00"]
    assert "name" not in added.place_metadata


async def test_upsert_insert_calls_flush_and_refresh() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    await place_repository.upsert_place(db, _PROVIDER, make_place_result())

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


# --- update / dedupe path ---


async def test_upsert_updates_existing_place_without_inserting() -> None:
    db = make_db()
    existing = Place(
        provider=_PROVIDER,
        external_id="gp_123",
        name="Old Name",
        place_metadata={},
    )
    existing.id = uuid.uuid4()
    db.execute.return_value = _found(existing)

    result = await place_repository.upsert_place(db, _PROVIDER, make_place_result())

    assert result is existing
    assert existing.name == "Louvre Museum"
    assert existing.place_metadata["rating"] == 4.7
    db.add.assert_not_called()


async def test_upsert_update_calls_flush_and_refresh() -> None:
    db = make_db()
    existing = Place(provider=_PROVIDER, external_id="gp_123", name="Old", place_metadata={})
    db.execute.return_value = _found(existing)

    await place_repository.upsert_place(db, _PROVIDER, make_place_result())

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


async def test_upsert_dedupes_by_provider_and_external_id() -> None:
    db = make_db()
    db.execute.return_value = _found(None)

    await place_repository.upsert_place(db, _PROVIDER, make_place_result())

    compiled = str(db.execute.call_args[0][0])
    assert "places.provider =" in compiled
    assert "places.external_id =" in compiled


# --- validation ---


async def test_upsert_raises_when_place_id_missing() -> None:
    db = make_db()

    with pytest.raises(ValueError, match="place_id"):
        await place_repository.upsert_place(db, _PROVIDER, make_place_result(place_id=None))

    db.add.assert_not_called()
