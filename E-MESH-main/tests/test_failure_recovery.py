"""
Tests for ESP-WIFI-MESH failure scenarios, self-healing parent reassignment, and network analytics.
"""
import pytest
from httpx import AsyncClient

from app.gateway.simulated import get_gateway


@pytest.mark.asyncio
async def test_parent_failure_and_child_self_healing(client: AsyncClient, admin_token: str):
    """
    Test failure workflow:
    1. Parent node EM-01 fails.
    2. Affected children EM-03 & EM-04 detect parent loss.
    3. Self-healing dynamically discovers candidate parent (EM-02 or GATEWAY).
    4. Routes & layers updated.
    5. Recovery time recorded.
    """
    # 1. Trigger parent failure on EM-01
    fail_resp = await client.post(
        "/api/v1/simulation/fail-parent",
        json={"parent_node_id": "EM-01", "auto_reheal": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fail_resp.status_code == 200
    data = fail_resp.json()
    assert data["failed_parent"] == "EM-01"
    assert "EM-03" in data["affected_children"]
    assert "EM-04" in data["affected_children"]
    assert data["recovery_time_ms"] > 0
    assert data["topology_changes"] > 0

    # 2. Verify parent node is OFFLINE
    node_resp = await client.get(
        "/api/v1/simulation/nodes/EM-01",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert node_resp.json()["status"] == "OFFLINE"

    # 3. Verify children re-parented and back ONLINE
    ch3_resp = await client.get(
        "/api/v1/simulation/nodes/EM-03",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ch3_data = ch3_resp.json()
    assert ch3_data["status"] == "ONLINE"
    assert ch3_data["parent_id"] != "EM-01"

    # 4. Clean up / Restore
    await client.post(
        "/api/v1/simulation/restore-network",
        headers={"Authorization": f"Bearer {admin_token}"},
    )


@pytest.mark.asyncio
async def test_gateway_failure_and_network_restoration(client: AsyncClient, admin_token: str):
    """Verify loss of Root Gateway causes mesh degradation, and network restoration recovers it."""
    # 1. Fail gateway
    fail_resp = await client.post(
        "/api/v1/simulation/fail-gateway",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fail_resp.status_code == 200
    assert fail_resp.json()["status"] == "GATEWAY_DOWN"

    # 2. Check gateway status
    gw_resp = await client.get(
        "/api/v1/simulation/nodes/GATEWAY",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert gw_resp.json()["status"] == "OFFLINE"

    # 3. Restore full network
    restore_resp = await client.post(
        "/api/v1/simulation/restore-network",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["status"] == "NETWORK_RESTORED"

    # 4. Check gateway restored
    gw_resp2 = await client.get(
        "/api/v1/simulation/nodes/GATEWAY",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert gw_resp2.json()["status"] == "ONLINE"


@pytest.mark.asyncio
async def test_link_degradation_and_pdr_metrics(client: AsyncClient, admin_token: str):
    """Verify link degradation impacts Packet Delivery Ratio (PDR) and average latency."""
    # Inject heavy degradation on EM-02
    await client.post(
        "/api/v1/simulation/links/degrade",
        json={
            "source_node_id": "EM-02",
            "target_node_id": "EM-05",
            "packet_loss_percent": 80.0,
            "latency_ms": 250.0,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Fetch analytics
    analytics_resp = await client.get(
        "/api/v1/simulation/analytics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert analytics_resp.status_code == 200
    metrics = analytics_resp.json()
    assert metrics["packet_delivery_ratio"] < 100.0
    assert metrics["packet_loss_percent"] > 0.0
    assert metrics["average_latency_ms"] > 0.0

    # Restore
    await client.post(
        "/api/v1/simulation/restore-network",
        headers={"Authorization": f"Bearer {admin_token}"},
    )


@pytest.mark.asyncio
async def test_live_event_timeline_stream(client: AsyncClient, admin_token: str):
    """Verify live event timeline stream contains formatted logs with timestamps and levels."""
    # Trigger a series of actions
    await client.post(
        "/api/v1/simulation/nodes/EM-04/offline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await client.post(
        "/api/v1/simulation/nodes/EM-04/restore",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Fetch timeline
    tl_resp = await client.get(
        "/api/v1/simulation/timeline?limit=20",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert tl_resp.status_code == 200
    events = tl_resp.json()
    assert len(events) >= 2

    event_types = [e["event_type"] for e in events]
    assert "NODE_OFFLINE" in event_types or "NODE_RESTORED" in event_types

    for e in events:
        assert "timestamp" in e
        assert "event_type" in e
        assert "node_id" in e
        assert "message" in e
        assert "level" in e
