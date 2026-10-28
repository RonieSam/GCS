"""
Tests for user location updates, timestamp tracking, out-of-order rejection,
and geospatial precision preservation in the E-MESH backend.
"""
import time
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_update_location_precision_and_timestamp(
    client: AsyncClient, civilian_user: User, civilian_token: str
):
    """Verify full float precision, accuracy, and client timestamp are preserved."""
    now_ts = time.time()
    lat = 13.082684
    lon = 80.270718
    acc = 4.25

    resp = await client.post(
        "/api/v1/location",
        json={
            "latitude": lat,
            "longitude": lon,
            "accuracy": acc,
            "timestamp": now_ts,
        },
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Location updated"

    # Query GET /location/users to verify stored values
    users_resp = await client.get(
        "/api/v1/location/users",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert users_resp.status_code == 200
    records = [u for u in users_resp.json() if u.get("user_id") == civilian_user.id]
    assert len(records) == 1
    data = records[0]
    assert abs(data["latitude"] - lat) < 1e-6
    assert abs(data["longitude"] - lon) < 1e-6
    assert abs(data["accuracy"] - acc) < 1e-3
    assert data["timestamp"] is not None
    assert abs(data["timestamp"] - now_ts) < 1e-3


@pytest.mark.asyncio
async def test_stale_location_packet_rejected(
    client: AsyncClient, civilian_user: User, civilian_token: str
):
    """A location update with an older timestamp does not overwrite a newer position."""
    t_new = time.time()
    t_old = t_new - 30.0

    # 1. Send fresh location
    resp1 = await client.post(
        "/api/v1/location",
        json={
            "latitude": 13.083000,
            "longitude": 80.273000,
            "accuracy": 5.0,
            "timestamp": t_new,
        },
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp1.status_code == 200

    # 2. Send older/stale location (delayed arrival)
    resp2 = await client.post(
        "/api/v1/location",
        json={
            "latitude": 12.900000,
            "longitude": 80.100000,
            "accuracy": 150.0,
            "timestamp": t_old,
        },
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["message"] == "Stale update ignored"

    # 3. Verify that the newer location remains in storage
    users_resp = await client.get(
        "/api/v1/location/users",
        headers={"Authorization": f"Bearer {civilian_token}"},
    )
    assert users_resp.status_code == 200
    records = [u for u in users_resp.json() if u.get("user_id") == civilian_user.id]
    assert len(records) == 1
    assert abs(records[0]["latitude"] - 13.083000) < 1e-6
    assert abs(records[0]["longitude"] - 80.273000) < 1e-6
