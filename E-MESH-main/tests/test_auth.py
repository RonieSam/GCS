"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_register_civilian_success(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "new_civilian",
            "password": "Password123",
            "full_name": "New Civilian",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "new_civilian"
    assert data["role"] == "CIVILIAN"
    assert "id" in data


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, admin_user: User):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "test_admin", "password": "Test@1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, admin_user: User):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "test_admin", "password": "WrongPass123"},
    )
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "nonexistent_xyz", "password": "Test@1234"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "test_admin"
    assert data["role"] == "ADMIN"


@pytest.mark.asyncio
async def test_get_me_no_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer notarealtoken.xyz.abc"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh(client: AsyncClient, admin_user: User):
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "test_admin", "password": "Test@1234"},
    )
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]

    refresh_resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    # Refresh must return valid access and refresh tokens
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, admin_user: User, admin_token: str):
    resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
