"""
Auth service — login, token refresh, logout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import User
from app.services.audit_service import write_audit
from app.services.user_service import get_user_by_username

settings = get_settings()


async def authenticate_user(
    session: AsyncSession,
    username: str,
    password: str,
    ip_address: Optional[str] = None,
) -> tuple[User, str, str]:
    """
    Verify credentials and return (user, access_token, refresh_token).
    Raises AuthenticationError on failure.
    """
    user = await get_user_by_username(session, username)
    if not user:
        raise AuthenticationError("Invalid username or password")
    if not user.is_active:
        raise AuthenticationError("Account is disabled")
    if not verify_password(password, user.hashed_password):
        raise AuthenticationError("Invalid username or password")

    access_token = create_access_token(
        subject=user.username,
        extra_claims={"role": user.role.value, "uid": user.id},
    )
    refresh_token = create_refresh_token(subject=user.username)

    await write_audit(
        session,
        action="auth.login",
        actor=user,
        entity_type="User",
        entity_id=user.id,
        ip_address=ip_address,
    )

    return user, access_token, refresh_token


async def refresh_access_token(
    session: AsyncSession,
    refresh_token: str,
) -> tuple[str, str]:
    """
    Validate a refresh token and issue a new access + refresh token pair.
    """
    from jose import JWTError

    try:
        payload = decode_token(refresh_token)
    except JWTError:
        raise AuthenticationError("Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise AuthenticationError("Invalid token type")

    username: Optional[str] = payload.get("sub")
    if not username:
        raise AuthenticationError("Invalid token payload")

    user = await get_user_by_username(session, username)
    if not user or not user.is_active:
        raise AuthenticationError("User not found or disabled")

    new_access = create_access_token(
        subject=user.username,
        extra_claims={"role": user.role.value, "uid": user.id},
    )
    new_refresh = create_refresh_token(subject=user.username)
    return new_access, new_refresh
