"""
Unit & Integration Tests for Phase 4:
Dynamic RF Coverage, Gap Detection & Candidate Placement Pipeline

Covers:
1. One deployed node -> exactly one RSSI value.
2. Add a second node -> exactly two RSSI values.
3. Delete the second node -> only one remains in future scans.
4. Delete all nodes -> zero RSSI streams.
5. Deleting a node prunes stale measurements from survey data.
6. RF range is approximately 1/4 of previous effective range (RFRangeScale = 0.25).
7. Horizontal distance only: d = sqrt((droneX - nodeX)^2 + (droneY - nodeY)^2).
8. Monotonic distance vs RSSI relationship: moving away weakens RSSI.
9. Deterministic node ID mapping and ordering.
10. Survey mission ends at final survey waypoint (no return-to-start, no landing, no RTL).
11. Collector state machine: IDLE -> SCAN_READY -> SCANNING -> SCAN_COMPLETE.
12. Normal mission upload/start/return/landing behavior remains completely unaffected.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from config import DEFAULT_ALTITUDE, RF_RANGE_SCALE
from database import clear_nodes, delete_node, init_db, insert_node, list_nodes
from main import app, session_state
import mavlink_mission
from rf_collector import (
    SCAN_STATE_COMPLETE,
    SCAN_STATE_IDLE,
    SCAN_STATE_READY,
    SCAN_STATE_SCANNING,
    RFSurveyCollector,
    get_rf_collector,
)
from rf_model import (
    calculate_node_rssi_vector,
    calculate_rssi,
    compute_distance_horizontal_m,
    latlon_to_xy_m,
)


class TestPhase4DynamicNodesAndRSSI(unittest.TestCase):
    """Verify dynamic node handling: 1 node -> 1 RSSI, 2 nodes -> 2 RSSI, delete node -> 1 RSSI."""

    def setUp(self):
        init_db()
        clear_nodes()

    def tearDown(self):
        clear_nodes()

    def test_dynamic_node_addition_and_deletion(self):
        # Initial state: 0 nodes
        self.assertEqual(len(list_nodes()), 0)

        # 0 deployed nodes -> exactly 0 RSSI values
        rssi_0 = calculate_node_rssi_vector(
            uav_lat=13.0827,
            uav_lon=80.2707,
            deployed_nodes=[],
        )
        self.assertEqual(len(rssi_0), 0)

        # 1 deployed node -> exactly 1 RSSI value
        insert_node("COMM-001", 13.0827, 80.2707, 250.0)
        nodes = list_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "COMM-001")

        rssi_1 = calculate_node_rssi_vector(
            uav_lat=13.0827,
            uav_lon=80.2707,
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


class TestPhase4HorizontalDistanceAndRSSIBehavior(unittest.TestCase):
    """Verify horizontal distance calculation, altitude exclusion, and RSSI monotonicity."""

    def test_horizontal_distance_formula(self):
        # UAV=(152.4, 198.7), NODE=(150.0, 200.0) -> dist = 2.729m
        d = compute_distance_horizontal_m(152.4, 198.7, 150.0, 200.0)
        self.assertAlmostEqual(d, 2.729, places=2)

    def test_altitude_excluded_from_rf_distance(self):
        # Two calls at same horizontal coordinates with different altitudes
        # MUST produce the exact same RSSI
        node = [{"id": "COMM-001", "x": 150.0, "y": 200.0}]

        rssi_alt15 = calculate_node_rssi_vector(
            uav_x=152.4, uav_y=198.7, uav_alt_m=15.0, deployed_nodes=node
        )
        rssi_alt50 = calculate_node_rssi_vector(
            uav_x=152.4, uav_y=198.7, uav_alt_m=500.0, deployed_nodes=node
        )

        self.assertEqual(rssi_alt15["COMM-001"], rssi_alt50["COMM-001"])

    def test_rssi_decreases_monotonically_with_distance(self):
        # Fixed node at (150, 200)
        node = [{"id": "COMM-001", "x": 150.0, "y": 200.0}]

        # UAV near node (dist = 2.7m)
        r_near = calculate_node_rssi_vector(
            uav_x=152.4, uav_y=198.7, deployed_nodes=node
        )["COMM-001"]

        # UAV moderate distance (dist = 30m)
        r_mid = calculate_node_rssi_vector(
            uav_x=180.0, uav_y=200.0, deployed_nodes=node
        )["COMM-001"]

        # UAV far distance (dist = 80m)
        r_far = calculate_node_rssi_vector(
            uav_x=230.0, uav_y=200.0, deployed_nodes=node
        )["COMM-001"]

        # RSSI must strictly decrease as distance increases
        self.assertGreater(r_near, r_mid)
        self.assertGreater(r_mid, r_far)

        # Classification check:
        # Near (2.7m) should be GOOD (> -60 dBm)
        self.assertGreater(r_near, -60.0)
        # Mid (30m, eff 120m) should be WEAK (-85 to -75 dBm)
        self.assertLessEqual(r_mid, -75.0)
        self.assertGreater(r_mid, -85.0)
        # Far (80m, eff 320m) should be GAP (<= -85 dBm)
        self.assertLessEqual(r_far, -85.0)


class TestPhase4ApiEndpoints(unittest.TestCase):
    """Verify REST API for node deployment, deletion, persistence, and collector sync."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        get_rf_collector().reset()

    def tearDown(self):
        clear_nodes()

    def test_node_api_crud(self):
        # 1. Start with zero nodes
        r = self.client.get("/api/nodes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 0)

        # 2. Deploy COMM-001
        node1 = {"id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250.0}
        r_add1 = self.client.post("/api/nodes", json=node1)
        self.assertEqual(r_add1.status_code, 200)
        self.assertEqual(r_add1.json()["id"], "COMM-001")

        # GET /api/nodes returns exactly 1
        r_list1 = self.client.get("/api/nodes")
        self.assertEqual(len(r_list1.json()), 1)

        # 3. Deploy COMM-002
        node2 = {"id": "COMM-002", "lat": 13.0850, "lon": 80.2715, "coverage_radius_m": 250.0}
        r_add2 = self.client.post("/api/nodes", json=node2)
        self.assertEqual(r_add2.status_code, 200)

        # GET /api/nodes returns exactly 2
        r_list2 = self.client.get("/api/nodes")
        self.assertEqual(len(r_list2.json()), 2)

        # 4. Delete COMM-002
        r_del = self.client.delete("/api/nodes/COMM-002")
        self.assertEqual(r_del.status_code, 200)
        self.assertTrue(r_del.json()["success"])

        # GET /api/nodes returns exactly 1
        r_list3 = self.client.get("/api/nodes")
        self.assertEqual(len(r_list3.json()), 1)
        self.assertEqual(r_list3.json()[0]["id"], "COMM-001")

        # 5. Delete COMM-001
        r_del2 = self.client.delete("/api/nodes/COMM-001")
        self.assertEqual(r_del2.status_code, 200)

        # GET /api/nodes returns 0
        r_list4 = self.client.get("/api/nodes")
        self.assertEqual(len(r_list4.json()), 0)

    def test_collector_sync_and_stale_node_pruning(self):
        collector = get_rf_collector()
        collector._min_sample_interval_s = 0.0

        # Start with COMM-001
        self.client.post("/api/nodes", json={"id": "COMM-001", "lat": 13.0827, "lon": 80.2707})

        collector.prepare_scan(
            start_position={"latitude": 13.0827, "longitude": 80.2707, "altitude": 25.0},
            affected_area=None,
            deployed_nodes=list_nodes(),
            survey_waypoint_count=5,
            total_mission_items=6,
        )
        collector.start_scan()

        # Sample 1 -> 1 node
        s1 = collector.ingest_telemetry({
            "latitude": 13.0827, "longitude": 80.2707, "altitude": 25.0,
            "mission_current": 1, "mission_item_reached": 1,
        })
        self.assertIsNotNone(s1)
        self.assertEqual(len(s1["rssi"]), 1)
        self.assertIn("COMM-001", s1["rssi"])

        # Add COMM-002 -> 2 nodes
        self.client.post("/api/nodes", json={"id": "COMM-002", "lat": 13.0840, "lon": 80.2710})

        # Sample 2 -> 2 nodes
        s2 = collector.ingest_telemetry({
            "latitude": 13.0830, "longitude": 80.2708, "altitude": 25.0,
            "mission_current": 2, "mission_item_reached": 2,
        })
        self.assertIsNotNone(s2)
        self.assertEqual(len(s2["rssi"]), 2)
        self.assertIn("COMM-001", s2["rssi"])
        self.assertIn("COMM-002", s2["rssi"])

        # Delete COMM-001 -> prunes COMM-001 from collector
        self.client.delete("/api/nodes/COMM-001")

        # Future sample 3 -> only COMM-002
        s3 = collector.ingest_telemetry({
            "latitude": 13.0835, "longitude": 80.2709, "altitude": 25.0,
            "mission_current": 3, "mission_item_reached": 3,
        })
        self.assertIsNotNone(s3)
        self.assertEqual(len(s3["rssi"]), 1)
        self.assertIn("COMM-002", s3["rssi"])
        self.assertNotIn("COMM-001", s3["rssi"])

        # Previous sample 1 and 2 must also have COMM-001 pruned
        survey_data = collector.get_survey_data()
        for sample in survey_data["samples"]:
            self.assertNotIn("COMM-001", sample["rssi"])


class TestPhase4SurveyMissionAndState(unittest.TestCase):
    """Verify RF survey ends at final waypoint with no return-to-start, no landing, and no RTL."""

    def test_survey_mission_items_end_at_final_waypoint(self):
        survey_alt = 20.0
        wps = [
            {"seq": 0, "lat": 13.082, "lon": 80.270, "alt": survey_alt},
            {"seq": 1, "lat": 13.084, "lon": 80.270, "alt": survey_alt},
        ]
        items = mavlink_mission.build_survey_mission_items(
            px4_waypoints=wps,
            home_lat=13.080,
            home_lon=80.268,
        )

        # Exactly 3 items: TAKEOFF + 2 survey waypoints
        self.assertEqual(len(items), 3)
        # Takeoff item
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        self.assertEqual(items[0]["alt"], survey_alt)
        # Waypoints
        self.assertEqual(items[1]["command"], mavlink_mission._CMD_WAYPOINT)
        self.assertEqual(items[2]["command"], mavlink_mission._CMD_WAYPOINT)
        # NO return waypoint, NO landing waypoint
        commands = [it["command"] for it in items]
        self.assertNotIn(mavlink_mission._CMD_LAND, commands)

    def test_survey_stops_collection_at_final_waypoint(self):
        collector = get_rf_collector()
        collector.reset()
        collector._min_sample_interval_s = 0.0

        collector.prepare_scan(
            start_position={"latitude": 13.080, "longitude": 80.270, "altitude": 20.0},
            affected_area=None,
            deployed_nodes=[{"id": "COMM-001", "lat": 13.082, "lon": 80.270}],
            survey_waypoint_count=2,
            total_mission_items=3,
        )
        collector.start_scan()
        self.assertEqual(collector.state, SCAN_STATE_SCANNING)

        # Waypoint 1 reached -> sample collected
        s1 = collector.ingest_telemetry({
            "latitude": 13.082, "longitude": 80.270, "altitude": 20.0,
            "mission_current": 1, "mission_item_reached": 1,
        })
        self.assertIsNotNone(s1)

        # Final survey waypoint 2 reached -> transitions directly to SCAN_COMPLETE
        collector.ingest_telemetry({
            "latitude": 13.084, "longitude": 80.270, "altitude": 20.0,
            "mission_current": 2, "mission_item_reached": 2,
        })
        self.assertEqual(collector.state, SCAN_STATE_COMPLETE)

        # Subsequent telemetry -> NO new samples collected
        s_after = collector.ingest_telemetry({
            "latitude": 13.084, "longitude": 80.270, "altitude": 20.0,
            "mission_current": 2, "mission_item_reached": 2,
        })
        self.assertIsNone(s_after)

        # Data is preserved
        survey_data = collector.get_survey_data()
        self.assertEqual(survey_data["state"], SCAN_STATE_COMPLETE)
        self.assertGreaterEqual(survey_data["sample_count"], 1)

    def test_normal_mission_unaffected(self):
        items = mavlink_mission.build_mission_items(
            target_lat=13.085,
            target_lon=80.275,
            target_alt_m=18.0,
            home_lat=13.080,
            home_lon=80.270,
        )
        # Normal mission remains TAKEOFF -> TARGET -> LAND (3 items)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        self.assertEqual(items[1]["command"], mavlink_mission._CMD_WAYPOINT)
        self.assertEqual(items[2]["command"], mavlink_mission._CMD_LAND)


if __name__ == "__main__":
    unittest.main()
