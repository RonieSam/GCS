"""
Router for internal ESP32 mesh hardware communication (Telemetry & SOS).

These endpoints are strictly unauthenticated and meant to be consumed ONLY by 
the ESP32 hardware routing traffic over the internal private Radxa hotspot.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
import math

from app.core.dependencies import get_db
from app.models.node_telemetry import NodeTelemetry
from app.core.enums import NodeStatus, UserRole
from app.core.ws_manager import emit_event
from app.schemas.events import EventType
from app.schemas.node import NodeCreate, NodeRead, NodeUpdate
from app.schemas.sos import SOSCreate, SOSRead
from app.services.node_service import create_node, get_node_by_node_id, update_node
from app.services.sos_service import create_sos
from app.services.network_event_service import (
    emit_node_online,
    emit_node_updated,
)

router = APIRouter(prefix="/mesh", tags=["Mesh Hardware"])

# These roles will receive the real-time WebSocket alerts
_ADMIN_ROLES = [UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.RESPONDER, UserRole.VIEWER]


@router.post("/nodes", response_model=NodeRead, summary="Hardware node heartbeat (upsert)")
async def hardware_node_heartbeat(
    request: Request,
    body: NodeCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Called by ESP32 firmware on boot and every N seconds to report telemetry.
    No JWT required. Upserts the node record based on node_id.
    """
    existing_node = await get_node_by_node_id(db, body.node_id)
    
    imu_jerk = 0.0
    if existing_node and existing_node.accel_x is not None and body.accel_x is not None:
        dx = body.accel_x - existing_node.accel_x
        dy = body.accel_y - existing_node.accel_y
        dz = body.accel_z - existing_node.accel_z
        imu_jerk = math.sqrt(dx**2 + dy**2 + dz**2) * 5.0

    if existing_node:
        # Update telemetry + last_heartbeat timestamp
        existing_node.last_heartbeat = datetime.now(timezone.utc)
        update_data = NodeUpdate(
            display_name=body.display_name,
            battery_percent=body.battery_level,
            rssi_dbm=body.signal_quality,
            hop_count=body.hop_count,
            position_x=body.position_x,
            position_y=body.position_y,
            has_gps=body.has_gps,
            gps_lat=body.gps_lat,
            gps_lon=body.gps_lon,
            gps_alt_m=body.gps_alt_m,
            gps_sats=body.gps_sats,
            temperature_c=body.temperature_c,
            pressure_hpa=body.pressure_hpa,
            accel_x=body.accel_x,
            accel_y=body.accel_y,
            accel_z=body.accel_z,
            gyro_x=body.gyro_x,
            gyro_y=body.gyro_y,
            gyro_z=body.gyro_z,
            status=NodeStatus.ONLINE
        )
        node = await update_node(db, existing_node.id, update_data)
        
        emit_node_updated(
            node_id=node.node_id,
            name=node.display_name or node.node_id,
            status="ONLINE",
            battery_level=node.battery_percent,
            signal_quality=node.rssi_dbm,
            hop_count=node.hop_count,
            has_gps=node.has_gps,
            gps_lat=node.gps_lat,
            gps_lon=node.gps_lon,
            gps_alt_m=node.gps_alt_m,
            gps_sats=node.gps_sats,
            temperature_c=node.temperature_c,
            pressure_hpa=node.pressure_hpa,
            accel_x=node.accel_x,
            accel_y=node.accel_y,
            accel_z=node.accel_z,
            gyro_x=node.gyro_x,
            gyro_y=node.gyro_y,
            gyro_z=node.gyro_z,
        )
    else:
        # Create new node registration (set initial heartbeat)
        node = await create_node(db, body)
        
        # We manually update the status/telemetry right after creation since 
        # create_node sets it to UNKNOWN and drops telemetry fields by default
        node.last_heartbeat = datetime.now(timezone.utc)
        update_data = NodeUpdate(
            battery_percent=body.battery_level,
            rssi_dbm=body.signal_quality,
            position_x=body.position_x,
            position_y=body.position_y,
            has_gps=body.has_gps,
            gps_lat=body.gps_lat,
            gps_lon=body.gps_lon,
            gps_alt_m=body.gps_alt_m,
            gps_sats=body.gps_sats,
            temperature_c=body.temperature_c,
            pressure_hpa=body.pressure_hpa,
            accel_x=body.accel_x,
            accel_y=body.accel_y,
            accel_z=body.accel_z,
            gyro_x=body.gyro_x,
            gyro_y=body.gyro_y,
            gyro_z=body.gyro_z,
            status=NodeStatus.ONLINE
        )
        node = await update_node(db, node.id, update_data)

        emit_node_online(
            node_id=node.node_id,
            name=node.display_name or node.node_id,
            battery_level=node.battery_percent,
            signal_quality=node.rssi_dbm,
            hop_count=node.hop_count,
            has_gps=node.has_gps,
            gps_lat=node.gps_lat,
            gps_lon=node.gps_lon,
            gps_alt_m=node.gps_alt_m,
            gps_sats=node.gps_sats,
            temperature_c=node.temperature_c,
            pressure_hpa=node.pressure_hpa,
            accel_x=node.accel_x,
            accel_y=node.accel_y,
            accel_z=node.accel_z,
            gyro_x=node.gyro_x,
            gyro_y=node.gyro_y,
            gyro_z=node.gyro_z,
        )

    # Insert historical telemetry
    telemetry = NodeTelemetry(
        node_id=body.node_id,
        temperature_c=body.temperature_c,
        pressure_hpa=body.pressure_hpa,
        imu_jerk=imu_jerk,
        accel_x=body.accel_x,
        accel_y=body.accel_y,
        accel_z=body.accel_z,
        gyro_x=body.gyro_x,
        gyro_y=body.gyro_y,
        gyro_z=body.gyro_z,
    )
    db.add(telemetry)
    await db.commit()

    return NodeRead.model_validate(node)


@router.post("/sos", response_model=SOSRead, status_code=201, summary="Hardware SOS trigger")
async def hardware_sos_trigger(
    request: Request,
    body: SOSCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Called by ESP32 firmware when the physical SOS button is pressed.
    No JWT required. Creates a CRITICAL incident and broadcasts WebSocket alert.
    """
    # reporter=None because it's a hardware trigger, not an authenticated user
    sos, incident = await create_sos(db, body, reporter=None)

    # Emit real-time WebSocket events for the Admin UI to react
    emit_event(
        event=EventType.SOS_CREATED,
        data={
            "id": sos.id,
            "sos_id": sos.sos_id,
            "incident_id": incident.id,
            "people_count": sos.people_count,
            "notes": sos.notes,
            "status": sos.status.value if hasattr(sos.status, 'value') else str(sos.status),
            "reporter_id": "HARDWARE",
            "reporter_username": "Hardware Button",
            "origin_node_id": sos.origin_node_id,
            "created_at": sos.created_at.isoformat() if sos.created_at else "",
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )

    emit_event(
        event=EventType.INCIDENT_CREATED,
        data={
            "id": incident.id,
            "incident_id": incident.incident_id,
            "category": incident.category.value if hasattr(incident.category, 'value') else str(incident.category),
            "priority": incident.priority.value if hasattr(incident.priority, 'value') else str(incident.priority),
            "status": incident.status.value if hasattr(incident.status, 'value') else str(incident.status),
            "description": incident.description,
            "people_affected": incident.people_affected,
            "reporter_id": "HARDWARE",
            "created_at": incident.created_at.isoformat() if incident.created_at else "",
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )

    return SOSRead.model_validate(sos)
