"""
Announcement model — emergency broadcast messages.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AnnouncementPriority, AnnouncementTarget
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[AnnouncementPriority] = mapped_column(
        Enum(AnnouncementPriority, native_enum=False), nullable=False,
        default=AnnouncementPriority.NORMAL
    )
    target: Mapped[AnnouncementTarget] = mapped_column(
        Enum(AnnouncementTarget, native_enum=False), nullable=False,
        default=AnnouncementTarget.ALL_USERS
    )
    target_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────
    creator: Mapped["User | None"] = relationship(  # noqa: F821
        "User", back_populates="announcements_created"
    )

    def __repr__(self) -> str:
        return f"<Announcement id={self.id} priority={self.priority} title={self.title!r}>"
