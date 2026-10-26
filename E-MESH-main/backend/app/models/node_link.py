"""
NodeLink model — directed link between two mesh nodes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NodeLinkStatus
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NodeLink(Base):
    __tablename__ = "node_links"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rssi_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    packet_loss_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[NodeLinkStatus] = mapped_column(
        Enum(NodeLinkStatus, native_enum=False), nullable=False, default=NodeLinkStatus.ACTIVE
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relationships ─────────────────────────────────────────────────────
    source_node: Mapped["Node"] = relationship(  # noqa: F821
        "Node", back_populates="outgoing_links", foreign_keys=[source_node_id]
    )
    target_node: Mapped["Node"] = relationship(  # noqa: F821
        "Node", back_populates="incoming_links", foreign_keys=[target_node_id]
    )

    def __repr__(self) -> str:
        return f"<NodeLink {self.source_node_id} → {self.target_node_id} status={self.status}>"
