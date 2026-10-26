import os
import sys
import time
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from emesh_service import EMeshSurveyCollector, get_emesh_service
from main import app

client = TestClient(app)


def test_survey_collector_lifecycle():
    """Verify state transitions and duplicate click safety."""
    collector = EMeshSurveyCollector(stale_threshold_s=2.0)
    assert collector.state == "IDLE"
    assert not collector.is_active()

    # Start survey
    st = collector.start()
    assert collector.state == "SCANNING"
    assert collector.is_active()
    assert st["state"] == "SCANNING"

    # Duplicate start does not reset or crash
    st2 = collector.start()
    assert collector.state == "SCANNING"

    # Record readings
    r1 = collector.record_reading(node_id="NODE-101", rssi_dbm=-65.2)
    assert r1 is not None
    assert r1["node_id"] == "NODE-101"
    assert r1["rssi_dbm"] == -65.2

    r2 = collector.record_reading(
        node_id="NODE-102",
        parent_id="NODE-101",
        link_id="L-102-101",
        rssi_dbm=-78.0,
        link_quality=85.0,
    )
    assert r2 is not None
    assert r2["parent_id"] == "NODE-101"

    status = collector.get_status()
    assert status["sample_count"] == 2
    assert "NODE-101" in status["latest_readings"]
    assert "NODE-102->NODE-101" in status["latest_readings"]
    assert not status["latest_readings"]["NODE-101"]["is_stale"]

    # Stop survey
    st_stop = collector.stop()
    assert collector.state == "STOPPED"
    assert not collector.is_active()
    assert st_stop["state"] == "STOPPED"

    # Subsequent reading ignored when stopped
    r3 = collector.record_reading(node_id="NODE-101", rssi_dbm=-60.0)
    assert r3 is None
    assert collector.get_status()["sample_count"] == 2

    # Reset survey
    st_reset = collector.reset()
    assert collector.state == "IDLE"
    assert collector.get_status()["sample_count"] == 0


def test_survey_collector_staleness():
    """Verify that readings are accurately marked as stale when older than threshold."""
    collector = EMeshSurveyCollector(stale_threshold_s=0.2)
    collector.start()

    collector.record_reading(node_id="NODE-201", rssi_dbm=-70.0, measurement_time=time.time() - 1.0)
    status = collector.get_status()
    assert status["latest_readings"]["NODE-201"]["is_stale"] is True


def test_api_emesh_status_endpoint():
    """Verify /api/emesh/status responds with expected structure."""
    res = client.get("/api/emesh/status")
    assert res.status_code == 200
    data = res.json()
    assert "connected" in data
    assert "survey" in data
    assert "node_count" in data
    assert "active_sos_count" in data


def test_api_emesh_survey_endpoints():
    """Verify /api/emesh/survey/* controls work via HTTP."""
    # Reset
    res = client.post("/api/emesh/survey/reset")
    assert res.status_code == 200
    assert res.json()["state"] == "IDLE"

    # Start
    res = client.post("/api/emesh/survey/start")
    assert res.status_code == 200
    assert res.json()["state"] == "SCANNING"

    # Status
    res = client.get("/api/emesh/survey/status")
    assert res.status_code == 200
    assert res.json()["is_active"] is True

    # Stop
    res = client.post("/api/emesh/survey/stop")
    assert res.status_code == 200
    assert res.json()["state"] == "STOPPED"

    # Samples
    res = client.get("/api/emesh/survey/samples")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_emesh_data_endpoints():
    """Verify nodes, topology, clients, and sos endpoints return lists/dicts without failing."""
    res_nodes = client.get("/api/emesh/nodes")
    assert res_nodes.status_code == 200
    assert isinstance(res_nodes.json(), list)

    res_topo = client.get("/api/emesh/topology")
    assert res_topo.status_code == 200
    assert isinstance(res_topo.json(), dict)

    res_clients = client.get("/api/emesh/clients")
    assert res_clients.status_code == 200
    assert isinstance(res_clients.json(), list)

    res_sos = client.get("/api/emesh/sos")
    assert res_sos.status_code == 200
    assert isinstance(res_sos.json(), list)
