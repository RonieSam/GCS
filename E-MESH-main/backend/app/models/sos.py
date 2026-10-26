"""
SOS model — emergency SOS alert, distinct from a general incident.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SOSStatus
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SOS(Base):
    __tablename__ = "sos_alerts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    sos_id: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, index=True,
        comment="Human-readable SOS reference e.g. SOS-00007"
    )
    status: Mapped[SOSStatus] = mapped_column(
        Enum(SOSStatus, native_enum=False), nullable=False, default=SOSStatus.ACTIVE
    )
    people_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # ── Foreign keys ──────────────────────────────────────────────────────
    reporter_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    incident_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    origin_node_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )


    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────
    reporter: Mapped["User | None"] = relationship(  # noqa: F821
        "User", back_populates="sos_alerts", foreign_keys=[reporter_id]
    )
    incident: Mapped["Incident | None"] = relationship(  # noqa: F821
        "Incident", back_populates="sos_link", foreign_keys=[incident_id]
    )
    origin_node: Mapped["Node | None"] = relationship(  # noqa: F821
        "Node", back_populates="sos_alerts", foreign_keys=[origin_node_id]
    )

    def __repr__(self) -> str:
        return f"<SOS {self.sos_id} status={self.status}>"
