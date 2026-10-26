"""
SOS router — create and manage SOS alerts.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_user_optional, get_db, require_roles
from app.core.enums import SOSStatus, UserRole
from app.core.ws_manager import emit_event
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.events import EventType
from app.schemas.sos import SOSCreate, SOSRead, SOSUpdate
from app.services.audit_service import write_audit
from app.services.sos_service import create_sos, list_sos, update_sos

router = APIRouter(prefix="/sos", tags=["SOS"])

_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)
_ADMIN_ROLES = [UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.RESPONDER, UserRole.VIEWER]


@router.post("", response_model=SOSRead, status_code=201, summary="Send an SOS alert")
async def create_sos_endpoint(
    request: Request,
    body: SOSCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
):
    sos, incident = await create_sos(db, body, reporter=actor)
    if actor:
        await write_audit(
            db, "sos.created", actor=actor,
            entity_type="SOS", entity_id=sos.id,
            metadata={"sos_id": sos.sos_id, "incident_id": incident.incident_id},
            ip_address=request.client.host if request.client else None,
        )

    reporter_uname = actor.username if actor else f"Citizen ({body.client_id or 'Mobile'})"

    # Emit real-time WebSocket events
    emit_event(
        event=EventType.SOS_CREATED,
        data={
            "id": sos.id,
            "sos_id": sos.sos_id,
            "incident_id": incident.id,
            "people_count": sos.people_count,
            "notes": sos.notes,
            "status": sos.status.value if hasattr(sos.status, 'value') else str(sos.status),
            "reporter_id": actor.id if actor else None,
            "reporter_username": reporter_uname,
            "origin_node_id": sos.origin_node_id,
            "latitude": sos.latitude,
            "longitude": sos.longitude,
            "accuracy": sos.accuracy,
            "client_id": sos.client_id,
            "created_at": sos.created_at.isoformat() if sos.created_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=actor.id if actor else None,
        scope="admin",
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
            "reporter_id": actor.id if actor else None,
            "location": incident.location,
            "created_at": incident.created_at.isoformat() if incident.created_at else "",
        },
        target_roles=_ADMIN_ROLES,
        target_user_id=actor.id if actor else None,
        scope="admin",
    )

    return SOSRead.model_validate(sos)


@router.get("", response_model=PaginatedResponse[SOSRead], summary="List SOS alerts")
async def list_sos_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
    status: Optional[SOSStatus] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    # Civilians see only their own SOS if authenticated; if None or Manager/Admin, see all
    reporter_id = actor.id if (actor and actor.role == UserRole.CIVILIAN) else None
    sos_list, total = await list_sos(db, status=status, reporter_id=reporter_id, page=page, page_size=page_size)
    return PaginatedResponse(
        data=[SOSRead.model_validate(s) for s in sos_list],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )



@router.patch("/{sos_id}", response_model=SOSRead, summary="Update SOS status")
async def update_sos_endpoint(
    request: Request,
    sos_id: str,
    body: SOSUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
):
    sos = await update_sos(db, sos_id, body)
    if actor:
        await write_audit(
            db, "sos.updated", actor=actor,
            entity_type="SOS", entity_id=sos_id,
            metadata=body.model_dump(exclude_unset=True),
            ip_address=request.client.host if request.client else None,
        )

    event_data = {
        "sos_id": sos.sos_id,
        "id": sos.id,
        "status": sos.status.value if hasattr(sos.status, 'value') else str(sos.status),
        "latitude": sos.latitude,
        "longitude": sos.longitude,
        "accuracy": sos.accuracy,
        "people_count": sos.people_count,
        "notes": sos.notes,
        "client_id": sos.client_id,
        "origin_node_id": sos.origin_node_id,
        "created_at": sos.created_at.isoformat() if sos.created_at else "",
        "acknowledged_at": sos.acknowledged_at.isoformat() if sos.acknowledged_at else "",
        "resolved_at": sos.resolved_at.isoformat() if sos.resolved_at else "",
    }

    emit_event(
        event=EventType.SOS_UPDATED,
        data=event_data,
        target_roles=_ADMIN_ROLES,
        target_user_id=sos.reporter_id,
        scope="admin",
    )

    emit_event(
        event=EventType.INCIDENT_UPDATED,
        data=event_data,
        target_roles=_ADMIN_ROLES,
        target_user_id=sos.reporter_id,
        scope="admin",
    )

    return SOSRead.model_validate(sos)

