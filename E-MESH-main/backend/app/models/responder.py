"""
Responder model — emergency responder profile linked to a User.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ResponderStatus
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Responder(Base):
    __tablename__ = "responders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    team: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[ResponderStatus] = mapped_column(
        Enum(ResponderStatus, native_enum=False), nullable=False, default=ResponderStatus.AVAILABLE
    )
    zone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relationships ─────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="responder_profile")  # noqa: F821
    assigned_incidents: Mapped[list["Incident"]] = relationship(  # noqa: F821
        "Incident", back_populates="assigned_responder", foreign_keys="Incident.assigned_responder_id"
    )

    def __repr__(self) -> str:
        return f"<Responder id={self.id} status={self.status}>"
