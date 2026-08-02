"""SQLAlchemy ORM models. Import models here so Alembic autogenerate sees them."""

from trip_planner.core.database import Base
from trip_planner.models.itinerary_version import ItineraryVersion
from trip_planner.models.message import Message
from trip_planner.models.place import Place
from trip_planner.models.selected_flight import SelectedFlight
from trip_planner.models.selected_hotel import SelectedHotel
from trip_planner.models.thread import Thread
from trip_planner.models.trip import Trip
from trip_planner.models.user import User

__all__ = [
    "Base",
    "ItineraryVersion",
    "Message",
    "Place",
    "SelectedFlight",
    "SelectedHotel",
    "Thread",
    "Trip",
    "User",
]
