"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(message: str = "Not authenticated.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    """Resolve the bearer token to a user, or raise 401."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("A bearer token is required.")

    claims = decode_token(credentials.credentials)
    if claims is None:
        raise _unauthorized("That token is invalid or has expired.")

    user = db.get(User, claims["sub"])
    if user is None:
        raise _unauthorized("That account no longer exists.")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "inactive", "message": "This account is disabled."},
        )
    return user


def get_optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User | None:
    """Like :func:`get_current_user` but returns None instead of raising.

    Used by the translate endpoint, which works anonymously but saves history
    when the caller is signed in.
    """
    if credentials is None or not credentials.credentials:
        return None
    claims = decode_token(credentials.credentials)
    if claims is None:
        return None
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        return None
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


__all__ = [
    "CurrentUser",
    "DbSession",
    "OptionalUser",
    "get_current_user",
    "get_optional_user",
]
