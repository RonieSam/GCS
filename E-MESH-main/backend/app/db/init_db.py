"""
Database initialization — create tables and seed bootstrap data.
Called from application lifespan.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.security import hash_password
from app.db.base import AsyncSessionLocal, Base, engine

logger = logging.getLogger(__name__)
settings = get_settings()


async def create_tables() -> None:
    """Create all SQLAlchemy model tables (DDL)."""
    # Import models so Base.metadata knows about them
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified.")


async def seed_admin_user(session: AsyncSession) -> None:
    """Ensure the bootstrap ADMIN user exists."""
    from app.models.user import User

    result = await session.execute(
        select(User).where(User.username == settings.ADMIN_USERNAME)
    )
    existing = result.scalar_one_or_none()
    if existing:
        logger.info("Admin user already exists — skipping seed.")
        return

    admin = User(
        username=settings.ADMIN_USERNAME,
        email=settings.ADMIN_EMAIL,
        full_name=settings.ADMIN_FULL_NAME,
        hashed_password=hash_password(settings.ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(admin)
    await session.commit()
    logger.info("Bootstrap admin user created: %s", settings.ADMIN_USERNAME)


async def init_db() -> None:
    """Create tables and seed initial data."""
    await create_tables()
    async with AsyncSessionLocal() as session:
        await seed_admin_user(session)
