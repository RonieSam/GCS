"""
Tests for the users API with RBAC.
"""
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_list_users_as_admin(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_list_users_as_civilian_forbidden(
    client: AsyncClient, civilian_user: User, civilian_token: str
):
    resp = await client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_user_as_admin(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.post(
        "/api/v1/users",
        json={
            "username": "new_user_xyz",
            "full_name": "New User",
            "password": "NewPass@123",
            "role": "CIVILIAN",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "new_user_xyz"
    assert data["role"] == "CIVILIAN"
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_create_user_duplicate_username(
    client: AsyncClient, admin_user: User, admin_token: str
):
    # First creation
    await client.post(
        "/api/v1/users",
        json={"username": "dupe_user_test", "full_name": "Dupe", "password": "Dupe@1234"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Second creation should conflict
    resp = await client.post(
        "/api/v1/users",
        json={"username": "dupe_user_test", "full_name": "Dupe2", "password": "Dupe@1234"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_user_weak_password(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.post(
        "/api/v1/users",
        json={"username": "weakpass_user", "full_name": "Weak", "password": "password"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_user_by_id(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.get(
        f"/api/v1/users/{admin_user.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == admin_user.id


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.get(
        "/api/v1/users/nonexistent-id-000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_user(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.patch(
        f"/api/v1/users/{admin_user.id}",
        json={"full_name": "Updated Name"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_deactivate_user(
    client: AsyncClient, admin_user: User, admin_token: str, civilian_user: User
):
    resp = await client.delete(
        f"/api/v1/users/{civilian_user.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
