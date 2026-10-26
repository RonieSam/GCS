"""
Analytics router — aggregate KPI metrics, incident distributions, and system stats.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.enums import IncidentPriority, IncidentStatus, NodeStatus, ResponderStatus, SOSStatus
from app.models.incident import Incident
from app.models.node import Node
from app.models.resource import Resource
from app.models.responder import Responder
from app.models.sos import SOS
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary", summary="Get aggregated command center analytics")
async def get_analytics_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> Dict[str, Any]:
    # Incidents counts
    total_incidents = (await db.execute(select(func.count(Incident.id)))).scalar_one()
    active_incidents = (
        await db.execute(
            select(func.count(Incident.id)).where(
                Incident.status.in_([IncidentStatus.SUBMITTED, IncidentStatus.ACKNOWLEDGED, IncidentStatus.IN_PROGRESS])
            )
        )
    ).scalar_one()

    # Incidents by priority
    priority_res = await db.execute(
        select(Incident.priority, func.count(Incident.id)).group_by(Incident.priority)
    )
    incidents_by_priority = {p.value if hasattr(p, 'value') else str(p): count for p, count in priority_res.all()}

    # Incidents by category
    category_res = await db.execute(
        select(Incident.category, func.count(Incident.id)).group_by(Incident.category)
    )
    incidents_by_category = {c.value if hasattr(c, 'value') else str(c): count for c, count in category_res.all()}

    # SOS counts
    active_sos = (
        await db.execute(select(func.count(SOS.id)).where(SOS.status == SOSStatus.ACTIVE))
    ).scalar_one()
    total_sos = (await db.execute(select(func.count(SOS.id)))).scalar_one()

    # Node stats
    total_nodes = (await db.execute(select(func.count(Node.id)))).scalar_one()
    online_nodes = (
        await db.execute(select(func.count(Node.id)).where(Node.status == NodeStatus.ONLINE))
    ).scalar_one()
    avg_battery = (await db.execute(select(func.avg(Node.battery_percent)))).scalar_one() or 100.0

    # Responder stats
    total_responders = (await db.execute(select(func.count(Responder.id)))).scalar_one()
    available_responders = (
        await db.execute(select(func.count(Responder.id)).where(Responder.status == ResponderStatus.AVAILABLE))
    ).scalar_one()
    deployed_responders = (
        await db.execute(select(func.count(Responder.id)).where(Responder.status == ResponderStatus.DEPLOYED))
    ).scalar_one()

    # Total Users
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()

    # Resource summary
    total_resources = (await db.execute(select(func.count(Resource.id)))).scalar_one()

    return {
        "incidents": {
            "total": total_incidents,
            "active": active_incidents,
            "resolved": total_incidents - active_incidents,
            "by_priority": incidents_by_priority,
            "by_category": incidents_by_category,
        },
        "sos": {
            "total": total_sos,
            "active": active_sos,
        },
        "mesh": {
            "total_nodes": total_nodes,
            "online_nodes": online_nodes,
            "offline_nodes": total_nodes - online_nodes,
            "health_pct": round((online_nodes / total_nodes * 100) if total_nodes > 0 else 100, 1),
            "avg_battery_pct": round(float(avg_battery), 1),
        },
        "responders": {
            "total": total_responders,
            "available": available_responders,
            "deployed": deployed_responders,
        },
        "users": {
            "total": total_users,
        },
        "resources": {
            "total_items": total_resources,
        },
    }
