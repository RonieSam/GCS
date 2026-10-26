"""
Incident model — emergency incident lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import IncidentCategory, IncidentPriority, IncidentStatus
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    incident_id: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, index=True,
        comment="Human-readable incident reference e.g. INC-00042"
    )
    category: Mapped[IncidentCategory] = mapped_column(
        Enum(IncidentCategory, native_enum=False), nullable=False
    )
    priority: Mapped[IncidentPriority] = mapped_column(
        Enum(IncidentPriority, native_enum=False), nullable=False, default=IncidentPriority.MEDIUM
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False), nullable=False, default=IncidentStatus.SUBMITTED
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    people_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    additional_info: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Foreign keys ──────────────────────────────────────────────────────
    reporter_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    origin_node_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_responder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("responders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────
    reporter: Mapped["User | None"] = relationship(  # noqa: F821
        "User", back_populates="incidents", foreign_keys=[reporter_id]
    )
    origin_node: Mapped["Node | None"] = relationship(  # noqa: F821
        "Node", back_populates="incidents", foreign_keys=[origin_node_id]
    )
    assigned_responder: Mapped["Responder | None"] = relationship(  # noqa: F821
        "Responder", back_populates="assigned_incidents", foreign_keys=[assigned_responder_id]
    )
    sos_link: Mapped["SOS | None"] = relationship(  # noqa: F821
        "SOS", back_populates="incident", uselist=False, foreign_keys="SOS.incident_id"
    )

    def __repr__(self) -> str:
        return f"<Incident {self.incident_id} priority={self.priority} status={self.status}>"
