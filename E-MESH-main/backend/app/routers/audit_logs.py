"""
Audit logs router — read-only, admin/manager access only.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.core.enums import UserRole
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogRead
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])

_privileged = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)


@router.get("", response_model=PaginatedResponse[AuditLogRead], summary="List audit logs")
async def list_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(_privileged)],
    action: Optional[str] = None,
    actor_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(AuditLog.timestamp.desc())
    result = await db.execute(query)
    logs = list(result.scalars().all())

    return PaginatedResponse(
        data=[AuditLogRead.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )
