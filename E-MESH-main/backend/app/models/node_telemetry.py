"""
NodeTelemetry model — stores historical time-series data for nodes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class NodeTelemetry(Base):
    __tablename__ = "node_telemetry"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    node_id: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False,
        comment="Human-readable node identifier e.g. EM-01"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure_hpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    imu_jerk: Mapped[float | None] = mapped_column(Float, nullable=True)
    accel_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accel_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accel_z: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gyro_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gyro_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gyro_z: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<NodeTelemetry node_id={self.node_id} time={self.timestamp}>"
