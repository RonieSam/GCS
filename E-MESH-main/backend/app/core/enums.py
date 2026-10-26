"""
User roles enumeration — single source of truth used by models, schemas, and RBAC.
"""
from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    CIVILIAN = "CIVILIAN"
    RESPONDER = "RESPONDER"
    INCIDENT_MANAGER = "INCIDENT_MANAGER"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


class IncidentCategory(str, Enum):
    MEDICAL = "MEDICAL"
    FIRE_HAZARD = "FIRE_HAZARD"
    RESCUE_TRAPPED = "RESCUE_TRAPPED"
    FOOD = "FOOD"
    WATER = "WATER"
    SHELTER = "SHELTER"
    EVACUATION = "EVACUATION"
    MISSING_PERSON = "MISSING_PERSON"
    OTHER = "OTHER"


class IncidentPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESPONDING = "RESPONDING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SOSStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class NodeStatus(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class NodeLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class ResponderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    RESPONDING = "RESPONDING"
    UNAVAILABLE = "UNAVAILABLE"
    DEPLOYED = "DEPLOYED"
    BUSY = "BUSY"
    RESTING = "RESTING"
    OFFLINE = "OFFLINE"


class ResourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    DEPLETED = "DEPLETED"
    RESERVED = "RESERVED"


class AnnouncementPriority(str, Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnnouncementTarget(str, Enum):
    ALL_USERS = "ALL_USERS"
    ALL_NODES = "ALL_NODES"
    ZONE = "ZONE"
    SPECIFIC_NODE = "SPECIFIC_NODE"
    RESPONDERS = "RESPONDERS"
