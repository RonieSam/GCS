"""
Auth router — login, refresh, logout, current user.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.user import LoginRequest, RefreshRequest, Token, UserRead, UserCreate
from app.services.auth_service import authenticate_user, refresh_access_token
from app.services.audit_service import write_audit
from app.services.user_service import create_user
from app.core.enums import UserRole

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Token, summary="Obtain access and refresh tokens")
async def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ip = request.client.host if request.client else None
    user, access_token, refresh_token = await authenticate_user(
        db, body.username, body.password, ip_address=ip
    )
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=UserRead, status_code=201, summary="Register a new civilian user")
async def register(
    request: Request,
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Force role to civilian to prevent privilege escalation via public endpoint
    body.role = UserRole.CIVILIAN
    user = await create_user(db, body)
    
    ip = request.client.host if request.client else None
    await write_audit(
        db, "user.registered", actor=user, entity_type="User", entity_id=user.id,
        ip_address=ip,
    )
    return UserRead.model_validate(user)


@router.post("/refresh", response_model=Token, summary="Refresh access token")
async def refresh(
    body: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    access_token, refresh_token = await refresh_access_token(db, body.refresh_token)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", response_model=SuccessResponse, summary="Logout (client-side token invalidation)")
async def logout(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action="auth.logout",
        actor=current_user,
        entity_type="User",
        entity_id=current_user.id,
        ip_address=ip,
    )
    return SuccessResponse(message="Logged out successfully")


@router.get("/me", response_model=UserRead, summary="Get current authenticated user")
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
