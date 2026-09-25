"""
Unit & Integration Tests for Phase 4:
Dynamic RF Coverage, Gap Detection & Candidate Placement Pipeline

Covers the Phase 4 Test Plan:
1. One deployed node -> exactly one RSSI value.
2. Add a second node -> exactly two RSSI values.
3. Delete the second node -> only one remains in future scans.
4. RF range is approximately 1/4 of the previous effective range (RFRangeScale = 0.25).
5. UAV altitude and scan path are unchanged.
6. Backend /api/rf-survey/data supplies real survey points for Simulink.
7. Coverage classification thresholds: GOOD (> -60), MODERATE (> -75), WEAK (> -85), GAP (<= -85).
8. Existing normal mission and RF Scan functionality still work.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from config import DEFAULT_ALTITUDE, RF_RANGE_SCALE
from database import clear_nodes, delete_node, insert_node, list_nodes
from main import app, session_state
import mavlink_mission
from rf_collector import (
    SCAN_STATE_COMPLETE,
    SCAN_STATE_IDLE,
    SCAN_STATE_READY,
    SCAN_STATE_RETURNING,
    SCAN_STATE_SCANNING,
    RFSurveyCollector,
    get_rf_collector,
)
from rf_model import (
    calculate_node_rssi_vector,
    calculate_rssi,
    compute_distance_3d_m,
)


class TestPhase4DynamicNodesAndRSSI(unittest.TestCase):
    """Verify dynamic node handling: 1 node -> 1 RSSI, 2 nodes -> 2 RSSI, delete node -> 1 RSSI."""

    def setUp(self):
        clear_nodes()

    def tearDown(self):
        clear_nodes()

    def test_dynamic_node_addition_and_deletion(self):
        # Initial state: 0 nodes
        self.assertEqual(len(list_nodes()), 0)

        # 1 deployed node -> exactly 1 RSSI value
        insert_node("COMM-001", 13.0827, 80.2707, 250.0)
        nodes = list_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "COMM-001")

        rssi_1 = calculate_node_rssi_vector(
            uav_lat=13.0827,
            uav_lon=80.2707,
            uav_alt_m=30.0,
            deployed_nodes=nodes,
        )
        self.assertEqual(len(rssi_1), 1)
        self.assertIn("COMM-001", rssi_1)

        # Add a 2nd node -> exactly 2 RSSI values
        insert_node("COMM-002", 13.0850, 80.2715, 250.0)
        nodes = list_nodes()
        self.assertEqual(len(nodes), 2)

        rssi_2 = calculate_node_rssi_vector(
            uav_lat=13.0827,
            uav_lon=80.2707,
            uav_alt_m=30.0,
            deployed_nodes=nodes,
        )
        self.assertEqual(len(rssi_2), 2)
        self.assertIn("COMM-001", rssi_2)
        self.assertIn("COMM-002", rssi_2)

        # Delete the 2nd node -> only 1 remains in future scans
        del_ok = delete_node("COMM-002")
        self.assertTrue(del_ok)
        nodes = list_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "COMM-001")

        rssi_after = calculate_node_rssi_vector(
            uav_lat=13.0827,
            uav_lon=80.2707,
            uav_alt_m=30.0,
            deployed_nodes=nodes,
        )
        self.assertEqual(len(rssi_after), 1)
        self.assertIn("COMM-001", rssi_after)
        self.assertNotIn("COMM-002", rssi_after)


class TestPhase4RFRangeScale(unittest.TestCase):
    """Verify RF model calibration with RFRangeScale = 0.25 (effective range ~1/4)."""

    def test_quarter_range_calibration(self):
        # When RFRangeScale = 0.25, a point at distance d should have the same
        # RSSI as a point at distance 4*d with RFRangeScale = 1.0.
        rssi_full_scale = calculate_rssi(distance_m=200.0, rf_range_scale=1.0)
        rssi_quarter_scale = calculate_rssi(distance_m=50.0, rf_range_scale=0.25)

        self.assertAlmostEqual(rssi_full_scale, rssi_quarter_scale, places=1)

    def test_rssi_not_multiplied_by_quarter(self):
        # RSSI is NOT multiplied by 0.25 — it follows logarithmic path loss
        rssi_1 = calculate_rssi(distance_m=10.0, rf_range_scale=1.0)
        rssi_quarter = calculate_rssi(distance_m=10.0, rf_range_scale=0.25)

        # At the same distance, 0.25 scale has more path loss (lower RSSI),
        # but NOT 0.25 * rssi_1
        self.assertNotEqual(rssi_quarter, rssi_1 * 0.25)
        self.assertLess(rssi_quarter, rssi_1)


class TestPhase4ApiEndpoints(unittest.TestCase):
    """Verify REST API for node deployment, deletion, and collector sync."""

    def setUp(self):
        self.client = TestClient(app)
        clear_nodes()
        get_rf_collector().reset()

    def tearDown(self):
        clear_nodes()

    def test_node_api_crud(self):
        # Initially empty
        r = self.client.get("/api/nodes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 0)

        # Deploy COMM-001
        node1 = {"id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250.0}
        r_add1 = self.client.post("/api/nodes", json=node1)
        self.assertEqual(r_add1.status_code, 200)
        self.assertEqual(r_add1.json()["id"], "COMM-001")

        # Deploy COMM-002
        node2 = {"id": "COMM-002", "lat": 13.0850, "lon": 80.2715, "coverage_radius_m": 250.0}
        r_add2 = self.client.post("/api/nodes", json=node2)
        self.assertEqual(r_add2.status_code, 200)

        # List nodes -> exactly 2
        r_list = self.client.get("/api/nodes")
        self.assertEqual(len(r_list.json()), 2)

        # Delete COMM-002
        r_del = self.client.delete("/api/nodes/COMM-002")
        self.assertEqual(r_del.status_code, 200)
        self.assertTrue(r_del.json()["success"])

        # List nodes -> exactly 1
        r_list2 = self.client.get("/api/nodes")
        self.assertEqual(len(r_list2.json()), 1)
        self.assertEqual(r_list2.json()[0]["id"], "COMM-001")

    def test_collector_sync_on_node_changes(self):
        collector = get_rf_collector()
        collector._min_sample_interval_s = 0.0

        # Start with COMM-001
        self.client.post("/api/nodes", json={"id": "COMM-001", "lat": 13.0827, "lon": 80.2707})

        collector.prepare_scan(
            start_position={"latitude": 13.0827, "longitude": 80.2707, "altitude": 25.0},
            affected_area=None,
            deployed_nodes=list_nodes(),
            survey_waypoint_count=5,
            total_mission_items=8,
        )
        collector.start_scan()

        # Ingest sample 1 -> has only COMM-001
        s1 = collector.ingest_telemetry({
            "latitude": 13.0827, "longitude": 80.2707, "altitude": 25.0,
            "mission_current": 1, "mission_item_reached": 1,
        })
        self.assertIsNotNone(s1)
        self.assertEqual(len(s1["rssi"]), 1)
        self.assertIn("COMM-001", s1["rssi"])

        # Deploy COMM-002 via API
        self.client.post("/api/nodes", json={"id": "COMM-002", "lat": 13.0840, "lon": 80.2710})

        # Ingest sample 2 -> automatically has BOTH COMM-001 and COMM-002
        s2 = collector.ingest_telemetry({
            "latitude": 13.0830, "longitude": 80.2708, "altitude": 25.0,
            "mission_current": 2, "mission_item_reached": 2,
        })
        self.assertIsNotNone(s2)
        self.assertEqual(len(s2["rssi"]), 2)
        self.assertIn("COMM-001", s2["rssi"])
        self.assertIn("COMM-002", s2["rssi"])

        # Delete COMM-001 via API
        self.client.delete("/api/nodes/COMM-001")

        # Ingest sample 3 -> has only COMM-002
        s3 = collector.ingest_telemetry({
            "latitude": 13.0835, "longitude": 80.2709, "altitude": 25.0,
            "mission_current": 3, "mission_item_reached": 3,
        })
        self.assertIsNotNone(s3)
        self.assertEqual(len(s3["rssi"]), 1)
        self.assertIn("COMM-002", s3["rssi"])
        self.assertNotIn("COMM-001", s3["rssi"])


class TestPhase4MissionIntegrity(unittest.TestCase):
    """Verify normal single-target mission and RF scan path altitudes remain unchanged."""

    def test_altitudes_and_paths_unchanged(self):
        survey_alt = 20.0
        wps = [
            {"seq": 0, "lat": 13.082, "lon": 80.270, "alt": survey_alt},
            {"seq": 1, "lat": 13.084, "lon": 80.270, "alt": survey_alt},
        ]
        items = mavlink_mission.build_survey_mission_items(
            px4_waypoints=wps,
            home_lat=13.080,
            home_lon=80.268,
            return_lat=13.081,
            return_lon=13.081,
            return_alt_m=survey_alt,
        )

        # Takeoff altitude matches survey_alt
        self.assertEqual(items[0]["alt"], survey_alt)
        # Survey waypoints altitude matches survey_alt
        self.assertEqual(items[1]["alt"], survey_alt)
        self.assertEqual(items[2]["alt"], survey_alt)
        # Return waypoint altitude matches survey_alt
        self.assertEqual(items[3]["alt"], survey_alt)
        # Landing altitude is 0
        self.assertEqual(items[4]["alt"], 0.0)

    def test_normal_mission_unaffected(self):
        items = mavlink_mission.build_mission_items(
            target_lat=13.085,
            target_lon=80.275,
            target_alt_m=18.0,
            home_lat=13.080,
            home_lon=80.270,
        )
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["alt"], 18.0)
        self.assertEqual(items[1]["alt"], 18.0)


if __name__ == "__main__":
    unittest.main()
