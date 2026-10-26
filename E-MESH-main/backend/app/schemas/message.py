"""
Message schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.schemas.common import EMeshBaseModel


class CommunityMessageCreate(EMeshBaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


class CommunityMessageRead(EMeshBaseModel):
    id: str
    sender_id: Optional[str]
    sender_username: Optional[str]
    content: str
    sent_at: datetime
