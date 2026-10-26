"""
Tests for SOS endpoints including cooldown protection.
"""
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_create_sos(client: AsyncClient, civilian_user: User, civilian_token: str):
    resp = await client.post(
        "/api/v1/sos",
        json={"people_count": 3, "notes": "Trapped in building."},
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["sos_id"].startswith("SOS-")
    assert data["status"] == "ACTIVE"
    assert data["people_count"] == 3
    assert data["incident_id"] is not None


@pytest.mark.asyncio
async def test_sos_cooldown(client: AsyncClient, admin_user: User, admin_token: str):
    """
    Second SOS within cooldown window should return 429.
    Uses a separate admin user so it doesn't clash with other test SOS.
    """
    # First SOS
    first_resp = await client.post(
        "/api/v1/sos",
        json={"people_count": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first_resp.status_code == 201

    # Immediate second SOS — should be blocked by cooldown
    second_resp = await client.post(
        "/api/v1/sos",
        json={"people_count": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second_resp.status_code == 429
    data = second_resp.json()
    assert "cooldown" in data["message"].lower() or "seconds" in data["message"].lower()


@pytest.mark.asyncio
async def test_list_sos_as_manager(
    client: AsyncClient,
    manager_user: User,
    manager_token: str,
    civilian_user: User,
    civilian_token: str,
):
    await client.post(
        "/api/v1/sos",
        json={"people_count": 2},
        headers={"Authorization": f"Bearer {civilian_token}"},
    )

    resp = await client.get(
        "/api/v1/sos",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_civilian_sees_only_own_sos(
    client: AsyncClient,
    civilian_user: User,
    civilian_token: str,
):
    resp = await client.get(
        "/api/v1/sos",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 200
    for sos in resp.json()["data"]:
        assert sos["reporter_id"] == civilian_user.id


@pytest.mark.asyncio
async def test_update_sos_status(
    client: AsyncClient,
    manager_user: User,
    manager_token: str,
    responder_user: User,
):
    """Manager can acknowledge and resolve SOS."""
    # Manager creates a user and SOS via admin endpoint
    # For simplicity, use manager to create SOS (all authenticated users can)
    create_resp = await client.post(
        "/api/v1/sos",
        json={"people_count": 1},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    sos_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/sos/{sos_id}",
        json={"status": "ACKNOWLEDGED"},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "ACKNOWLEDGED"
    assert update_resp.json()["acknowledged_at"] is not None
