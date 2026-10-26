"""
Nodes router — mesh node CRUD with RBAC.
"""
from __future__ import annotations

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_optional, get_db, require_roles
from app.core.enums import NodeStatus, UserRole
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.node import NodeCreate, NodeLinkRead, NodeRead, NodeUpdate, NodeTelemetryRead
from app.services.audit_service import write_audit
from app.services.network_event_service import (
    emit_node_offline,
    emit_node_online,
    emit_node_updated,
    emit_topology_updated,
)
from app.services.node_service import (
    create_node,
    delete_node,
    get_node_by_id,
    get_links_for_node,
    list_all_links,
    list_nodes,
    update_node,
)

router = APIRouter(prefix="/nodes", tags=["Nodes"])

_admin_only = require_roles(UserRole.ADMIN)
_privileged = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.VIEWER, UserRole.RESPONDER)


@router.get("", response_model=PaginatedResponse[NodeRead], summary="List all nodes")
async def list_nodes_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
    status: Optional[NodeStatus] = None,

    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    nodes, total = await list_nodes(db, status=status, page=page, page_size=page_size)
    return PaginatedResponse(
        data=[NodeRead.model_validate(n) for n in nodes],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=NodeRead, status_code=201, summary="Create a node")
async def create_node_endpoint(
    request: Request,
    body: NodeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_admin_only)],
):
    node = await create_node(db, body)
    await write_audit(
        db, "node.created", actor=actor, entity_type="Node", entity_id=node.id,
        metadata={"node_id": body.node_id},
        ip_address=request.client.host if request.client else None,
    )

    emit_node_online(
        node_id=node.node_id,
        name=node.display_name or node.node_id,
        battery_level=node.battery_percent,
        signal_quality=node.rssi_dbm,
        hop_count=node.hop_count,
    )
    return NodeRead.model_validate(node)


@router.get("/links", response_model=list[NodeLinkRead], summary="Get all node links (topology)")
async def list_links_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
):
    links = await list_all_links(db)
    return [NodeLinkRead.model_validate(lnk) for lnk in links]


@router.get("/topology", summary="Get complete mesh topology (nodes + links)")
async def get_topology_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
):
    nodes, _ = await list_nodes(db, page=1, page_size=200)
    links = await list_all_links(db)
    
    # Auto-generate visual links if none exist based on hop_count
    if not links and len(nodes) > 1:
        mock_links = []
        import uuid
        from app.core.enums import NodeLinkStatus
        
        by_hop = {}
        for n in nodes:
            hc = n.hop_count or 1
            if hc not in by_hop:
                by_hop[hc] = []
            by_hop[hc].append(n)
            
        for hc in sorted(by_hop.keys()):
            if hc <= 1:
                continue
            parents = by_hop.get(hc - 1, [])
            if not parents:
                parents = [p for p in nodes if (p.hop_count or 1) < hc]
                
            for child in by_hop[hc]:
                parent = parents[child.node_id.__hash__() % len(parents)] if parents else None
                if parent:
                    mock_links.append(NodeLinkRead(
                        id=str(uuid.uuid4()),
                        source_node_id=child.node_id,
                        target_node_id=parent.node_id,
                        rssi_dbm=child.rssi_dbm,
                        packet_loss_percent=child.packet_loss_percent,
                        latency_ms=15.0,
                        status=NodeLinkStatus.ACTIVE
                    ))
                    
        return {
            "nodes": [NodeRead.model_validate(n).model_dump() for n in nodes],
            "links": [l.model_dump() for l in mock_links],
        }

    return {
        "nodes": [NodeRead.model_validate(n).model_dump() for n in nodes],
        "links": [NodeLinkRead.model_validate(l).model_dump() for l in links],
    }


@router.get("/{node_id}", response_model=NodeRead, summary="Get a node by ID")
async def get_node_endpoint(
    node_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
):
    node = await get_node_by_id(db, node_id)
    if not node:
        raise NotFoundError("Node", node_id)
    return NodeRead.model_validate(node)



@router.patch("/{node_id}", response_model=NodeRead, summary="Update a node")
async def update_node_endpoint(
    request: Request,
    node_id: str,
    body: NodeUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_admin_only)],
):
    node = await update_node(db, node_id, body)
    await write_audit(
        db, "node.updated", actor=actor, entity_type="Node", entity_id=node_id,
        metadata=body.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )

    emit_node_updated(
        node_id=node.node_id,
        name=node.display_name or node.node_id,
        status=node.status.value if hasattr(node.status, 'value') else str(node.status),
        battery_level=node.battery_percent,
        signal_quality=node.rssi_dbm,
        hop_count=node.hop_count,
    )
    return NodeRead.model_validate(node)


@router.delete("/{node_id}", response_model=SuccessResponse, summary="Delete a node")
async def delete_node_endpoint(
    request: Request,
    node_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(_admin_only)],
):
    node = await get_node_by_id(db, node_id)
    name = (node.display_name or node.node_id) if node else node_id
    nid = node.node_id if node else node_id

    await delete_node(db, node_id)
    await write_audit(
        db, "node.deleted", actor=actor, entity_type="Node", entity_id=node_id,
        ip_address=request.client.host if request.client else None,
    )

    emit_node_offline(node_id=nid, name=name)
    return SuccessResponse(message="Node deleted")


@router.get("/{node_id}/links", response_model=list[NodeLinkRead], summary="Get links for a specific node")
async def get_node_links(
    node_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(_privileged)],
):
    node = await get_node_by_id(db, node_id)
    if not node:
        raise NotFoundError("Node", node_id)
    links = await get_links_for_node(db, node.id)
    return [NodeLinkRead.model_validate(lnk) for lnk in links]


@router.get("/{node_id}/telemetry", response_model=list[NodeTelemetryRead], summary="Get time-series telemetry for a specific node")
async def get_node_telemetry(
    node_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(_privileged)],
    limit: int = Query(100, ge=1, le=1000)
):
    from sqlalchemy import select
    from app.models.node_telemetry import NodeTelemetry
    
    node = await get_node_by_id(db, node_id)
    if not node:
        raise NotFoundError("Node", node_id)
        
    result = await db.execute(
        select(NodeTelemetry)
        .where(NodeTelemetry.node_id == node.node_id)
        .order_by(NodeTelemetry.timestamp.desc())
        .limit(limit)
    )
    telemetry = result.scalars().all()
    # Return ascending order for charts
    return [NodeTelemetryRead.model_validate(t) for t in reversed(telemetry)]
