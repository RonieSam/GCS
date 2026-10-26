"""
Resources router — endpoints for inventory and asset management.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_roles
from app.core.enums import ResourceStatus, UserRole
from app.models.user import User
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.resource import ResourceCreate, ResourceRead, ResourceUpdate
from app.services.audit_service import write_audit
from app.services.resource_service import (
    create_resource,
    delete_resource,
    get_resource_by_id,
    list_resources,
    update_resource,
)

router = APIRouter(prefix="/resources", tags=["Resources"])
_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)


@router.get("", response_model=PaginatedResponse[ResourceRead], summary="List resources")
async def get_resources(
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    resource_type: Optional[str] = None,
    status: Optional[ResourceStatus] = None,
    search: Optional[str] = None,
):
    items, total = await list_resources(
        db, page=page, page_size=page_size, resource_type=resource_type, status=status, search=search
    )
    return PaginatedResponse(
        data=[ResourceRead.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=ResourceRead, status_code=status.HTTP_201_CREATED, summary="Create a resource")
async def create_new_resource(
    request: Request,
    body: ResourceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    resource = await create_resource(db, body)
    await write_audit(
        db, "resource.created", actor=actor, entity_type="Resource", entity_id=resource.id,
        metadata={"name": resource.name, "quantity": resource.quantity},
        ip_address=request.client.host if request.client else None,
    )
    return ResourceRead.model_validate(resource)


@router.get("/{resource_id}", response_model=ResourceRead, summary="Get resource by ID")
async def get_single_resource(
    resource_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    resource = await get_resource_by_id(db, resource_id)
    return ResourceRead.model_validate(resource)


@router.patch("/{resource_id}", response_model=ResourceRead, summary="Update resource")
async def update_single_resource(
    request: Request,
    resource_id: str,
    body: ResourceUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    resource = await update_resource(db, resource_id, body)
    await write_audit(
        db, "resource.updated", actor=actor, entity_type="Resource", entity_id=resource.id,
        metadata=body.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )
    return ResourceRead.model_validate(resource)


@router.delete("/{resource_id}", response_model=SuccessResponse, summary="Delete resource")
async def delete_single_resource(
    request: Request,
    resource_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_managers)],
):
    await delete_resource(db, resource_id)
    await write_audit(
        db, "resource.deleted", actor=actor, entity_type="Resource", entity_id=resource_id,
        ip_address=request.client.host if request.client else None,
    )
    return SuccessResponse(message="Resource deleted")
