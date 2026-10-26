"""
SOS service — creation with cooldown protection and incident linkage.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IncidentCategory, IncidentPriority, IncidentStatus, SOSStatus
from app.core.exceptions import SOSCooldownError
from app.models.incident import Incident
from app.models.sos import SOS
from app.models.user import User
from app.schemas.sos import SOSCreate, SOSUpdate
from app.services.incident_service import _generate_incident_id

# SOS cooldown in seconds — prevents accidental duplicate submissions
SOS_COOLDOWN_SECONDS = 60


def _generate_sos_id() -> str:
    suffix = "".join(random.choices(string.digits, k=5))
    return f"SOS-{suffix}"


async def _check_cooldown(
    session: AsyncSession,
    reporter_id: Optional[str] = None,
    client_id: Optional[str] = None,
) -> None:
    """Raise SOSCooldownError if user or client session sent SOS within cooldown window."""
    if not reporter_id and not client_id:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=SOS_COOLDOWN_SECONDS)
    # Use timezone-naive cutoff for SQLite compatibility (SQLite stores naive datetimes)
    cutoff_naive = cutoff.replace(tzinfo=None)

    query = select(SOS).where(SOS.created_at >= cutoff_naive).where(SOS.status == SOSStatus.ACTIVE)
    if reporter_id and client_id:
        query = query.where((SOS.reporter_id == reporter_id) | (SOS.client_id == client_id))
    elif reporter_id:
        query = query.where(SOS.reporter_id == reporter_id)
    else:
        query = query.where(SOS.client_id == client_id)

    result = await session.execute(query)
    recent = result.scalar_one_or_none()
    if recent:
        recent_created = recent.created_at
        if recent_created.tzinfo is None:
            recent_created = recent_created.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - recent_created).seconds
        remaining = SOS_COOLDOWN_SECONDS - elapsed
        raise SOSCooldownError(max(0, remaining))


async def create_sos(
    session: AsyncSession,
    data: SOSCreate,
    reporter: Optional[User] = None,
) -> tuple[SOS, Incident]:
    """
    Create an SOS alert and an associated CRITICAL incident.
    Enforces cooldown protection against accidental duplicate SOS.
    Returns (sos, incident).
    """
    await _check_cooldown(
        session,
        reporter_id=reporter.id if reporter else None,
        client_id=data.client_id,
    )

    location_str = None
    if data.latitude is not None and data.longitude is not None:
        location_str = f"{data.latitude:.6f}, {data.longitude:.6f}"

    # Create linked incident first
    incident = Incident(
        incident_id=_generate_incident_id(),
        category=IncidentCategory.OTHER,
        priority=IncidentPriority.CRITICAL,
        status=IncidentStatus.SUBMITTED,
        description=f"SOS — Immediate assistance required.{f' (Notes: {data.notes})' if data.notes else ''}",
        people_affected=data.people_count,
        origin_node_id=data.origin_node_id,
        reporter_id=reporter.id if reporter else None,
        location=location_str,
    )
    session.add(incident)
    await session.flush()

    # Create SOS record
    sos = SOS(
        sos_id=_generate_sos_id(),
        status=SOSStatus.ACTIVE,
        people_count=data.people_count,
        notes=data.notes,
        reporter_id=reporter.id if reporter else None,
        incident_id=incident.id,
        origin_node_id=data.origin_node_id,
        latitude=data.latitude,
        longitude=data.longitude,
        accuracy=data.accuracy,
        client_id=data.client_id,
    )
    session.add(sos)
    await session.flush()
    return sos, incident


async def get_sos_by_id(session: AsyncSession, sos_id: str) -> Optional[SOS]:
    result = await session.execute(
        select(SOS).where((SOS.id == sos_id) | (SOS.sos_id == sos_id))
    )
    return result.scalar_one_or_none()


async def list_sos(
    session: AsyncSession,
    status: Optional[SOSStatus] = None,
    reporter_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SOS], int]:
    query = select(SOS)
    if status:
        query = query.where(SOS.status == status)
    if reporter_id:
        query = query.where(SOS.reporter_id == reporter_id)

    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(SOS.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def update_sos(session: AsyncSession, sos_id: str, data: SOSUpdate) -> SOS:
    from app.core.exceptions import NotFoundError

    sos = await get_sos_by_id(session, sos_id)
    if not sos:
        raise NotFoundError("SOS", sos_id)

    now = datetime.now(timezone.utc)
    update_data = data.model_dump(exclude_unset=True)

    new_status = update_data.get("status")
    if new_status == SOSStatus.ACKNOWLEDGED and not sos.acknowledged_at:
        sos.acknowledged_at = now
    elif new_status == SOSStatus.RESOLVED and not sos.resolved_at:
        sos.resolved_at = now

    for field, value in update_data.items():
        setattr(sos, field, value)

    await session.flush()
    return sos
