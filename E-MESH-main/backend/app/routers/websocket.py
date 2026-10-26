"""
WebSocket router — manages real-time socket connections and message loops.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.security import decode_token
from app.core.ws_manager import ws_manager
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


def _resolve_user_from_token(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        role_str = payload.get("role")
        user_id = payload.get("uid")
        if not username or not role_str:
            return None
        
        # Construct lightweight user object
        user = User(
            id=user_id or username,
            username=username,
            role=UserRole(role_str) if isinstance(role_str, str) else role_str,
            is_active=True,
        )
        return user
    except Exception as e:
        logger.debug("Failed to resolve user from token: %s", e)
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    client_type: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time telemetry and event streaming.
    Supports ?token=<jwt_access_token> query parameter for authenticated roles,
    and ?client_type=gcs for local GCS Ground Control Station integration.
    """
    user = _resolve_user_from_token(token)
    cid = "gcs" if client_type == "gcs" else None
    if not user and client_type == "gcs":
        user = User(
            id="gcs-system",
            username="GCS-Gateway",
            role=UserRole.ADMIN,
            is_active=True,
        )
    await ws_manager.connect(websocket, user=user, client_id=cid)

    try:
        # Send initial connected greeting
        await websocket.send_text(
            json.dumps({
                "event": "connected",
                "authenticated": user is not None,
                "user": user.username if user else None,
                "role": user.role.value if user else "PUBLIC",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        )

        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
                msg_type = data.get("type", "").lower()

                # Handle Ping/Pong Heartbeat
                if msg_type == "ping":
                    await websocket.send_text(
                        json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    )
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
        await ws_manager.disconnect(websocket)
