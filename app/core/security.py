"""Authentication: password hashing and JWT.

bcrypt for passwords, HS256 for tokens. Both are boring on purpose -- the
interesting security work in this app is input handling and rate limiting, and
rolling your own crypto is how you lose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt has a 72-byte input limit and passlib raises on longer passwords rather
# than silently truncating. We truncate explicitly in ``hash_password`` so a long
# passphrase works instead of erroring, and we do the same on verify so the two
# always agree.
_BCRYPT_MAX_BYTES = 72

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _prepare(password: str) -> bytes:
    """Encode and truncate to bcrypt's limit, on a character boundary."""
    raw = password.encode("utf-8")
    if len(raw) <= _BCRYPT_MAX_BYTES:
        return raw
    # Truncate by characters, not bytes, so we never split a multi-byte sequence.
    out = ""
    for ch in password:
        if len((out + ch).encode("utf-8")) > _BCRYPT_MAX_BYTES:
            break
        out += ch
    return out.encode("utf-8")


def hash_password(password: str) -> str:
    return _pwd_context.hash(_prepare(password))


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(_prepare(plain), hashed)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, *, expires_minutes: int | None = None) -> str:
    """Issue a signed token for ``subject`` (the user id)."""
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """Return the claims, or None if the token is invalid or expired."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    if payload.get("typ") != "access":
        return None
    if not payload.get("sub"):
        return None
    return payload


__all__ = [
    "create_access_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
