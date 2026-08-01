import uuid
from datetime import datetime, timezone

import pytest

from trip_planner.core.pagination import decode_cursor, encode_cursor


def test_encode_decode_round_trip_preserves_timestamp_and_id() -> None:
    created_at = datetime(2026, 8, 1, 12, 30, 45, tzinfo=timezone.utc)
    item_id = uuid.uuid4()

    decoded_at, decoded_id = decode_cursor(encode_cursor(created_at, item_id))

    assert decoded_at == created_at
    assert decoded_id == item_id


def test_encode_cursor_is_url_safe() -> None:
    cursor = encode_cursor(datetime.now(timezone.utc), uuid.uuid4())

    assert "+" not in cursor
    assert "/" not in cursor


def test_decode_cursor_raises_value_error_for_non_base64() -> None:
    with pytest.raises(ValueError):
        decode_cursor("not a valid cursor!!!")


def test_decode_cursor_raises_value_error_for_missing_id() -> None:
    import base64

    malformed = base64.urlsafe_b64encode(b"2026-08-01T12:00:00+00:00").decode()

    with pytest.raises(ValueError):
        decode_cursor(malformed)


def test_decode_cursor_raises_value_error_for_invalid_uuid() -> None:
    import base64

    malformed = base64.urlsafe_b64encode(b"2026-08-01T12:00:00+00:00|not-a-uuid").decode()

    with pytest.raises(ValueError):
        decode_cursor(malformed)
