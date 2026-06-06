from datetime import datetime, timedelta, timezone

import jwt
import pytest

from trip_planner.config import get_settings
from trip_planner.services.auth_service import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

_settings = get_settings()


def test_hash_password_returns_bcrypt_hash() -> None:
    hashed = hash_password("secret123")

    assert hashed != "secret123"
    assert hashed.startswith("$2b$")


def test_hash_password_produces_unique_hashes_for_same_input() -> None:
    first = hash_password("secret123")
    second = hash_password("secret123")

    assert first != second


def test_verify_password_returns_true_for_correct_password() -> None:
    hashed = hash_password("secret123")

    assert verify_password("secret123", hashed) is True


def test_verify_password_returns_false_for_wrong_password() -> None:
    hashed = hash_password("secret123")

    assert verify_password("wrong_password", hashed) is False


def test_create_access_token_returns_decodable_jwt() -> None:
    subject = "user-id-123"

    token = create_access_token(subject)

    assert isinstance(token, str)
    assert len(token) > 0


def test_create_access_token_contains_correct_subject() -> None:
    subject = "user-id-123"

    token = create_access_token(subject)
    decoded = decode_access_token(token)

    assert decoded == subject


def test_decode_access_token_raises_on_expired_token() -> None:
    # Build an already-expired token directly, signed with the real secret
    payload = {
        "sub": "user-id-123",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)


def test_decode_access_token_raises_on_invalid_signature() -> None:
    subject = "user-id-123"
    token = create_access_token(subject)

    tampered_token = token[:-5] + "XXXXX"

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered_token)


def test_decode_access_token_raises_on_malformed_token() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not.a.valid.jwt")
