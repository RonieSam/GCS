"""
Incident schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.core.enums import IncidentCategory, IncidentPriority, IncidentStatus
from app.schemas.common import EMeshBaseModel


class IncidentCreate(EMeshBaseModel):
    category: IncidentCategory
    priority: IncidentPriority = IncidentPriority.MEDIUM
    description: str = Field(..., min_length=10, max_length=2000)
    people_affected: int = Field(1, ge=1, le=10000)
    location: Optional[str] = Field(None, max_length=512)
    additional_info: Optional[str] = Field(None, max_length=2000)
    origin_node_id: Optional[str] = None


class IncidentRead(EMeshBaseModel):
    id: str
    incident_id: str
    category: IncidentCategory
    priority: IncidentPriority
    status: IncidentStatus
    description: str
    people_affected: int
    location: Optional[str] = None
    additional_info: Optional[str] = None
    reporter_id: Optional[str] = None
    origin_node_id: Optional[str] = None
    assigned_responder_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class IncidentUpdate(EMeshBaseModel):
    priority: Optional[IncidentPriority] = None
    status: Optional[IncidentStatus] = None
    description: Optional[str] = Field(None, min_length=10, max_length=2000)
    people_affected: Optional[int] = Field(None, ge=1)
    location: Optional[str] = Field(None, max_length=512)
    additional_info: Optional[str] = Field(None, max_length=2000)
    assigned_responder_id: Optional[str] = None


class IncidentAssign(EMeshBaseModel):
    responder_id: str


class IncidentNote(EMeshBaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
