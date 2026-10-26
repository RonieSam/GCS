"""
User schemas — request/response bodies for the users API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import EmailStr, Field, field_validator

from app.core.enums import UserRole
from app.schemas.common import EMeshBaseModel


class UserCreate(EMeshBaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    email: Optional[EmailStr] = None
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.CIVILIAN

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserRead(EMeshBaseModel):
    id: str
    username: str
    email: Optional[str] = None
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(EMeshBaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None


class UserPasswordChange(EMeshBaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


# ── Auth schemas ──────────────────────────────────────────────────────────────

class LoginRequest(EMeshBaseModel):
    username: str
    password: str


class Token(EMeshBaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class TokenData(EMeshBaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None


class RefreshRequest(EMeshBaseModel):
    refresh_token: str
