"""
Responder schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.enums import ResponderStatus
from app.schemas.common import EMeshBaseModel
from app.schemas.user import UserRead


class ResponderCreate(EMeshBaseModel):
    user_id: str
    team: Optional[str] = None
    zone: Optional[str] = None


class ResponderRead(EMeshBaseModel):
    id: str
    user_id: str
    team: Optional[str] = None
    status: ResponderStatus
    zone: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ResponderReadWithUser(ResponderRead):
    user: Optional[UserRead] = None


class ResponderUpdate(EMeshBaseModel):
    team: Optional[str] = None
    status: Optional[ResponderStatus] = None
    zone: Optional[str] = None
