"""
FastAPI dependency injectors — database session, current user, RBAC.
"""
from __future__ import annotations

from typing import Annotated, List

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_token
from app.db.base import get_async_session

settings = get_settings()

_bearer = HTTPBearer(auto_error=False)


# ── Database ──────────────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:
    """Yield an async SQLAlchemy session, rolling back on error."""
    async for session in get_async_session():
        yield session


# ── Auth ──────────────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Extract and validate the JWT bearer token.
    Returns the User ORM object for the authenticated user.
    """
    from app.services.user_service import get_user_by_username

    if credentials is None:
        raise AuthenticationError("No authentication token provided")

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise AuthenticationError("Invalid or expired token")

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")

    username: str | None = payload.get("sub")
    if not username:
        raise AuthenticationError("Invalid token payload")

    user = await get_user_by_username(db, username)
    if user is None:
        raise AuthenticationError("User not found")
    if not user.is_active:
        raise AuthenticationError("Account is disabled")

    return user


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Like get_current_user but returns None when no credentials are provided or token is invalid.
    Useful for endpoints that are public but optionally authenticated.
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except Exception:
        return None



def require_roles(*roles: str):
    """
    Dependency factory: inject a guard that raises 403 if the current
    user's role is not in the allowed list.

    Usage:
        @router.get("/admin-only")
        async def admin(user=Depends(require_roles("ADMIN")))
    """
    async def _guard(current_user=Depends(get_current_user)):
        if current_user.role not in roles:
            raise AuthorizationError(
                f"This action requires one of: {', '.join(roles)}"
            )
        return current_user

    return _guard
