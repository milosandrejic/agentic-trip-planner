"""Trip lifecycle state machine: which TripStatus transitions are permitted."""
from trip_planner.models.trip import TripStatus

# Allowed transitions per state. Anything unlisted (including self-transitions) is rejected.
_ALLOWED_TRANSITIONS: dict[TripStatus, frozenset[TripStatus]] = {
    TripStatus.DRAFT: frozenset({TripStatus.GENERATING, TripStatus.ARCHIVED}),
    TripStatus.GENERATING: frozenset({TripStatus.READY, TripStatus.DRAFT}),
    TripStatus.READY: frozenset(
        {TripStatus.GENERATING, TripStatus.COMPLETED, TripStatus.ARCHIVED}
    ),
    TripStatus.COMPLETED: frozenset({TripStatus.ARCHIVED}),
    TripStatus.ARCHIVED: frozenset(),
}


class InvalidTripTransition(Exception):
    """Raised when a trip is moved between two states the lifecycle forbids."""

    def __init__(self, current: TripStatus, target: TripStatus) -> None:
        """Record the rejected (current -> target) pair."""
        self.current = current
        self.target = target
        super().__init__(f"Illegal trip transition: {current.value} -> {target.value}")


def can_transition(current: TripStatus, target: TripStatus) -> bool:
    """Return True when moving from `current` to `target` is allowed."""
    return target in _ALLOWED_TRANSITIONS[current]


def assert_transition(current: TripStatus, target: TripStatus) -> None:
    """Raise InvalidTripTransition when the `current` -> `target` move is forbidden."""
    if not can_transition(current, target):
        raise InvalidTripTransition(current, target)
