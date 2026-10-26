"""
Responder service — responder roster, teams, zones, and readiness statuses.
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import ResponderStatus
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.models.responder import Responder
from app.models.user import User
from app.schemas.responder import ResponderCreate, ResponderUpdate


async def list_responders(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status: Optional[ResponderStatus] = None,
    team: Optional[str] = None,
    zone: Optional[str] = None,
) -> Tuple[List[Responder], int]:
    query = select(Responder).options(selectinload(Responder.user))
    count_query = select(func.count(Responder.id))

    if status:
        query = query.where(Responder.status == status)
        count_query = count_query.where(Responder.status == status)
    if team:
        query = query.where(Responder.team == team)
        count_query = count_query.where(Responder.team == team)
    if zone:
        query = query.where(Responder.zone == zone)
        count_query = count_query.where(Responder.zone == zone)

    total = (await session.execute(count_query)).scalar_one()
    query = query.order_by(Responder.status, Responder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def get_responder_by_id(session: AsyncSession, responder_id: str) -> Responder:
    result = await session.execute(
        select(Responder).options(selectinload(Responder.user)).where(Responder.id == responder_id)
    )
    resp = result.scalar_one_or_none()
    if not resp:
        raise NotFoundError("Responder", responder_id)
    return resp


async def create_responder(session: AsyncSession, payload: ResponderCreate) -> Responder:
    # Check if user exists
    user_res = await session.execute(select(User).where(User.id == payload.user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", payload.user_id)

    # Check if user already has a responder profile
    existing = await session.execute(select(Responder).where(Responder.user_id == payload.user_id))
    if existing.scalar_one_or_none():
        raise AlreadyExistsError("Responder", f"User {user.username}")

    responder = Responder(
        user_id=payload.user_id,
        team=payload.team,
        zone=payload.zone,
        status=ResponderStatus.AVAILABLE,
    )
    session.add(responder)
    await session.commit()
    await session.refresh(responder)
    return await get_responder_by_id(session, responder.id)


async def update_responder(session: AsyncSession, responder_id: str, payload: ResponderUpdate) -> Responder:
    responder = await get_responder_by_id(session, responder_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(responder, field, value)
    await session.commit()
    await session.refresh(responder)
    return await get_responder_by_id(session, responder.id)


async def delete_responder(session: AsyncSession, responder_id: str) -> None:
    responder = await get_responder_by_id(session, responder_id)
    await session.delete(responder)
    await session.commit()
