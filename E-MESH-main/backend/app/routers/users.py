"""
Users router — CRUD for user management (admin operations).
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_roles
from app.core.enums import UserRole
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.audit_service import write_audit
from app.services.user_service import (
    create_user,
    deactivate_user,
    get_user_by_id,
    list_users,
    update_user,
)

router = APIRouter(prefix="/users", tags=["Users"])

_admin_only = require_roles(UserRole.ADMIN)
_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)


@router.get("", response_model=PaginatedResponse[UserRead], summary="List users")
async def list_users_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(_managers)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[UserRole] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    users, total = await list_users(db, page, page_size, role, search, is_active)
    return PaginatedResponse(
        data=[UserRead.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=UserRead, status_code=201, summary="Create a new user")
async def create_user_endpoint(
    request: Request,
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_admin_only)],
):
    user = await create_user(db, body)
    await write_audit(
        db, "user.created", actor=actor, entity_type="User", entity_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead, summary="Get a user by ID")
async def get_user_endpoint(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(_managers)],
):
    user = await get_user_by_id(db, user_id)
    if not user:
        raise NotFoundError("User", user_id)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead, summary="Update a user")
async def update_user_endpoint(
    request: Request,
    user_id: str,
    body: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_admin_only)],
):
    user = await update_user(db, user_id, body)
    await write_audit(
        db, "user.updated", actor=actor, entity_type="User", entity_id=user_id,
        metadata=body.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )
    return UserRead.model_validate(user)


@router.delete("/{user_id}", response_model=SuccessResponse, summary="Deactivate a user")
async def deactivate_user_endpoint(
    request: Request,
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_admin_only)],
):
    await deactivate_user(db, user_id)
    await write_audit(
        db, "user.deactivated", actor=actor, entity_type="User", entity_id=user_id,
        ip_address=request.client.host if request.client else None,
    )
    return SuccessResponse(message="User deactivated")
