import base64
import binascii
import uuid
from datetime import datetime


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    """Encode a (timestamp, id) pair into an opaque, URL-safe keyset cursor."""
    raw = f"{created_at.isoformat()}|{item_id}"

    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode an opaque keyset cursor back into its (timestamp, id) pair.

    Raises ValueError when the cursor is malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp_part, id_part = raw.split("|", 1)

        return datetime.fromisoformat(timestamp_part), uuid.UUID(id_part)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
