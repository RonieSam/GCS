"""
Incident service — complete lifecycle management for incidents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IncidentCategory, IncidentPriority, IncidentStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.models.incident import Incident
from app.models.user import User
from app.schemas.incident import IncidentCreate, IncidentUpdate


def _generate_incident_id() -> str:
    """Generate a short human-readable incident ID like INC-00042."""
    suffix = "".join(random.choices(string.digits, k=5))
    return f"INC-{suffix}"


async def create_incident(
    session: AsyncSession,
    data: IncidentCreate,
    reporter: Optional[User] = None,
) -> Incident:
    incident = Incident(
        incident_id=_generate_incident_id(),
        category=data.category,
        priority=data.priority,
        status=IncidentStatus.SUBMITTED,
        description=data.description,
        people_affected=data.people_affected,
        location=data.location,
        additional_info=data.additional_info,
        origin_node_id=data.origin_node_id,
        reporter_id=reporter.id if reporter else None,
    )
    session.add(incident)
    await session.flush()
    return incident


async def get_incident_by_id(session: AsyncSession, incident_id: str) -> Optional[Incident]:
    result = await session.execute(select(Incident).where(Incident.id == incident_id))
    return result.scalar_one_or_none()


async def get_incident_by_public_id(session: AsyncSession, incident_id: str) -> Optional[Incident]:
    result = await session.execute(
        select(Incident).where(Incident.incident_id == incident_id)
    )
    return result.scalar_one_or_none()


async def list_incidents(
    session: AsyncSession,
    reporter_id: Optional[str] = None,
    status: Optional[IncidentStatus] = None,
    priority: Optional[IncidentPriority] = None,
    category: Optional[IncidentCategory] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Incident], int]:
    query = select(Incident)
    if reporter_id:
        query = query.where(Incident.reporter_id == reporter_id)
    if status:
        query = query.where(Incident.status == status)
    if priority:
        query = query.where(Incident.priority == priority)
    if category:
        query = query.where(Incident.category == category)

    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(Incident.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def update_incident(
    session: AsyncSession, incident_id: str, data: IncidentUpdate, actor: Optional[User] = None
) -> Incident:
    incident = await get_incident_by_id(session, incident_id)
    if not incident:
        raise NotFoundError("Incident", incident_id)

    update_data = data.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)

    # Handle status transition timestamps
    new_status = update_data.get("status")
    if new_status:
        if new_status == IncidentStatus.ACKNOWLEDGED and not incident.acknowledged_at:
            incident.acknowledged_at = now
        elif new_status == IncidentStatus.RESOLVED and not incident.resolved_at:
            incident.resolved_at = now
        elif new_status == IncidentStatus.CLOSED and not incident.closed_at:
            incident.closed_at = now

    for field, value in update_data.items():
        setattr(incident, field, value)

    await session.flush()
    return incident


async def acknowledge_incident(session: AsyncSession, incident_id: str) -> Incident:
    incident = await get_incident_by_id(session, incident_id)
    if not incident:
        raise NotFoundError("Incident", incident_id)

    if incident.status != IncidentStatus.SUBMITTED:
        raise ValidationError(
            f"Cannot acknowledge incident in status: {incident.status.value}"
        )

    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_at = datetime.now(timezone.utc)
    await session.flush()
    return incident


async def assign_responder(
    session: AsyncSession, incident_id: str, responder_id: str
) -> Incident:
    incident = await get_incident_by_id(session, incident_id)
    if not incident:
        raise NotFoundError("Incident", incident_id)

    incident.assigned_responder_id = responder_id
    if incident.status in (IncidentStatus.SUBMITTED, IncidentStatus.ACKNOWLEDGED):
        incident.status = IncidentStatus.ASSIGNED

    await session.flush()
    return incident
