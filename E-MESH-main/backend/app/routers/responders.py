"""
Responders router — endpoints for field responder profiles, teams, and status management.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_roles
from app.core.enums import ResponderStatus, UserRole
from app.models.user import User
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.responder import ResponderCreate, ResponderReadWithUser, ResponderUpdate
from app.services.audit_service import write_audit
from app.services.responder_service import (
    create_responder,
    delete_responder,
    get_responder_by_id,
    list_responders,
    update_responder,
)

router = APIRouter(prefix="/responders", tags=["Responders"])
_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)


@router.get("", response_model=PaginatedResponse[ResponderReadWithUser], summary="List responders")
async def get_responders(
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[ResponderStatus] = None,
    team: Optional[str] = None,
    zone: Optional[str] = None,
):
    items, total = await list_responders(db, page=page, page_size=page_size, status=status, team=team, zone=zone)
    return PaginatedResponse(
        data=[ResponderReadWithUser.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=ResponderReadWithUser, status_code=status.HTTP_201_CREATED, summary="Create responder")
async def create_new_responder(
    request: Request,
    body: ResponderCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    responder = await create_responder(db, body)
    await write_audit(
        db, "responder.created", actor=actor, entity_type="Responder", entity_id=responder.id,
        metadata={"user_id": responder.user_id, "team": responder.team},
        ip_address=request.client.host if request.client else None,
    )
    return ResponderReadWithUser.model_validate(responder)


@router.get("/{responder_id}", response_model=ResponderReadWithUser, summary="Get responder by ID")
async def get_single_responder(
    responder_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    responder = await get_responder_by_id(db, responder_id)
    return ResponderReadWithUser.model_validate(responder)


@router.patch("/{responder_id}", response_model=ResponderReadWithUser, summary="Update responder status/team")
async def update_single_responder(
    request: Request,
    responder_id: str,
    body: ResponderUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    responder = await update_responder(db, responder_id, body)
    await write_audit(
        db, "responder.updated", actor=actor, entity_type="Responder", entity_id=responder.id,
        metadata=body.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )
    return ResponderReadWithUser.model_validate(responder)


@router.delete("/{responder_id}", response_model=SuccessResponse, summary="Delete responder profile")
async def delete_single_responder(
    request: Request,
    responder_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    await delete_responder(db, responder_id)
    await write_audit(
        db, "responder.deleted", actor=actor, entity_type="Responder", entity_id=responder_id,
        ip_address=request.client.host if request.client else None,
    )
    return SuccessResponse(message="Responder removed")
