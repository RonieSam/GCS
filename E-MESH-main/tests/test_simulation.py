"""
Tests for ESP-WIFI-MESH network simulation layer and simulation controls.
"""
import pytest
from httpx import AsyncClient

from app.gateway.simulated import get_gateway
from app.models.user import User


@pytest.mark.asyncio
async def test_simulation_initial_seed_topology(client: AsyncClient, admin_token: str):
    """Verify default 6-node tree topology is seeded on startup."""
    resp = await client.get(
        "/api/v1/simulation/topology",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["root_id"] == "GATEWAY"
    assert len(data["nodes"]) >= 6

    node_ids = [n["node_id"] for n in data["nodes"]]
    for expected in ["GATEWAY", "EM-01", "EM-02", "EM-03", "EM-04", "EM-05"]:
        assert expected in node_ids

    assert data["max_depth"] >= 3


@pytest.mark.asyncio
async def test_simulation_network_status(client: AsyncClient, admin_token: str):
    """Verify simulation network status endpoint."""
    resp = await client.get(
        "/api/v1/simulation/network-status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "SIMULATION"
    assert data["protocol_target"] == "ESP-WIFI-MESH"
    assert data["total_nodes"] >= 6
    assert data["online_nodes"] >= 1


@pytest.mark.asyncio
async def test_simulation_node_create_and_delete(client: AsyncClient, admin_token: str):
    """Verify creating a new simulated node and subsequently deleting it."""
    # Create node EM-99 attached to EM-02
    create_resp = await client.post(
        "/api/v1/simulation/nodes",
        json={
            "node_id": "EM-99",
            "parent_id": "EM-02",
            "battery_percent": 95.0,
            "rssi_dbm": -52.0,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["node_id"] == "EM-99"
    assert created_data["parent_id"] == "EM-02"
    assert created_data["layer"] == 3

    # Verify presence in node list
    list_resp = await client.get(
        "/api/v1/simulation/nodes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    node_ids = [n["node_id"] for n in list_resp.json()]
    assert "EM-99" in node_ids

    # Delete node EM-99
    del_resp = await client.delete(
        "/api/v1/simulation/nodes/EM-99",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_simulation_node_offline_and_recovery(client: AsyncClient, admin_token: str):
    """Verify taking a node offline and restoring its operational health."""
    # Take EM-03 offline
    off_resp = await client.post(
        "/api/v1/simulation/nodes/EM-03/offline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert off_resp.status_code == 200

    node_resp = await client.get(
        "/api/v1/simulation/nodes/EM-03",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert node_resp.json()["status"] == "OFFLINE"

    # Restore EM-03
    restore_resp = await client.post(
        "/api/v1/simulation/nodes/EM-03/restore",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert restore_resp.status_code == 200

    node_resp2 = await client.get(
        "/api/v1/simulation/nodes/EM-03",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert node_resp2.json()["status"] == "ONLINE"


@pytest.mark.asyncio
async def test_simulation_parent_change_layer_update(client: AsyncClient, admin_token: str):
    """Verify dynamic tree reconfiguration when a node's parent is modified."""
    # Move EM-05 (layer 3 under EM-02) to become a child of EM-03 (layer 3) -> new layer should be 4
    patch_resp = await client.patch(
        "/api/v1/simulation/nodes/EM-05",
        json={"parent_id": "EM-03"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["parent_id"] == "EM-03"
    assert patched["layer"] == 4
    assert "EM-03" in patched["current_route"]

    # Revert back to EM-02
    await client.patch(
        "/api/v1/simulation/nodes/EM-05",
        json={"parent_id": "EM-02"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


@pytest.mark.asyncio
async def test_simulation_link_degradation(client: AsyncClient, admin_token: str):
    """Verify simulating link degradation between two nodes."""
    resp = await client.post(
        "/api/v1/simulation/links/degrade",
        json={
            "source_node_id": "EM-01",
            "target_node_id": "EM-03",
            "packet_loss_percent": 75.0,
            "latency_ms": 180.0,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_simulation_heartbeat(client: AsyncClient, admin_token: str):
    """Verify manual heartbeat trigger."""
    resp = await client.post(
        "/api/v1/simulation/nodes/EM-02/heartbeat",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_simulation_routes_endpoint(client: AsyncClient, admin_token: str):
    """Verify route resolution to Root Gateway."""
    resp = await client.get(
        "/api/v1/simulation/routes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    routes = resp.json()
    assert "EM-04" in routes
    # EM-04 route should be ["EM-04", "EM-01", "GATEWAY"]
    assert routes["EM-04"] == ["EM-04", "EM-01", "GATEWAY"]
