"""
SOS schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.core.enums import SOSStatus
from app.schemas.common import EMeshBaseModel


class SOSCreate(EMeshBaseModel):
    people_count: int = Field(1, ge=1, le=10000)
    notes: Optional[str] = Field(None, max_length=1024)
    origin_node_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    client_id: Optional[str] = None


class SOSRead(EMeshBaseModel):
    id: str
    sos_id: str
    status: SOSStatus
    people_count: int
    notes: Optional[str] = None
    reporter_id: Optional[str] = None
    incident_id: Optional[str] = None
    origin_node_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    client_id: Optional[str] = None
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class SOSUpdate(EMeshBaseModel):
    status: Optional[SOSStatus] = None
    notes: Optional[str] = Field(None, max_length=1024)
    incident_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


