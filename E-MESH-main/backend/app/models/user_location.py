"""
UserLocation model — stores the latest GPS fix per user.
Upsert pattern: one row per user, overwritten on each update.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserLocation(Base):
    __tablename__ = "user_locations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
        comment="One location record per user (upsert)"
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True,
        comment="Accuracy radius in metres")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # Relationship back to User
    user: Mapped["User"] = relationship("User", back_populates="location")  # noqa: F821

    def __repr__(self) -> str:
        return f"<UserLocation user_id={self.user_id} lat={self.latitude:.4f} lng={self.longitude:.4f}>"
