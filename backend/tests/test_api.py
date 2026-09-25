"""
Phase 5 API tests. Run from backend/:

    python3 -m unittest tests.test_api -v

Uses FastAPI's TestClient (in-process, no real server/socket needed) and
resets the SQLite DB before each test so mission-history assertions don't
depend on test execution order.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import database
from main import app, session_state

# Irregular hexagon shared with the Phase 3/4 demos — large enough to
# produce a real gap area against the far-away test nodes.
POLYGON = [
    {"lat": 13.0900, "lon": 80.2650},
    {"lat": 13.0920, "lon": 80.2760},
    {"lat": 13.0850, "lon": 80.2830},
    {"lat": 13.0760, "lon": 80.2800},
    {"lat": 13.0740, "lon": 80.2700},
    {"lat": 13.0800, "lon": 80.2630},
]


class ApiTestCase(unittest.TestCase):
    """Base class: fresh DB + fresh in-process session state per test."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()  # trigger startup (init_db)
        database.reset_db_for_tests()
        session_state.update(
            {
                "polygon": None,
                "last_coverage": None,
                "last_candidates": None,
                "last_scored": None,
                "selected_target": None,
                "mission_state": "PLANNING",
            }
        )

    def tearDown(self):
        self.client.__exit__(None, None, None)


class TestStatusAndNodes(ApiTestCase):
    def test_status_ok_before_any_area(self):
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertGreaterEqual(body["phase"], 7)
        self.assertFalse(body["area_defined"])
        # No real SITL in the test environment, so the background MAVLink
        # connection attempt (started at app startup) hasn't — and won't —
        # succeed; link_state should honestly reflect that rather than
        # claiming a connection that doesn't exist.
        self.assertFalse(body["uav_connected"])
        self.assertIn(body["link_state"], ("DISCONNECTED", "CONNECTING"))

    def test_nodes_empty_initially_and_deployable(self):
        r = self.client.get("/api/nodes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 0)
        # Deploy a node
        r_post = self.client.post("/api/nodes", json={"id": "NODE-001", "lat": 13.0827, "lon": 80.2707})
        self.assertEqual(r_post.status_code, 200)
        r2 = self.client.get("/api/nodes")
        self.assertEqual(len(r2.json()), 1)

    def test_vehicle_state_before_any_connection(self):
        r = self.client.get("/api/vehicle/state")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["connected"])
        self.assertIsNone(body["latitude"])
        self.assertIsNone(body["mode"])


class TestArea(ApiTestCase):
    def test_valid_area_accepted(self):
        r = self.client.post("/api/area", json={"polygon": POLYGON})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["point_count"], 6)

    def test_too_few_points_rejected(self):
        r = self.client.post("/api/area", json={"polygon": POLYGON[:2]})
        self.assertEqual(r.status_code, 422)  # pydantic min_length validation

    def test_new_area_invalidates_prior_analysis(self):
        self.client.post("/api/area", json={"polygon": POLYGON})
        self.client.post("/api/analyze")
        # Submitting a new area should reset last_analysis_available.
        self.client.post("/api/area", json={"polygon": POLYGON})
        r = self.client.get("/api/status")
        self.assertFalse(r.json()["last_analysis_available"])


class TestAnalyze(ApiTestCase):
    def test_analyze_without_area_rejected(self):
        r = self.client.post("/api/analyze")
        self.assertEqual(r.status_code, 400)

    def test_analyze_after_area_returns_percentages(self):
        self.client.post("/api/area", json={"polygon": POLYGON})
        r = self.client.post("/api/analyze")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertAlmostEqual(body["coverage_percentage"] + body["gap_percentage"], 100.0, places=3)
        self.assertGreater(body["total_points"], 0)


class TestCandidates(ApiTestCase):
    def test_candidates_without_analyze_rejected(self):
        self.client.post("/api/area", json={"polygon": POLYGON})
        r = self.client.get("/api/candidates")
        self.assertEqual(r.status_code, 400)

    def test_candidates_after_analyze_returns_top_2(self):
        self.client.post("/api/area", json={"polygon": POLYGON})
        self.client.post("/api/analyze")
        r = self.client.get("/api/candidates")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["candidates"]), 5)
        self.assertEqual(len(body["top"]), 2)
        # Top list should be the two highest-scoring candidates.
        scores = [c["score"] for c in body["candidates"]]
        self.assertEqual(body["top"][0]["score"], max(scores))


