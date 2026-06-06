from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from trip_planner.config import get_settings

_settings = get_settings()


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())

    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored bcrypt hash."""
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")

    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(subject: str) -> str:
    """Create a signed JWT for the given subject (user id as string).

    Token expires after jwt_expire_hours as configured in settings.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=_settings.jwt_expire_hours)

    payload = {
        "sub": subject,
        "exp": expire,
    }

    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Decode and validate a JWT. Returns the subject (user id).

    Raises jwt.InvalidTokenError on expiry, bad signature, or malformed token.
    Callers are responsible for catching and converting to HTTP 401.
    """
    payload: dict[str, str] = jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])

    return payload["sub"]
