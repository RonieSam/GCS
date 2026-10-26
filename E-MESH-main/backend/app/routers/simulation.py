"""
Simulation router — REST endpoints for ESP-WIFI-MESH network simulation and failure/recovery analytics.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.dependencies import get_current_user, require_roles
from app.core.enums import UserRole
from app.gateway.simulated import get_gateway
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.simulation import (
    AnalyticsMetricsResponse,
    LinkDegradationRequest,
    NetworkStatusResponse,
    ParentFailureRequest,
    SimulatedNodeCreate,
    SimulatedNodeRead,
    SimulatedNodeUpdate,
    TimelineEventRead,
    TopologyResponse,
)

router = APIRouter(prefix="/simulation", tags=["Simulation"])

_admin_only = require_roles(UserRole.ADMIN)
_privileged = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.VIEWER, UserRole.RESPONDER)


@router.get("/network-status", response_model=NetworkStatusResponse, summary="Get overall simulated mesh network status")
async def get_network_status_endpoint(
    _actor: Annotated[User, Depends(_privileged)],
):
    gw = get_gateway()
    status_data = await gw.get_network_status()
    return NetworkStatusResponse(**status_data)


@router.get("/analytics", response_model=AnalyticsMetricsResponse, summary="Get comprehensive network analytics & failure metrics")
async def get_analytics_metrics_endpoint(
    _actor: Annotated[User, Depends(_privileged)],
):
    gw = get_gateway()
    metrics = await gw.get_analytics_metrics()
    return AnalyticsMetricsResponse(**metrics)


@router.get("/timeline", response_model=List[TimelineEventRead], summary="Get live failure & recovery event timeline")
async def get_timeline_endpoint(
    _actor: Annotated[User, Depends(_privileged)],
    limit: int = 50,
):
    gw = get_gateway()
    timeline = await gw.get_timeline(limit=limit)
    return [TimelineEventRead(**e) for e in timeline]


@router.get("/topology", response_model=TopologyResponse, summary="Get full ESP-WIFI-MESH tree topology")
async def get_topology_endpoint(
    _actor: Annotated[User, Depends(_privileged)],
):
    gw = get_gateway()
    topo = await gw.get_topology()
    return TopologyResponse(**topo)


@router.get("/routes", summary="Get all calculated routes to the Gateway")
async def get_routes_endpoint(
    _actor: Annotated[User, Depends(_privileged)],
) -> Dict[str, List[str]]:
    gw = get_gateway()
    return await gw.get_routes()


@router.get("/nodes", response_model=List[SimulatedNodeRead], summary="List all simulated nodes")
async def list_simulated_nodes_endpoint(
    _actor: Annotated[User, Depends(_privileged)],
):
    gw = get_gateway()
    nodes = await gw.get_nodes()
    return [SimulatedNodeRead.model_validate(n) for n in nodes]


@router.get("/nodes/{node_id}", response_model=SimulatedNodeRead, summary="Get details for a simulated node")
async def get_simulated_node_endpoint(
    node_id: str,
    _actor: Annotated[User, Depends(_privileged)],
):
    gw = get_gateway()
    node = await gw.get_node(node_id)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node {node_id} not found in simulation")
    return SimulatedNodeRead.model_validate(node)


@router.post("/nodes", response_model=SimulatedNodeRead, status_code=status.HTTP_201_CREATED, summary="Create a simulated node")
async def create_simulated_node_endpoint(
    body: SimulatedNodeCreate,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    node = await gw.create_node(
        node_id=body.node_id,
        parent_id=body.parent_id,
        battery=body.battery_percent,
        rssi=body.rssi_dbm or -60.0,
        mac_address=body.mac_address,
        position_x=body.position_x,
        position_y=body.position_y,
    )
    return SimulatedNodeRead.model_validate(node)


@router.delete("/nodes/{node_id}", response_model=SuccessResponse, summary="Delete a simulated node")
async def delete_simulated_node_endpoint(
    node_id: str,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    success = await gw.delete_node(node_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot delete node {node_id}")
    return SuccessResponse(message=f"Node {node_id} removed from simulation")


@router.post("/nodes/{node_id}/online", response_model=SuccessResponse, summary="Bring a simulated node online")
async def bring_node_online_endpoint(
    node_id: str,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    success = await gw.bring_node_online(node_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node {node_id} not found")
    return SuccessResponse(message=f"Node {node_id} brought online")


@router.post("/nodes/{node_id}/offline", response_model=SuccessResponse, summary="Take a simulated node offline")
async def take_node_offline_endpoint(
    node_id: str,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    success = await gw.take_node_offline(node_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node {node_id} not found")
    return SuccessResponse(message=f"Node {node_id} taken offline")


@router.post("/nodes/{node_id}/restore", response_model=SuccessResponse, summary="Restore a simulated node to full health")
async def restore_node_endpoint(
    node_id: str,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    success = await gw.restore_node(node_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node {node_id} not found")
    return SuccessResponse(message=f"Node {node_id} restored to full health")


@router.post("/nodes/{node_id}/heartbeat", response_model=SuccessResponse, summary="Simulate node heartbeat")
async def simulate_heartbeat_endpoint(
    node_id: str,
    _actor: Annotated[User, Depends(_privileged)],
):
    gw = get_gateway()
    success = await gw.simulate_heartbeat(node_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node {node_id} not found or offline")
    return SuccessResponse(message=f"Heartbeat received from {node_id}")


@router.patch("/nodes/{node_id}", response_model=SimulatedNodeRead, summary="Update node simulation parameters")
async def update_simulated_node_endpoint(
    node_id: str,
    body: SimulatedNodeUpdate,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    node = await gw.update_node_simulation(
        node_id=node_id,
        parent_id=body.parent_id,
        battery=body.battery_percent,
        rssi=body.rssi_dbm,
        packet_loss=body.packet_loss_percent,
        latency=body.latency_ms,
    )
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node {node_id} not found")
    return SimulatedNodeRead.model_validate(node)


@router.post("/links/degrade", response_model=SuccessResponse, summary="Simulate mesh link degradation")
async def degrade_link_endpoint(
    body: LinkDegradationRequest,
    _actor: Annotated[User, Depends(_admin_only)],
):
    gw = get_gateway()
    success = await gw.simulate_link_degradation(
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        packet_loss_percent=body.packet_loss_percent,
        latency_ms=body.latency_ms,
    )
    return SuccessResponse(message=f"Degradation simulated between {body.source_node_id} and {body.target_node_id}")


@router.post("/fail-parent", summary="Simulate parent failure and observe self-healing re-parenting")
async def fail_parent_endpoint(
    body: ParentFailureRequest,
    _actor: Annotated[User, Depends(_admin_only)],
) -> Dict[str, Any]:
    gw = get_gateway()
    return await gw.simulate_parent_failure(
        parent_node_id=body.parent_node_id,
        auto_reheal=body.auto_reheal,
    )


@router.post("/fail-gateway", summary="Simulate Root Gateway failure")
async def fail_gateway_endpoint(
    _actor: Annotated[User, Depends(_admin_only)],
) -> Dict[str, Any]:
    gw = get_gateway()
    return await gw.simulate_gateway_failure()


@router.post("/restore-network", summary="Restore full mesh network to initial seed state")
async def restore_network_endpoint(
    _actor: Annotated[User, Depends(_admin_only)],
) -> Dict[str, Any]:
    gw = get_gateway()
    return await gw.restore_full_network()
