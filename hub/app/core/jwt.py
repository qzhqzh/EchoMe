"""JWT token utilities: issue and verify tokens."""

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(
    user_id: uuid.UUID,
    username: str,
    role: str,
) -> tuple[str, int]:
    """Create a JWT access token.

    Returns:
        Tuple of (token_string, expires_in_seconds).
    """
    expires_delta = timedelta(days=settings.jwt_expire_days)
    expire = datetime.now(timezone.utc) + expires_delta
    expires_in = int(expires_delta.total_seconds())

    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict | None:
    """Decode and verify a JWT token.

    Returns:
        The token payload dict if valid, None otherwise.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
