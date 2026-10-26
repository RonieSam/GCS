"""
Audit service — centralized audit log writer.
All significant operations call write_audit() so we have one place to adjust.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User


async def write_audit(
    session: AsyncSession,
    action: str,
    actor: Optional[User] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    """
    Create and persist an AuditLog entry.

    Args:
        session:     Active async DB session.
        action:      Short machine-readable action name e.g. "incident.created".
        actor:       The User performing the action (None for system actions).
        entity_type: The resource type being acted upon e.g. "Incident".
        entity_id:   The primary key / public ID of the entity.
        metadata:    Extra context dict — will be JSON-serialized.
        ip_address:  Client IP if available.
    """
    log = AuditLog(
        action=action,
        actor_id=actor.id if actor else None,
        actor_username=actor.username if actor else "system",
        actor_role=actor.role.value if actor else None,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=json.dumps(metadata) if metadata else None,
        ip_address=ip_address,
    )
    session.add(log)
    # Flush so we have the ID but don't commit (caller controls transaction)
    await session.flush()
    return log
