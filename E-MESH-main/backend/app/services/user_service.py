"""
User service — CRUD operations for User model.
Business logic lives here, not in route handlers.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


async def get_user_by_id(session: AsyncSession, user_id: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    # Uniqueness checks
    existing_username = await get_user_by_username(session, data.username)
    if existing_username:
        raise AlreadyExistsError("Username", data.username)
    if data.email:
        existing_email = await get_user_by_email(session, data.email)
        if existing_email:
            raise AlreadyExistsError("Email", data.email)

    user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=data.role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def update_user(session: AsyncSession, user_id: str, data: UserUpdate) -> User:
    user = await get_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("User", user_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await session.flush()
    return user


async def change_password(
    session: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.hashed_password):
        from app.core.exceptions import AuthenticationError
        raise AuthenticationError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    await session.flush()


async def list_users(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    role: Optional[UserRole] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Tuple[List[User], int]:
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if search:
        query = query.where(
            (User.username.ilike(f"%{search}%")) | (User.full_name.ilike(f"%{search}%"))
        )
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(User.created_at.desc())
    result = await session.execute(query)
    users = list(result.scalars().all())
    return users, total


async def deactivate_user(session: AsyncSession, user_id: str) -> User:
    user = await get_user_by_id(session, user_id)
    if not user:
        raise NotFoundError("User", user_id)
    user.is_active = False
    await session.flush()
    return user
