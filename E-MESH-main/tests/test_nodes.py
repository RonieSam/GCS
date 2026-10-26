"""
Tests for node management API.
"""
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_create_node_as_admin(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.post(
        "/api/v1/nodes",
        json={"node_id": "TEST-01", "display_name": "Test Node 1", "is_gateway": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["node_id"] == "TEST-01"
    assert data["status"] == "UNKNOWN"
    return data["id"]


@pytest.mark.asyncio
async def test_create_node_duplicate(client: AsyncClient, admin_user: User, admin_token: str):
    await client.post(
        "/api/v1/nodes",
        json={"node_id": "DUPE-NODE-01"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.post(
        "/api/v1/nodes",
        json={"node_id": "DUPE-NODE-01"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_nodes(client: AsyncClient, admin_user: User, admin_token: str):
    # Ensure at least one node exists
    await client.post(
        "/api/v1/nodes",
        json={"node_id": "LIST-NODE-01"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get(
        "/api/v1/nodes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_update_node(client: AsyncClient, admin_user: User, admin_token: str):
    create_resp = await client.post(
        "/api/v1/nodes",
        json={"node_id": "UPDATE-NODE-01"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    node_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/nodes/{node_id}",
        json={"status": "ONLINE", "battery_percent": 85.5},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ONLINE"
    assert data["battery_percent"] == 85.5


@pytest.mark.asyncio
async def test_delete_node(client: AsyncClient, admin_user: User, admin_token: str):
    create_resp = await client.post(
        "/api/v1/nodes",
        json={"node_id": "DELETE-NODE-01"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    node_id = create_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 200

    get_resp = await client.get(
        f"/api/v1/nodes/{node_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_civilian_cannot_create_node(
    client: AsyncClient, civilian_user: User, civilian_token: str
):
    resp = await client.post(
        "/api/v1/nodes",
        json={"node_id": "CIVIL-NODE"},
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 403
