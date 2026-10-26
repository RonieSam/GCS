"""
Incidents router — full lifecycle management with RBAC.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_roles
from app.core.enums import IncidentCategory, IncidentPriority, IncidentStatus, UserRole
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.ws_manager import emit_event
from app.models.user import User
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.events import EventType
from app.schemas.incident import (
    IncidentAssign,
    IncidentCreate,
    IncidentNote,
    IncidentRead,
    IncidentUpdate,
)
from app.services.audit_service import write_audit
from app.services.incident_service import (
    acknowledge_incident,
    assign_responder,
    create_incident,
    get_incident_by_id,
    list_incidents,
    update_incident,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])

_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)
_responders = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.RESPONDER)
_all_authenticated = require_roles(
    UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.RESPONDER, UserRole.CIVILIAN, UserRole.VIEWER
)
_ADMIN_ROLES = [UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.RESPONDER, UserRole.VIEWER]


@router.post("", response_model=IncidentRead, status_code=201, summary="Create an incident")
async def create_incident_endpoint(
    request: Request,
    body: IncidentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
):
    incident = await create_incident(db, body, reporter=actor)
    await write_audit(
        db, "incident.created", actor=actor,
        entity_type="Incident", entity_id=incident.id,
        metadata={"incident_id": incident.incident_id, "category": body.category.value if hasattr(body.category, 'value') else str(body.category)},
        ip_address=request.client.host if request.client else None,
    )

    emit_event(
        event=EventType.INCIDENT_CREATED,
        data={
            "id": incident.id,
            "incident_id": incident.incident_id,
            "category": incident.category.value if hasattr(incident.category, 'value') else str(incident.category),
            "priority": incident.priority.value if hasattr(incident.priority, 'value') else str(incident.priority),
            "status": incident.status.value if hasattr(incident.status, 'value') else str(incident.status),
            "description": incident.description,
            "people_affected": incident.people_affected,
            "reporter_id": actor.id,
            "created_at": incident.created_at.isoformat() if incident.created_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=actor.id,
        scope="admin",
    )

    return IncidentRead.model_validate(incident)


@router.get("", response_model=PaginatedResponse[IncidentRead], summary="List incidents")
async def list_incidents_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    status: Optional[IncidentStatus] = None,
    priority: Optional[IncidentPriority] = None,
    category: Optional[IncidentCategory] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    # Civilians only see their own incidents
    reporter_id = None
    if actor.role == UserRole.CIVILIAN:
        reporter_id = actor.id

    incidents, total = await list_incidents(
        db, reporter_id=reporter_id, status=status,
        priority=priority, category=category,
        page=page, page_size=page_size,
    )
    return PaginatedResponse(
        data=[IncidentRead.model_validate(i) for i in incidents],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{incident_id}", response_model=IncidentRead, summary="Get incident details")
async def get_incident_endpoint(
    incident_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
):
    incident = await get_incident_by_id(db, incident_id)
    if not incident:
        raise NotFoundError("Incident", incident_id)

    # Civilians can only view their own incidents
    if actor.role == UserRole.CIVILIAN and incident.reporter_id != actor.id:
        raise AuthorizationError("You do not have access to this incident")

    return IncidentRead.model_validate(incident)


@router.patch("/{incident_id}", response_model=IncidentRead, summary="Update incident")
async def update_incident_endpoint(
    request: Request,
    incident_id: str,
    body: IncidentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    incident = await update_incident(db, incident_id, body, actor=actor)
    await write_audit(
        db, "incident.updated", actor=actor,
        entity_type="Incident", entity_id=incident_id,
        metadata=body.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )

    emit_event(
        event=EventType.INCIDENT_UPDATED,
        data={
            "id": incident.id,
            "incident_id": incident.incident_id,
            "status": incident.status.value if hasattr(incident.status, 'value') else str(incident.status),
            "priority": incident.priority.value if hasattr(incident.priority, 'value') else str(incident.priority),
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=incident.reporter_id,
        scope="admin",
    )

    return IncidentRead.model_validate(incident)


@router.post("/{incident_id}/acknowledge", response_model=IncidentRead, summary="Acknowledge an incident")
async def acknowledge_incident_endpoint(
    request: Request,
    incident_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    incident = await acknowledge_incident(db, incident_id)
    await write_audit(
        db, "incident.acknowledged", actor=actor,
        entity_type="Incident", entity_id=incident_id,
        ip_address=request.client.host if request.client else None,
    )

    emit_event(
        event=EventType.INCIDENT_UPDATED,
        data={
            "id": incident.id,
            "incident_id": incident.incident_id,
            "status": incident.status.value if hasattr(incident.status, 'value') else str(incident.status),
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=incident.reporter_id,
        scope="admin",
    )

    return IncidentRead.model_validate(incident)


@router.post("/{incident_id}/assign", response_model=IncidentRead, summary="Assign a responder")
async def assign_incident_endpoint(
    request: Request,
    incident_id: str,
    body: IncidentAssign,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    incident = await assign_responder(db, incident_id, body.responder_id)
    await write_audit(
        db, "incident.assigned", actor=actor,
        entity_type="Incident", entity_id=incident_id,
        metadata={"responder_id": body.responder_id},
        ip_address=request.client.host if request.client else None,
    )

    emit_event(
        event=EventType.INCIDENT_ASSIGNED,
        data={
            "id": incident.id,
            "incident_id": incident.incident_id,
            "assigned_responder_id": body.responder_id,
            "status": incident.status.value if hasattr(incident.status, 'value') else str(incident.status),
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=incident.reporter_id,
        scope="admin",
    )

    return IncidentRead.model_validate(incident)


@router.post("/{incident_id}/resolve", response_model=IncidentRead, summary="Resolve an incident")
async def resolve_incident_endpoint(
    request: Request,
    incident_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
    body: Optional[IncidentUpdate] = None,
):
    update_payload = body or IncidentUpdate(status=IncidentStatus.RESOLVED)
    if not update_payload.status:
        update_payload.status = IncidentStatus.RESOLVED

    incident = await update_incident(db, incident_id, update_payload, actor=actor)
    await write_audit(
        db, "incident.resolved", actor=actor,
        entity_type="Incident", entity_id=incident_id,
        metadata=update_payload.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )

    emit_event(
        event=EventType.INCIDENT_RESOLVED,
        data={
            "id": incident.id,
            "incident_id": incident.incident_id,
            "status": "RESOLVED",
            "resolution_notes": incident.additional_info or "",
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=incident.reporter_id,
        scope="admin",
    )

    return IncidentRead.model_validate(incident)
