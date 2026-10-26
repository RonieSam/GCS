"""
WebSocket Event Schemas and Envelopes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common import EMeshBaseModel


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventType(str, Enum):
    # SOS Events
    SOS_CREATED = "sos.created"
    SOS_UPDATED = "sos.updated"

    # Incident Events
    INCIDENT_CREATED = "incident.created"
    INCIDENT_UPDATED = "incident.updated"
    INCIDENT_ASSIGNED = "incident.assigned"
    INCIDENT_RESOLVED = "incident.resolved"

    # Announcement Events
    ANNOUNCEMENT_CREATED = "announcement.created"

    # Node & Network Events (ESP-WIFI-MESH ready)
    NODE_ONLINE = "node.online"
    NODE_OFFLINE = "node.offline"
    NODE_UPDATED = "node.updated"
    TOPOLOGY_UPDATED = "topology.updated"
    ROUTE_CHANGED = "route.changed"

    # System Alerts
    SYSTEM_ALERT = "system.alert"

    # Civilian Location Tracking
    USER_LOCATION_UPDATED = "user.location_updated"

    # Community Group Chat
    COMMUNITY_MESSAGE_SENT = "community.message_sent"


class EventEnvelope(EMeshBaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event: EventType
    timestamp: str = Field(default_factory=_utcnow_iso)
    data: Dict[str, Any] = Field(default_factory=dict)
    scope: Optional[str] = None  # e.g., "public", "admin", "user:<user_id>"


# ── Typed Event Payloads ──────────────────────────────────────────────────────

class SOSEventPayload(EMeshBaseModel):
    sos_id: str
    incident_id: Optional[str] = None
    people_count: int
    notes: Optional[str] = None
    node_id: Optional[str] = None
    reporter_id: Optional[str] = None
    reporter_username: Optional[str] = None
    created_at: str


class IncidentEventPayload(EMeshBaseModel):
    incident_id: str
    title: Optional[str] = None
    category: str
    priority: str
    status: str
    description: str
    people_affected: int
    assigned_responder_id: Optional[str] = None
    assigned_responder_name: Optional[str] = None
    resolution_notes: Optional[str] = None
    updated_at: str


class AnnouncementEventPayload(EMeshBaseModel):
    announcement_id: str
    title: str
    message: str
    priority: str
    created_at: str


class NodeStatusEventPayload(EMeshBaseModel):
    node_id: str
    name: str
    status: str
    battery_level: Optional[float] = None
    signal_quality: Optional[float] = None
    hop_count: Optional[int] = None
    timestamp: str


class TopologyEventPayload(EMeshBaseModel):
    total_nodes: int
    online_nodes: int
    links_count: int
    timestamp: str


class RouteChangedEventPayload(EMeshBaseModel):
    source_node_id: str
    destination_node_id: str
    new_route: List[str]
    metric_rssi: Optional[float] = None
    timestamp: str


class SystemAlertPayload(EMeshBaseModel):
    level: str  # "INFO", "WARNING", "CRITICAL"
    message: str
    component: str
    timestamp: str


class CommunityMessagePayload(EMeshBaseModel):
    message_id: str
    sender_id: str
    sender_username: str
    content: str
    sent_at: str
