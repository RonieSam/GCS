"""
Tests for incident management API with RBAC.
"""
import pytest
from httpx import AsyncClient

from app.models.user import User


INCIDENT_PAYLOAD = {
    "category": "MEDICAL",
    "priority": "HIGH",
    "description": "Person injured near sector 4 requires immediate medical attention.",
    "people_affected": 2,
}


@pytest.mark.asyncio
async def test_create_incident_as_civilian(
    client: AsyncClient, civilian_user: User, civilian_token: str
):
    resp = await client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["category"] == "MEDICAL"
    assert data["status"] == "SUBMITTED"
    assert data["incident_id"].startswith("INC-")
    return data["id"]


@pytest.mark.asyncio
async def test_civilian_sees_only_own_incidents(
    client: AsyncClient,
    civilian_user: User,
    civilian_token: str,
    admin_user: User,
    admin_token: str,
):
    # Civilian creates one incident
    await client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Authorization": f"Bearer {civilian_token}"},
    )

    # Admin creates one incident
    await client.post(
        "/api/v1/incidents",
        json={**INCIDENT_PAYLOAD, "description": "Admin-created incident for testing purposes."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Civilian should only see their own
    resp = await client.get(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    for incident in data["data"]:
        assert incident["reporter_id"] == civilian_user.id


@pytest.mark.asyncio
async def test_admin_sees_all_incidents(
    client: AsyncClient, admin_user: User, admin_token: str, civilian_user: User, civilian_token: str
):
    # Create an incident as civilian
    await client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Authorization": f"Bearer {civilian_token}"},
    )

    resp = await client.get(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    # Admin should see at least 1
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_acknowledge_incident(
    client: AsyncClient,
    manager_user: User,
    manager_token: str,
    civilian_user: User,
    civilian_token: str,
):
    create_resp = await client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    incident_id = create_resp.json()["id"]

    ack_resp = await client.post(
        f"/api/v1/incidents/{incident_id}/acknowledge",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "ACKNOWLEDGED"
    assert ack_resp.json()["acknowledged_at"] is not None


@pytest.mark.asyncio
async def test_civilian_cannot_acknowledge(
    client: AsyncClient,
    civilian_user: User,
    civilian_token: str,
):
    create_resp = await client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    incident_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/acknowledge",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_incident_priority_filter(
    client: AsyncClient,
    admin_user: User,
    admin_token: str,
):
    await client.post(
        "/api/v1/incidents",
        json={**INCIDENT_PAYLOAD, "priority": "CRITICAL", "description": "Critical test incident for filtering."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get(
        "/api/v1/incidents?priority=CRITICAL",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    for incident in resp.json()["data"]:
        assert incident["priority"] == "CRITICAL"


@pytest.mark.asyncio
async def test_get_incident_not_found(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.get(
        "/api/v1/incidents/nonexistent-000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
