"""
Gateway abstraction interface for E-Mesh.

This defines the clean boundary between the application layer and the underlying transport layer.

Target Physical Mesh: ESP-WIFI-MESH (future physical implementation)
Current Implementation: SimulatedMeshGateway (software-only application simulation)

The web application depends ONLY on MeshGatewayInterface — never on concrete hardware implementations.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SimulatedNodeModel:
    """Status and telemetry snapshot for a simulated ESP-WIFI-MESH node."""
    node_id: str
    mac_address: str
    status: str  # "ONLINE" | "OFFLINE" | "DEGRADED" | "ISOLATED" | "RECONNECTING"
    root_id: str = "GATEWAY"
    parent_id: Optional[str] = None
    layer: int = 1  # 1 for Root, 2 for Direct Children, 3 for Leaf/Grandchildren
    children: List[str] = field(default_factory=list)
    rssi_dbm: Optional[float] = -55.0
    packet_loss_percent: float = 0.0
    latency_ms: Optional[float] = 12.0
    battery_percent: Optional[float] = 100.0
    uptime_seconds: int = 0
    packets_received: int = 0
    packets_transmitted: int = 0
    last_heartbeat: Optional[datetime] = None
    current_route: List[str] = field(default_factory=list)
    position_x: Optional[float] = None
    position_y: Optional[float] = None

    # Backward compatibility properties
    @property
    def packet_rx(self) -> int:
        return self.packets_received

    @property
    def packet_tx(self) -> int:
        return self.packets_transmitted

    @property
    def queue_depth(self) -> int:
        return 0

    @property
    def neighbour_count(self) -> int:
        return len(self.children) + (1 if self.parent_id else 0)


@dataclass
class SimulatedLinkModel:
    """Telemetry for a directed or bidirectional link between two mesh nodes."""
    source_node_id: str
    target_node_id: str
    rssi_dbm: float = -60.0
    packet_loss_percent: float = 0.0
    latency_ms: float = 15.0
    status: str = "ACTIVE"  # "ACTIVE" | "DEGRADED" | "DOWN"
    last_update: Optional[datetime] = None


@dataclass
class TimelineEvent:
    """Represents a discrete network simulation event log entry."""
    timestamp: str
    event_type: str  # "NODE_OFFLINE" | "PARENT_LOST" | "REJOINING" | "PARENT_REASSIGNED" | "TOPOLOGY_UPDATED" | "ROUTE_RESTORED" | "GATEWAY_FAILURE" | "NETWORK_RESTORED"
    node_id: str
    message: str
    level: str = "INFO"  # "INFO" | "WARNING" | "CRITICAL" | "SUCCESS"


@dataclass
class Packet:
    """Represents a data packet to be routed through the mesh."""
    destination_node_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    packet_type: str = "DATA"
    priority: int = 0


# Backwards compatibility aliases
NodeInfo = SimulatedNodeModel
LinkInfo = SimulatedLinkModel


class MeshGatewayInterface(ABC):
    """
    Abstract base class for mesh gateway implementations.
    All concrete gateways (SimulatedMeshGateway or ESPWifiMeshGateway) must implement this interface.
    """

    @abstractmethod
    async def get_network_status(self) -> Dict[str, Any]:
        """Return overall health, node counts, and operational summary of the mesh."""

    @abstractmethod
    async def get_nodes(self) -> List[SimulatedNodeModel]:
        """Return current status of all known mesh nodes."""

    @abstractmethod
    async def get_node(self, node_id: str) -> Optional[SimulatedNodeModel]:
        """Return status of a specific node, or None if unknown."""

    @abstractmethod
    async def get_links(self) -> List[SimulatedLinkModel]:
        """Return all current mesh links."""

    @abstractmethod
    async def get_topology(self) -> Dict[str, Any]:
        """Return complete hierarchical tree topology (nodes, links, layers, root)."""

    @abstractmethod
    async def get_routes(self) -> Dict[str, List[str]]:
        """Return computed routes from each node to the Root Gateway."""

    @abstractmethod
    async def get_analytics_metrics(self) -> Dict[str, Any]:
        """Calculate and return network analytics KPIs (availability, PDR, latency, hops, recovery time, changes)."""

    @abstractmethod
    async def get_timeline(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return live failure & recovery event timeline."""

    @abstractmethod
    async def send_message(self, destination_node_id: str, payload: Dict[str, Any]) -> bool:
        """Send a data payload to a specific node."""

    @abstractmethod
    async def send_announcement(self, title: str, message: str, target_node_id: Optional[str] = None) -> bool:
        """Broadcast an emergency announcement across the mesh."""

    @abstractmethod
    async def send_incident(self, incident_id: str, priority: str, node_id: Optional[str] = None) -> bool:
        """Relay incident dispatch information to mesh nodes."""

    @abstractmethod
    async def get_node_metrics(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Return telemetry metrics (battery, packet loss, RSSI, latency, traffic) for a node."""

    @abstractmethod
    async def create_node(
        self,
        node_id: str,
        parent_id: Optional[str] = None,
        battery: Optional[float] = 100.0,
        rssi: float = -60.0,
        mac_address: Optional[str] = None,
        position_x: Optional[float] = None,
        position_y: Optional[float] = None,
    ) -> SimulatedNodeModel:
        """Dynamically add a simulated node into the mesh topology."""

    @abstractmethod
    async def delete_node(self, node_id: str) -> bool:
        """Decommission and remove a simulated node from the mesh."""

    @abstractmethod
    async def bring_node_online(self, node_id: str) -> bool:
        """Request a node to come online."""

    @abstractmethod
    async def take_node_offline(self, node_id: str) -> bool:
        """Simulate a node powering down or losing connectivity."""

    @abstractmethod
    async def restore_node(self, node_id: str) -> bool:
        """Restore an offline or degraded node back to full operational health."""

    @abstractmethod
    async def update_node_simulation(
        self,
        node_id: str,
        parent_id: Optional[str] = None,
        battery: Optional[float] = None,
        rssi: Optional[float] = None,
        packet_loss: Optional[float] = None,
        latency: Optional[float] = None,
    ) -> Optional[SimulatedNodeModel]:
        """Update simulated telemetry or re-assign parent in the tree."""

    @abstractmethod
    async def simulate_heartbeat(self, node_id: str) -> bool:
        """Trigger an instant heartbeat telemetry pulse from a node."""

    @abstractmethod
    async def simulate_link_degradation(
        self,
        source_node_id: str,
        target_node_id: str,
        packet_loss_percent: float,
        latency_ms: float,
    ) -> bool:
        """Simulate noise, physical obstruction, or packet drop on a link."""

    @abstractmethod
    async def simulate_parent_failure(self, parent_node_id: str, auto_reheal: bool = True) -> Dict[str, Any]:
        """Simulate parent failure and observe child orphan detection and self-healing parent reassignment."""

    @abstractmethod
    async def simulate_gateway_failure(self) -> Dict[str, Any]:
        """Simulate Root Gateway failure where the entire mesh loses root connectivity."""

    @abstractmethod
    async def restore_full_network(self) -> Dict[str, Any]:
        """Restore entire mesh network to initial seed topology and full operational health."""


# Backwards compatibility alias
GatewayInterface = MeshGatewayInterface
