"""
Health check router — public endpoint for load balancers and monitors.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", summary="Basic health check")
async def health_check():
    return {
        "status": "ok",
        "service": "E-Mesh Emergency Mesh API",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/db", summary="Database connectivity check")
async def db_health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": "unavailable", "detail": str(exc)}
