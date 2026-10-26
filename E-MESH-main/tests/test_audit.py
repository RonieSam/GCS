"""
Tests for audit log API.
"""
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_audit_log_created_on_login(
    client: AsyncClient, admin_user: User, admin_token: str
):
    """Login creates an audit entry visible in the audit log."""
    resp = await client.get(
        "/api/v1/audit-logs?action=auth.login",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    actions = [log["action"] for log in data["data"]]
    assert "auth.login" in actions


@pytest.mark.asyncio
async def test_audit_log_created_on_incident(
    client: AsyncClient,
    admin_user: User,
    admin_token: str,
):
    await client.post(
        "/api/v1/incidents",
        json={
            "category": "FIRE_HAZARD",
            "description": "Audit test - fire incident near area 5.",
            "people_affected": 1,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get(
        "/api/v1/audit-logs?action=incident.created",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_civilian_cannot_read_audit_logs(
    client: AsyncClient, civilian_user: User, civilian_token: str
):
    resp = await client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_pagination(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.get(
        "/api/v1/audit-logs?page=1&page_size=5",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) <= 5
    assert data["page"] == 1
    assert data["page_size"] == 5