class TestSelectTargetAndMission(ApiTestCase):
    def _setup_area_and_candidates(self):
        self.client.post("/api/area", json={"polygon": POLYGON})
        self.client.post("/api/analyze")
        return self.client.get("/api/candidates").json()

    def test_select_target_outside_area_rejected(self):
        self._setup_area_and_candidates()
        r = self.client.post("/api/select-target", json={"lat": 0.0, "lon": 0.0})
        self.assertEqual(r.status_code, 400)

    def test_select_target_too_close_to_node_rejected(self):
        self.client.post("/api/area", json={"polygon": POLYGON})
        self.client.post("/api/nodes", json={"id": "NODE-001", "lat": 13.0827, "lon": 80.2707})
        node = self.client.get("/api/nodes").json()[0]
        r = self.client.post("/api/select-target", json={"lat": node["lat"], "lon": node["lon"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("too close", r.json()["detail"])

    def test_select_target_matches_candidate(self):
        candidates = self._setup_area_and_candidates()
        top = candidates["top"][0]
        r = self.client.post("/api/select-target", json={"lat": top["lat"], "lon": top["lon"]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["matched_candidate"])

    def test_mission_generate_creates_persisted_mission(self):
        candidates = self._setup_area_and_candidates()
        top = candidates["top"][0]
        r = self.client.post("/api/mission/generate", json={"lat": top["lat"], "lon": top["lon"]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "MISSION_READY")
        self.assertEqual(body["target_alt"], 15)  # DEFAULT_ALTITUDE

        missions = self.client.get("/api/missions").json()
        self.assertEqual(len(missions), 1)
        self.assertEqual(missions[0]["id"], body["id"])

    def test_mission_generate_custom_altitude(self):
        candidates = self._setup_area_and_candidates()
        top = candidates["top"][0]
        r = self.client.post(
            "/api/mission/generate", json={"lat": top["lat"], "lon": top["lon"], "altitude_m": 25}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["target_alt"], 25)

    def test_mission_generate_outside_area_rejected(self):
        self._setup_area_and_candidates()
        r = self.client.post("/api/mission/generate", json={"lat": 0.0, "lon": 0.0})
        self.assertEqual(r.status_code, 400)


class TestNotYetImplementedStubs(ApiTestCase):
    def test_mission_send_without_mission_returns_400(self):
        r = self.client.post("/api/mission/send")
        self.assertEqual(r.status_code, 400)

    def test_mission_abort_without_connection_returns_503(self):
        r = self.client.post("/api/mission/abort")
        self.assertEqual(r.status_code, 503)

    def test_deployment_simulate_is_honest_501(self):
        r = self.client.post("/api/deployment/simulate")
        self.assertEqual(r.status_code, 501)
        self.assertEqual(r.json()["phase_required"], 10)

    def test_deployments_list_is_empty_not_error(self):
        r = self.client.get("/api/deployments")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])


class TestTelemetryWebSocket(ApiTestCase):
    """Phase 7 — live telemetry stream over /ws/telemetry.

    No real SITL in the test environment, so these check the *shape* and
    delivery of messages (connected=False, all fields present) rather
    than real flight values — that end-to-end check is manual, against
    an actual PX4 SITL instance (see Phase 7 testing notes).
    """

    def test_sends_initial_state_immediately_on_connect(self):
        with self.client.websocket_connect("/ws/telemetry") as ws:
            data = ws.receive_json()

        self.assertEqual(data["type"], "telemetry")
        self.assertIn("timestamp", data)

        vehicle = data["vehicle"]
        for field in (
            "connected",
            "armed",
            "mode",
            "latitude",
            "longitude",
            "altitude",
            "relative_altitude",
            "ground_speed",
            "heading",
            "battery",
            "gps_fix",
            "satellites",
            "last_heartbeat",
        ):
            self.assertIn(field, vehicle)

        # No SITL connected in tests, so this is the honest current state
        # — not a faked "flying" value.
        self.assertFalse(vehicle["connected"])

    def test_multiple_clients_each_get_initial_state(self):
        with self.client.websocket_connect("/ws/telemetry") as ws_a, \
                self.client.websocket_connect("/ws/telemetry") as ws_b:
            data_a = ws_a.receive_json()
            data_b = ws_b.receive_json()

        self.assertEqual(data_a["type"], "telemetry")
        self.assertEqual(data_b["type"], "telemetry")

    def test_one_client_disconnecting_does_not_break_another(self):
        with self.client.websocket_connect("/ws/telemetry") as ws_a:
            with self.client.websocket_connect("/ws/telemetry") as ws_b:
                ws_b.receive_json()
            # ws_b is now closed; ws_a must still be usable.
            ws_a.receive_json()


class TestStaticServing(ApiTestCase):
    def test_root_redirects_to_frontend(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertEqual(r.headers["location"], "/frontend/index.html")

    def test_frontend_index_served(self):
        r = self.client.get("/frontend/index.html")
        self.assertEqual(r.status_code, 200)

    def test_data_nodes_json_served(self):
        r = self.client.get("/data/nodes.json")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
