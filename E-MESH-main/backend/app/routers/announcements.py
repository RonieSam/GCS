"""
Announcements router.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_roles
from app.core.enums import UserRole
from app.core.exceptions import NotFoundError
from app.core.ws_manager import emit_event
from app.models.announcement import Announcement
from app.models.user import User
from app.schemas.announcement import AnnouncementCreate, AnnouncementRead, AnnouncementUpdate
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.events import EventType
from app.services.audit_service import write_audit

router = APIRouter(prefix="/announcements", tags=["Announcements"])

_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)


@router.get("", response_model=PaginatedResponse[AnnouncementRead], summary="List announcements")
async def list_announcements(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(get_current_user)],
    active_only: Optional[bool] = Query(None, description="Filter active announcements only"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    from sqlalchemy import func
    query = select(Announcement)
    if active_only is True:
        query = query.where(Announcement.is_active == True)  # noqa: E712
    elif active_only is False:
        query = query.where(Announcement.is_active == False)  # noqa: E712

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(Announcement.created_at.desc())
    result = await db.execute(query)
    items = list(result.scalars().all())

    return PaginatedResponse(
        data=[AnnouncementRead.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=AnnouncementRead, status_code=201, summary="Create an announcement")
async def create_announcement(
    request: Request,
    body: AnnouncementCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    ann = Announcement(
        title=body.title,
        message=body.message,
        priority=body.priority,
        target=body.target,
        target_node_id=body.target_node_id,
        expires_at=body.expires_at,
        created_by=actor.id,
        is_active=True,
    )
    db.add(ann)
    await db.flush()
    await write_audit(
        db, "announcement.created", actor=actor,
        entity_type="Announcement", entity_id=ann.id,
        metadata={"title": body.title, "priority": body.priority.value},
        ip_address=request.client.host if request.client else None,
    )

    # Public announcement broadcast to all connected mesh clients
    emit_event(
        event=EventType.ANNOUNCEMENT_CREATED,
        data={
            "id": ann.id,
            "title": ann.title,
            "message": ann.message,
            "priority": ann.priority.value if hasattr(ann.priority, 'value') else str(ann.priority),
            "target": ann.target.value if hasattr(ann.target, 'value') else str(ann.target),
            "created_at": ann.created_at.isoformat() if ann.created_at else "",
        },
        target_roles=None,  # All roles receive public announcements
        target_user_id=None,
        scope="public",
    )

    return AnnouncementRead.model_validate(ann)


@router.get("/{ann_id}", response_model=AnnouncementRead, summary="Get an announcement")
async def get_announcement(
    ann_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise NotFoundError("Announcement", ann_id)
    return AnnouncementRead.model_validate(ann)


@router.patch("/{ann_id}", response_model=AnnouncementRead, summary="Update an announcement")
async def update_announcement(
    request: Request,
    ann_id: str,
    body: AnnouncementUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise NotFoundError("Announcement", ann_id)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ann, field, value)
    await db.flush()
    await write_audit(
        db, "announcement.updated", actor=actor,
        entity_type="Announcement", entity_id=ann_id,
        ip_address=request.client.host if request.client else None,
    )
    return AnnouncementRead.model_validate(ann)


@router.delete("/{ann_id}", response_model=SuccessResponse, summary="Delete an announcement")
async def delete_announcement(
    request: Request,
    ann_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise NotFoundError("Announcement", ann_id)
    await db.delete(ann)
    await db.flush()
    await write_audit(
        db, "announcement.deleted", actor=actor,
        entity_type="Announcement", entity_id=ann_id,
        ip_address=request.client.host if request.client else None,
    )
    return SuccessResponse(message="Announcement deleted")
