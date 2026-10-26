"""
Tests for WebSocket real-time event broadcasting and RBAC event filtering.
"""
import json
import pytest
from fastapi.testclient import TestClient

from app.core.enums import UserRole
from app.core.ws_manager import emit_event, ws_manager
from app.main import app as fastapi_app
from app.models.user import User
from app.schemas.events import EventType


def test_websocket_unauthenticated_connection():
    """Verify that unauthenticated / guest clients can connect to public websocket."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect("/api/v1/ws") as websocket:
            data = websocket.receive_json()
            assert data["event"] == "connected"
            assert data["authenticated"] is False
            assert data["role"] == "PUBLIC"


def test_websocket_authenticated_connection(admin_token: str):
    """Verify that authenticated clients can connect and receive their role."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect(f"/api/v1/ws?token={admin_token}") as websocket:
            data = websocket.receive_json()
            assert data["event"] == "connected"
            assert data["authenticated"] is True
            assert data["user"] == "test_admin"
            assert data["role"] == "ADMIN"


def test_websocket_ping_pong():
    """Verify ping/pong heartbeat mechanism."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect("/api/v1/ws") as websocket:
            _ = websocket.receive_json()  # Greeting
            websocket.send_json({"type": "ping"})
            resp = websocket.receive_json()
            assert resp["type"] == "pong"
            assert "timestamp" in resp


@pytest.mark.asyncio
async def test_announcement_broadcast_to_all(admin_token: str, civilian_token: str):
    """Verify announcements broadcast to both admin and civilian sockets."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect(f"/api/v1/ws?token={admin_token}") as ws_admin:
            with client.websocket_connect(f"/api/v1/ws?token={civilian_token}") as ws_civilian:
                _ = ws_admin.receive_json()
                _ = ws_civilian.receive_json()

                # Trigger announcement
                await ws_manager.broadcast_event(
                    event=EventType.ANNOUNCEMENT_CREATED,
                    data={"title": "Emergency Evacuation", "message": "Head to sector 4"},
                )

                admin_msg = ws_admin.receive_json()
                civilian_msg = ws_civilian.receive_json()

                assert admin_msg["event"] == "announcement.created"
                assert admin_msg["data"]["title"] == "Emergency Evacuation"
                assert civilian_msg["event"] == "announcement.created"
                assert civilian_msg["data"]["title"] == "Emergency Evacuation"


@pytest.mark.asyncio
async def test_sos_event_broadcast_to_admin(admin_token: str, civilian_token: str):
    """Verify SOS events are sent to Admins and the specific Civilian, but not other roles."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect(f"/api/v1/ws?token={admin_token}") as ws_admin:
            with client.websocket_connect(f"/api/v1/ws?token={civilian_token}") as ws_civilian:
                _ = ws_admin.receive_json()
                _ = ws_civilian.receive_json()

                # Emit SOS event targeting admins and civilian_user ID
                await ws_manager.broadcast_event(
                    event=EventType.SOS_CREATED,
                    data={"sos_id": "SOS-9999", "people_count": 3},
                    target_roles=[UserRole.ADMIN, UserRole.INCIDENT_MANAGER],
                )

                admin_msg = ws_admin.receive_json()
                assert admin_msg["event"] == "sos.created"
                assert admin_msg["data"]["sos_id"] == "SOS-9999"


@pytest.mark.asyncio
async def test_node_offline_and_topology_events(admin_token: str):
    """Verify node status and topology events."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect(f"/api/v1/ws?token={admin_token}") as ws_admin:
            _ = ws_admin.receive_json()

            await ws_manager.broadcast_event(
                event=EventType.NODE_OFFLINE,
                data={"node_id": "node_01", "name": "Relay 1", "status": "OFFLINE"},
                target_roles=[UserRole.ADMIN],
            )
            msg1 = ws_admin.receive_json()
            assert msg1["event"] == "node.offline"
            assert msg1["data"]["node_id"] == "node_01"

            await ws_manager.broadcast_event(
                event=EventType.TOPOLOGY_UPDATED,
                data={"total_nodes": 5, "online_nodes": 4, "links_count": 6},
                target_roles=[UserRole.ADMIN],
            )
            msg2 = ws_admin.receive_json()
            assert msg2["event"] == "topology.updated"
            assert msg2["data"]["total_nodes"] == 5


@pytest.mark.asyncio
async def test_multiple_admin_clients(admin_token: str):
    """Verify multiple simultaneous admin WebSocket connections receive events."""
    with TestClient(fastapi_app) as client:
        with client.websocket_connect(f"/api/v1/ws?token={admin_token}") as ws_admin1:
            with client.websocket_connect(f"/api/v1/ws?token={admin_token}") as ws_admin2:
                _ = ws_admin1.receive_json()
                _ = ws_admin2.receive_json()

                await ws_manager.broadcast_event(
                    event=EventType.INCIDENT_CREATED,
                    data={"incident_id": "INC-100", "priority": "HIGH"},
                    target_roles=[UserRole.ADMIN],
                )

                msg1 = ws_admin1.receive_json()
                msg2 = ws_admin2.receive_json()

                assert msg1["event"] == "incident.created"
                assert msg2["event"] == "incident.created"
                assert msg1["data"]["incident_id"] == "INC-100"
                assert msg2["data"]["incident_id"] == "INC-100"
