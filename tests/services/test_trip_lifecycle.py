import pytest

from trip_planner.models.trip import TripStatus
from trip_planner.services.trip_lifecycle import (
    InvalidTripTransition,
    assert_transition,
    can_transition,
)

_ALLOWED = [
    (TripStatus.DRAFT, TripStatus.GENERATING),
    (TripStatus.DRAFT, TripStatus.ARCHIVED),
    (TripStatus.GENERATING, TripStatus.READY),
    (TripStatus.GENERATING, TripStatus.DRAFT),
    (TripStatus.READY, TripStatus.GENERATING),
    (TripStatus.READY, TripStatus.COMPLETED),
    (TripStatus.READY, TripStatus.ARCHIVED),
    (TripStatus.COMPLETED, TripStatus.ARCHIVED),
]

_FORBIDDEN = [
    (TripStatus.DRAFT, TripStatus.READY),
    (TripStatus.DRAFT, TripStatus.COMPLETED),
    (TripStatus.GENERATING, TripStatus.COMPLETED),
    (TripStatus.GENERATING, TripStatus.ARCHIVED),
    (TripStatus.READY, TripStatus.DRAFT),
    (TripStatus.COMPLETED, TripStatus.READY),
    (TripStatus.COMPLETED, TripStatus.GENERATING),
    (TripStatus.ARCHIVED, TripStatus.DRAFT),
    (TripStatus.ARCHIVED, TripStatus.READY),
    # self-transitions are not real transitions
    (TripStatus.DRAFT, TripStatus.DRAFT),
    (TripStatus.READY, TripStatus.READY),
    (TripStatus.ARCHIVED, TripStatus.ARCHIVED),
]


@pytest.mark.parametrize(("current", "target"), _ALLOWED)
def test_can_transition_allows_valid_moves(current: TripStatus, target: TripStatus) -> None:
    assert can_transition(current, target) is True


@pytest.mark.parametrize(("current", "target"), _FORBIDDEN)
def test_can_transition_rejects_invalid_moves(current: TripStatus, target: TripStatus) -> None:
    assert can_transition(current, target) is False


@pytest.mark.parametrize(("current", "target"), _ALLOWED)
def test_assert_transition_passes_for_valid_moves(current: TripStatus, target: TripStatus) -> None:
    assert_transition(current, target)


@pytest.mark.parametrize(("current", "target"), _FORBIDDEN)
def test_assert_transition_raises_for_invalid_moves(current: TripStatus, target: TripStatus) -> None:
    with pytest.raises(InvalidTripTransition) as exc_info:
        assert_transition(current, target)

    assert exc_info.value.current == current
    assert exc_info.value.target == target


def test_archived_is_terminal() -> None:
    for target in TripStatus:
        assert can_transition(TripStatus.ARCHIVED, target) is False
