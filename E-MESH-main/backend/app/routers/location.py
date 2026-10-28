"""
Location router — GPS position collection and heatmap data endpoints.

POST /location      - Any authenticated user updates their GPS fix
GET  /location/heatmap - Admin/Manager: heatmap of all active users
GET  /location/users   - Admin: full user location list
DELETE /location/me    - User clears their own location record
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.dependencies import get_current_user, get_current_user_optional, get_db, require_roles
from app.core.enums import UserRole
from app.core.ws_manager import emit_event
from app.models.user import User
from app.models.user_location import UserLocation
from app.schemas.common import SuccessResponse
from app.schemas.events import EventType
from app.schemas.location import HeatmapPoint, HeatmapResponse, LocationRead, LocationUpdate
from app.services.audit_service import write_audit

router = APIRouter(prefix="/location", tags=["Location"])

_managers = require_roles(UserRole.ADMIN, UserRole.INCIDENT_MANAGER)
_all_auth = require_roles(
    UserRole.ADMIN, UserRole.INCIDENT_MANAGER,
    UserRole.RESPONDER, UserRole.CIVILIAN, UserRole.VIEWER
)

# In-memory storage for active anonymous client device locations
_anonymous_client_locations: dict[str, dict] = {}


def _to_utc_timestamp(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@router.post("", response_model=SuccessResponse, summary="Update my GPS location")
async def update_my_location(
    body: LocationUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
):
    """
    Upsert the authenticated user or anonymous mesh client's GPS coordinates.
    """
    now = datetime.now(timezone.utc)

    if actor:
        # Try to find existing record
        result = await db.execute(
            select(UserLocation).where(UserLocation.user_id == actor.id)
        )
        existing = result.scalar_one_or_none()

        update_ts = float(body.timestamp) if body.timestamp is not None else now.timestamp()
        if existing and existing.updated_at:
            existing_ts = _to_utc_timestamp(existing.updated_at) or 0.0
            if update_ts < (existing_ts - 0.5):
                return SuccessResponse(message="Stale update ignored")

        loc_time = datetime.fromtimestamp(update_ts, tz=timezone.utc)
        if existing:
            existing.latitude = body.latitude
            existing.longitude = body.longitude
            existing.accuracy = body.accuracy
            existing.updated_at = loc_time
        else:
            new_loc = UserLocation(
                user_id=actor.id,
                latitude=body.latitude,
                longitude=body.longitude,
                accuracy=body.accuracy,
                updated_at=loc_time,
            )
            db.add(new_loc)

        await db.flush()
        await db.commit()

        # Broadcast location update event to admin clients
        emit_event(
            event=EventType.USER_LOCATION_UPDATED,
            data={
                "user_id": actor.id,
                "username": actor.username,
                "role": actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                "latitude": body.latitude,
                "longitude": body.longitude,
                "accuracy": body.accuracy,
                "timestamp": update_ts,
                "updated_at": loc_time.isoformat(),
            },
            scope="admin",
        )
    elif body.client_id:
        cid = body.client_id
        update_ts = float(body.timestamp) if body.timestamp is not None else now.timestamp()
        existing = _anonymous_client_locations.get(cid)
        existing_ts = existing.get("timestamp") if existing else 0.0

        # Reject out-of-order older updates to prevent stale readings from overriding fresh GPS fixes
        if existing and update_ts < (existing_ts - 0.5):
            return SuccessResponse(message="Stale update ignored")

        _anonymous_client_locations[cid] = {
            "client_id": cid,
            "latitude": float(body.latitude),
            "longitude": float(body.longitude),
            "accuracy": float(body.accuracy) if body.accuracy is not None else None,
            "timestamp": update_ts,
            "updated_at": now,
        }
        # Broadcast location update event to admin clients
        emit_event(
            event=EventType.USER_LOCATION_UPDATED,
            data={
                "client_id": cid,
                "username": f"Citizen ({cid[:8]})",
                "role": "CIVILIAN",
                "latitude": float(body.latitude),
                "longitude": float(body.longitude),
                "accuracy": float(body.accuracy) if body.accuracy is not None else None,
                "timestamp": update_ts,
                "updated_at": now.isoformat(),
            },
            scope="admin",
        )

    return SuccessResponse(message="Location updated")



@router.get("/heatmap", response_model=HeatmapResponse, summary="Get user density heatmap")
async def get_heatmap(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(_managers)],
    window_minutes: int = Query(30, ge=1, le=1440, description="Include locations updated in last N minutes"),
):
    """Admin/Manager only. Returns weighted GPS points for heatmap rendering."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    result = await db.execute(
        select(UserLocation, User).join(User, UserLocation.user_id == User.id).where(
            UserLocation.updated_at >= cutoff
        )
    )
    rows = result.all()

    points: list[HeatmapPoint] = []
    lats, lngs = [], []

    for loc, user in rows:
        # Weight by role — responders and managers have higher visual weight
        weight = 1.0
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        if role_str in ("RESPONDER", "INCIDENT_MANAGER"):
            weight = 2.0
        elif role_str == "ADMIN":
            weight = 3.0

        points.append(HeatmapPoint(
            lat=loc.latitude,
            lng=loc.longitude,
            weight=weight,
            user_id=user.id,
            username=user.username,
            role=role_str,
            updated_at=loc.updated_at.isoformat(),
        ))
        lats.append(loc.latitude)
        lngs.append(loc.longitude)

    bounds = None
    if lats:
        bounds = {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lng": min(lngs),
            "max_lng": max(lngs),
        }

    return HeatmapResponse(
        points=points,
        total_active=len(points),
        bounds=bounds,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/users", response_model=list[LocationRead], summary="Get all user locations")
async def get_location_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[Optional[User], Depends(get_current_user_optional)] = None,
    window_minutes: int = Query(30, ge=1, le=1440),
):
    """Full list of active users and mesh clients with their latest GPS fix."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    result = await db.execute(
        select(UserLocation, User).join(User, UserLocation.user_id == User.id).where(
            UserLocation.updated_at >= cutoff
        ).order_by(UserLocation.updated_at.desc())
    )
    rows = result.all()

    items = [
        LocationRead(
            id=loc.id,
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            latitude=loc.latitude,
            longitude=loc.longitude,
            accuracy=loc.accuracy,
            client_id=None,
            timestamp=_to_utc_timestamp(loc.updated_at),
            updated_at=loc.updated_at,
        )
        for loc, user in rows
    ]

    # Include anonymous mesh clients reporting GPS
    for cid, data in _anonymous_client_locations.items():
        up_at = data.get("updated_at")
        if up_at and up_at >= cutoff:
            items.append(
                LocationRead(
                    id=f"client-{cid}",
                    user_id=cid,
                    username=f"Citizen ({cid[:8]})",
                    full_name=f"Mesh Client {cid[:8]}",
                    role="CIVILIAN",
                    latitude=data["latitude"],
                    longitude=data["longitude"],
                    accuracy=data.get("accuracy"),
                    client_id=cid,
                    timestamp=data.get("timestamp"),
                    updated_at=up_at,
                )
            )

    return items



@router.delete("/me", response_model=SuccessResponse, summary="Clear my location")
async def clear_my_location(
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
):
    """Allows user to opt-out and remove their location record."""
    result = await db.execute(
        select(UserLocation).where(UserLocation.user_id == actor.id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return SuccessResponse(message="Location cleared")
