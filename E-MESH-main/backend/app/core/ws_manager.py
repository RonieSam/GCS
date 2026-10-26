"""
Centralized WebSocket Connection Manager & Real-Time Event Bus.

Supports:
- Multi-client connection tracking
- Role-based event filtering (RBAC at the socket layer)
- Targeted user messaging (civilian notifications)
- Non-blocking background event emission
- Graceful disconnect & heartbeat ping/pong handling
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.core.enums import UserRole
from app.models.user import User
from app.schemas.events import EventEnvelope, EventType

logger = logging.getLogger(__name__)


@dataclass
class ConnectedClient:
    websocket: WebSocket
    user: Optional[User] = None
    client_id: Optional[str] = None


class ConnectionManager:
    """
    Central connection manager for all active WebSocket sessions.
    Decoupled from wireless protocols (ESP-WIFI-MESH ready).
    """

    def __init__(self) -> None:
        self._active_clients: Set[WebSocket] = set()
        self._client_map: Dict[WebSocket, ConnectedClient] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._active_clients)

    async def connect(
        self,
        websocket: WebSocket,
        user: Optional[User] = None,
        client_id: Optional[str] = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._active_clients.add(websocket)
            self._client_map[websocket] = ConnectedClient(
                websocket=websocket, user=user, client_id=client_id
            )
        username = user.username if user else "anonymous"
        role = user.role.value if user else "PUBLIC"
        logger.info(
            "WebSocket connected: %s (role=%s). Total active: %d",
            username,
            role,
            len(self._active_clients),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active_clients.discard(websocket)
            client = self._client_map.pop(websocket, None)
        username = client.user.username if client and client.user else "anonymous"
        logger.info(
            "WebSocket disconnected: %s. Total active: %d",
            username,
            len(self._active_clients),
        )

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.debug("Failed to send personal message to websocket: %s", e)
            await self.disconnect(websocket)

    async def broadcast_event(
        self,
        event: EventType,
        data: Dict[str, Any],
        target_roles: Optional[List[UserRole]] = None,
        target_user_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> None:
        """
        Broadcast a typed event envelope to eligible connected clients.
        
        Filtering rules:
        1. If target_roles is None and target_user_id is None -> Public event (all clients receive).
        2. If target_roles is specified -> Only clients with matching user.role receive.
        3. If target_user_id is specified -> Client with user.id == target_user_id also receives.
        """
        envelope = EventEnvelope(
            event=event,
            data=data,
            scope=scope or ("public" if not target_roles and not target_user_id else "restricted"),
        )
        msg_text = json.dumps(envelope.model_dump())

        async with self._lock:
            clients_snapshot = list(self._client_map.values())

        disconnected: List[WebSocket] = []

        for client in clients_snapshot:
            # Check eligibility
            is_eligible = False

            # Public event
            if target_roles is None and target_user_id is None:
                is_eligible = True
            else:
                # Check user ID match
                if target_user_id and client.user and str(client.user.id) == str(target_user_id):
                    is_eligible = True
                # Check role match or GCS admin bridge
                elif client.client_id == "gcs" or (client.user and (client.user.role in target_roles or client.user.role == UserRole.ADMIN)):
                    is_eligible = True

            if is_eligible:
                try:
                    await client.websocket.send_text(msg_text)
                except Exception as e:
                    logger.debug("Error sending event to client %s: %s", client.user, e)
                    disconnected.append(client.websocket)

        if disconnected:
            for ws in disconnected:
                await self.disconnect(ws)


# Global singleton instance
ws_manager = ConnectionManager()


def emit_event(
    event: EventType,
    data: Dict[str, Any],
    target_roles: Optional[List[UserRole]] = None,
    target_user_id: Optional[str] = None,
    scope: Optional[str] = None,
) -> None:
    """
    Non-blocking fire-and-forget helper to dispatch a WebSocket event.
    Guarantees REST endpoints and database transactions are never blocked.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            ws_manager.broadcast_event(
                event=event,
                data=data,
                target_roles=target_roles,
                target_user_id=target_user_id,
                scope=scope,
            )
        )
    except RuntimeError:
        # Loop may not be running in some test sync contexts
        pass
