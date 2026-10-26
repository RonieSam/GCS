"""
Announcement schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.core.enums import AnnouncementPriority, AnnouncementTarget
from app.schemas.common import EMeshBaseModel


class AnnouncementCreate(EMeshBaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=10000)
    priority: AnnouncementPriority = AnnouncementPriority.NORMAL
    target: AnnouncementTarget = AnnouncementTarget.ALL_USERS
    target_node_id: Optional[str] = None
    expires_at: Optional[datetime] = None


class AnnouncementRead(EMeshBaseModel):
    id: str
    title: str
    message: str
    priority: AnnouncementPriority
    target: AnnouncementTarget
    target_node_id: Optional[str] = None
    is_active: bool
    created_by: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None


class AnnouncementUpdate(EMeshBaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    message: Optional[str] = Field(None, min_length=1, max_length=10000)
    priority: Optional[AnnouncementPriority] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
