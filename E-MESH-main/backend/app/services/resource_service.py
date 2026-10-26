"""
Resource service — business logic for emergency resource inventory.
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ResourceStatus
from app.core.exceptions import NotFoundError
from app.models.resource import Resource
from app.schemas.resource import ResourceCreate, ResourceUpdate


async def list_resources(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    resource_type: Optional[str] = None,
    status: Optional[ResourceStatus] = None,
    search: Optional[str] = None,
) -> Tuple[List[Resource], int]:
    query = select(Resource)
    count_query = select(func.count(Resource.id))

    if resource_type:
        query = query.where(Resource.resource_type == resource_type)
        count_query = count_query.where(Resource.resource_type == resource_type)
    if status:
        query = query.where(Resource.status == status)
        count_query = count_query.where(Resource.status == status)
    if search:
        pattern = f"%{search}%"
        query = query.where(Resource.name.ilike(pattern) | Resource.location.ilike(pattern))
        count_query = count_query.where(Resource.name.ilike(pattern) | Resource.location.ilike(pattern))

    total = (await session.execute(count_query)).scalar_one()
    query = query.order_by(Resource.resource_type, Resource.name).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def get_resource_by_id(session: AsyncSession, resource_id: str) -> Resource:
    result = await session.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise NotFoundError("Resource", resource_id)
    return resource


async def create_resource(session: AsyncSession, payload: ResourceCreate) -> Resource:
    resource = Resource(
        resource_type=payload.resource_type,
        name=payload.name,
        quantity=payload.quantity,
        available_quantity=payload.available_quantity if payload.available_quantity is not None else payload.quantity,
        location=payload.location,
        status=payload.status,
    )
    session.add(resource)
    await session.commit()
    await session.refresh(resource)
    return resource


async def update_resource(session: AsyncSession, resource_id: str, payload: ResourceUpdate) -> Resource:
    resource = await get_resource_by_id(session, resource_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(resource, field, value)
    await session.commit()
    await session.refresh(resource)
    return resource


async def delete_resource(session: AsyncSession, resource_id: str) -> None:
    resource = await get_resource_by_id(session, resource_id)
    await session.delete(resource)
    await session.commit()
