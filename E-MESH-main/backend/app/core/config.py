"""
Core configuration — reads from environment / .env file.
All application-wide settings are accessed through `get_settings()`.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Security ──────────────────────────────────────────────────────────
    SECRET_KEY: str = secrets.token_urlsafe(64)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./e_mesh.db"

    # ── Server ────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True
    LOG_LEVEL: str = "info"

    # ── CORS ──────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://localhost:8080"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ── Admin Bootstrap ───────────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "Admin@Mesh2025"
    ADMIN_EMAIL: str = "admin@e-mesh.local"
    ADMIN_FULL_NAME: str = "System Administrator"

    # ── Rate Limiting ─────────────────────────────────────────────────────
    SOS_RATE_LIMIT: str = "3/minute"
    API_RATE_LIMIT: str = "100/minute"

    # ── Environment ───────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # ── App Metadata ──────────────────────────────────────────────────────
    APP_NAME: str = "E-Mesh Emergency Mesh"
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
