"""
AuditLog schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.schemas.common import EMeshBaseModel


class AuditLogRead(EMeshBaseModel):
    id: str
    timestamp: datetime
    actor_id: Optional[str] = None
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    metadata_json: Optional[str] = None
    ip_address: Optional[str] = None

    @property
    def created_at(self) -> datetime:
        return self.timestamp

