"""
Abstract Network Event Source & Dispatcher.

Decouples the application layer from physical wireless protocols (e.g. ESP-WIFI-MESH).
The simulated gateway or future ESP-WIFI-MESH hardware driver emits events through this service.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.core.enums import UserRole
from app.core.ws_manager import emit_event
from app.schemas.events import EventType

_ADMIN_ROLES = [UserRole.ADMIN, UserRole.INCIDENT_MANAGER, UserRole.RESPONDER, UserRole.VIEWER]


def emit_node_online(
    node_id: str,
    name: str,
    battery_level: Optional[float] = None,
    signal_quality: Optional[float] = None,
    hop_count: Optional[int] = None,
    has_gps: Optional[bool] = False,
    gps_lat: Optional[float] = None,
    gps_lon: Optional[float] = None,
    gps_alt_m: Optional[float] = None,
    gps_sats: Optional[int] = None,
    temperature_c: Optional[float] = None,
    pressure_hpa: Optional[float] = None,
    accel_x: Optional[int] = None,
    accel_y: Optional[int] = None,
    accel_z: Optional[int] = None,
    gyro_x: Optional[int] = None,
    gyro_y: Optional[int] = None,
    gyro_z: Optional[int] = None,
) -> None:
    emit_event(
        event=EventType.NODE_ONLINE,
        data={
            "node_id": node_id,
            "name": name,
            "status": "ONLINE",
            "battery_level": battery_level,
            "signal_quality": signal_quality,
            "hop_count": hop_count,
            "has_gps": has_gps,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "gps_alt_m": gps_alt_m,
            "gps_sats": gps_sats,
            "temperature_c": temperature_c,
            "pressure_hpa": pressure_hpa,
            "accel_x": accel_x,
            "accel_y": accel_y,
            "accel_z": accel_z,
            "gyro_x": gyro_x,
            "gyro_y": gyro_y,
            "gyro_z": gyro_z,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )


def emit_node_offline(node_id: str, name: str) -> None:
    emit_event(
        event=EventType.NODE_OFFLINE,
        data={
            "node_id": node_id,
            "name": name,
            "status": "OFFLINE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )


def emit_node_updated(
    node_id: str,
    name: str,
    status: str,
    battery_level: Optional[float] = None,
    signal_quality: Optional[float] = None,
    hop_count: Optional[int] = None,
    has_gps: Optional[bool] = False,
    gps_lat: Optional[float] = None,
    gps_lon: Optional[float] = None,
    gps_alt_m: Optional[float] = None,
    gps_sats: Optional[int] = None,
    temperature_c: Optional[float] = None,
    pressure_hpa: Optional[float] = None,
    accel_x: Optional[int] = None,
    accel_y: Optional[int] = None,
    accel_z: Optional[int] = None,
    gyro_x: Optional[int] = None,
    gyro_y: Optional[int] = None,
    gyro_z: Optional[int] = None,
) -> None:
    emit_event(
        event=EventType.NODE_UPDATED,
        data={
            "node_id": node_id,
            "name": name,
            "status": status,
            "battery_level": battery_level,
            "signal_quality": signal_quality,
            "hop_count": hop_count,
            "has_gps": has_gps,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "gps_alt_m": gps_alt_m,
            "gps_sats": gps_sats,
            "temperature_c": temperature_c,
            "pressure_hpa": pressure_hpa,
            "accel_x": accel_x,
            "accel_y": accel_y,
            "accel_z": accel_z,
            "gyro_x": gyro_x,
            "gyro_y": gyro_y,
            "gyro_z": gyro_z,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )


def emit_topology_updated(total_nodes: int, online_nodes: int, links_count: int) -> None:
    emit_event(
        event=EventType.TOPOLOGY_UPDATED,
        data={
            "total_nodes": total_nodes,
            "online_nodes": online_nodes,
            "links_count": links_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )


def emit_route_changed(
    source_node_id: str,
    destination_node_id: str,
    new_route: List[str],
    metric_rssi: Optional[float] = None,
) -> None:
    emit_event(
        event=EventType.ROUTE_CHANGED,
        data={
            "source_node_id": source_node_id,
            "destination_node_id": destination_node_id,
            "new_route": new_route,
            "metric_rssi": metric_rssi,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )


def emit_system_alert(level: str, message: str, component: str = "GATEWAY") -> None:
    emit_event(
        event=EventType.SYSTEM_ALERT,
        data={
            "level": level,
            "message": message,
            "component": component,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        target_roles=_ADMIN_ROLES,
        scope="admin",
    )
