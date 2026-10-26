"""
Node model — represents a mesh network node (simulated or real).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NodeStatus
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    node_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True,
        comment="Human-readable node identifier e.g. EM-01 or GATEWAY-01"
    )
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[NodeStatus] = mapped_column(
        Enum(NodeStatus, native_enum=False), nullable=False, default=NodeStatus.UNKNOWN
    )
    is_gateway: Mapped[bool] = mapped_column(default=False)
    uptime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    battery_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    rssi_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hop_count: Mapped[int] = mapped_column("neighbour_count", Integer, nullable=False, default=1)
    packet_rx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    packet_tx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    packet_loss_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_route: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON array of node IDs representing current route to gateway"
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position_x: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Topology visualization X")
    position_y: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Topology visualization Y")
    has_gps: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="True if GPS hardware is connected")
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True, comment="GPS latitude (decimal degrees)")
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True, comment="GPS longitude (decimal degrees)")
    gps_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True, comment="GPS altitude (metres)")
    gps_sats: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="GPS satellites in use")
    # ── Sensor telemetry (nullable — only populated when sensors are present) ──
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True, comment="BMP280 temperature (°C)")
    pressure_hpa: Mapped[float | None] = mapped_column(Float, nullable=True, comment="BMP280 pressure (hPa)")
    accel_x: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="MPU6050 accelerometer X raw")
    accel_y: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="MPU6050 accelerometer Y raw")
    accel_z: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="MPU6050 accelerometer Z raw")
    gyro_x: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="MPU6050 gyroscope X raw")
    gyro_y: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="MPU6050 gyroscope Y raw")
    gyro_z: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="MPU6050 gyroscope Z raw")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relationships ─────────────────────────────────────────────────────
    devices: Mapped[list["Device"]] = relationship("Device", back_populates="node")  # noqa: F821
    incidents: Mapped[list["Incident"]] = relationship(  # noqa: F821
        "Incident", back_populates="origin_node", foreign_keys="Incident.origin_node_id"
    )
    sos_alerts: Mapped[list["SOS"]] = relationship(  # noqa: F821
        "SOS", back_populates="origin_node", foreign_keys="SOS.origin_node_id"
    )
    outgoing_links: Mapped[list["NodeLink"]] = relationship(  # noqa: F821
        "NodeLink", back_populates="source_node", foreign_keys="NodeLink.source_node_id"
    )
    incoming_links: Mapped[list["NodeLink"]] = relationship(  # noqa: F821
        "NodeLink", back_populates="target_node", foreign_keys="NodeLink.target_node_id"
    )

    def __repr__(self) -> str:
        return f"<Node node_id={self.node_id} status={self.status}>"
