"""
Pydantic schemas for ESP-WIFI-MESH network simulation and failure/recovery analytics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common import EMeshBaseModel


class SimulatedNodeRead(EMeshBaseModel):
    node_id: str
    mac_address: str
    status: str
    root_id: str
    parent_id: Optional[str] = None
    layer: int
    children: List[str] = Field(default_factory=list)
    rssi_dbm: Optional[float] = None
    packet_loss_percent: float = 0.0
    latency_ms: Optional[float] = None
    battery_percent: Optional[float] = None
    uptime_seconds: int = 0
    packets_received: int = 0
    packets_transmitted: int = 0
    last_heartbeat: Optional[datetime] = None
    current_route: List[str] = Field(default_factory=list)
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class SimulatedNodeCreate(EMeshBaseModel):
    node_id: str = Field(..., min_length=2, max_length=32)
    parent_id: Optional[str] = Field(None)
    battery_percent: Optional[float] = Field(100.0, ge=0.0, le=100.0)
    rssi_dbm: Optional[float] = Field(-60.0, ge=-100.0, le=0.0)
    mac_address: Optional[str] = Field(None)
    position_x: Optional[float] = Field(None)
    position_y: Optional[float] = Field(None)


class SimulatedNodeUpdate(EMeshBaseModel):
    parent_id: Optional[str] = None
    battery_percent: Optional[float] = Field(None, ge=0.0, le=100.0)
    rssi_dbm: Optional[float] = Field(None, ge=-100.0, le=0.0)
    packet_loss_percent: Optional[float] = Field(None, ge=0.0, le=100.0)
    latency_ms: Optional[float] = Field(None, ge=1.0, le=2000.0)


class LinkDegradationRequest(EMeshBaseModel):
    source_node_id: str
    target_node_id: str
    packet_loss_percent: float = Field(..., ge=0.0, le=100.0)
    latency_ms: float = Field(..., ge=1.0, le=5000.0)


class ParentFailureRequest(EMeshBaseModel):
    parent_node_id: str
    auto_reheal: bool = True


class NetworkStatusResponse(EMeshBaseModel):
    mode: str
    protocol_target: str
    root_node_id: str
    total_nodes: int
    online_nodes: int
    degraded_nodes: int
    offline_nodes: int
    max_tree_depth: int
    active_links: int
    uptime_seconds: int


class TopologyResponse(EMeshBaseModel):
    root_id: str
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]
    max_depth: int


class AnalyticsMetricsResponse(EMeshBaseModel):
    total_nodes: int
    online_nodes: int
    degraded_nodes: int
    offline_nodes: int
    node_availability_percent: float
    packet_delivery_ratio: float
    packet_loss_percent: float
    average_latency_ms: float
    average_hop_count: float
    topology_changes_count: int
    latest_recovery_time_ms: float
    average_recovery_time_ms: float
    affected_nodes_count: int


class TimelineEventRead(EMeshBaseModel):
    timestamp: str
    event_type: str
    node_id: str
    message: str
    level: str
