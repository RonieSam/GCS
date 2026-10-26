"""
Resource schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.core.enums import ResourceStatus
from app.schemas.common import EMeshBaseModel


class ResourceCreate(EMeshBaseModel):
    resource_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(0, ge=0)
    available_quantity: int = Field(0, ge=0)
    location: Optional[str] = Field(None, max_length=512)
    status: ResourceStatus = ResourceStatus.AVAILABLE


class ResourceRead(EMeshBaseModel):
    id: str
    resource_type: str
    name: str
    quantity: int
    available_quantity: int
    location: Optional[str] = None
    status: ResourceStatus
    created_at: datetime
    updated_at: datetime


class ResourceUpdate(EMeshBaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    resource_type: Optional[str] = Field(None, min_length=1, max_length=64)
    quantity: Optional[int] = Field(None, ge=0)
    available_quantity: Optional[int] = Field(None, ge=0)
    location: Optional[str] = Field(None, max_length=512)
    status: Optional[ResourceStatus] = None
