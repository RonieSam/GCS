"""
Comprehensive verification test suite for Phase 4 Corrections:
GCS Node State, RSSI Debugging, and RF Survey End Behavior.

Directly verifies tests 1 through 44 from user requirements specification:
- Tests 1-18: Node State & Persistence (Single source of truth in DB, 0 on empty, full persistence).
- Tests 19-20: Node Deletion UI (Map marker click delete removed, Nodes menu delete works).
- Tests 21-25: RF Node Synchronization (Exact N-stream matching, pruning stale measurements).
- Tests 26-33: RSSI & Coordinate System Debugging (Horizontal Euclidean distance, monotonic path loss,
               deterministic node ID mapping, RFRangeScale = 0.25 applied once).
- Tests 34-42: RF Survey Mission (No return to start, no auto land, no RTL, terminates at final survey waypoint,
               stops RSSI collection, preserves data).
- Tests 43-44: Normal Mission behavior preserved (TAKEOFF -> TARGET -> LAND).
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import config
from database import clear_nodes, delete_node, init_db, insert_node, list_nodes
from main import app, session_state
import mavlink_mission
from rf_collector import (
    SCAN_STATE_COMPLETE,
    SCAN_STATE_IDLE,
    SCAN_STATE_READY,
    SCAN_STATE_SCANNING,
    get_rf_collector,
)
from rf_model import (
    calculate_node_rssi_vector,
    calculate_rssi,
    compute_distance_horizontal_m,
    latlon_to_xy_m,
)


class TestPhase4Corrections(unittest.TestCase):
    """Executes all 44 test verification requirements from Phase 4 specification."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        self.collector = get_rf_collector()
        self.collector.reset()
        self.collector._min_sample_interval_s = 0.0

    def tearDown(self):
        clear_nodes()
        self.collector.reset()

    # =========================================================================
    # TESTS 1 - 18: NODE STATE & PERSISTENCE
    # =========================================================================

    def test_requirements_01_to_18_node_state_and_persistence(self):
        """
        Verify complete node lifecycle & persistence:
        1. Start with zero nodes.
        2. GET /api/nodes returns zero.
        3. Deploy one node.
        4. GET /api/nodes returns exactly one.
        5. Refresh/reinitialize (new API client / query DB).
        6. Displays exactly one.
        7. Deploy second node.
        8. GET /api/nodes returns exactly two.
        9. Refresh.
        10. Both nodes remain visible.
        11. Delete one from Nodes menu (DELETE /api/nodes/{id}).
        12. Only the remaining node is displayed.
        13. Refresh.
        14. Remaining node is still displayed.
        15. Delete the final node.
        16. GET /api/nodes returns zero.
        17. Refresh.
        18. No nodes appear.
        """
        # 1. Start with zero nodes
        self.assertEqual(len(list_nodes()), 0)

        # 2. GET /api/nodes returns zero
        r = self.client.get("/api/nodes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 0)

        # 3. Deploy one node (NODE-001)
        r_post1 = self.client.post("/api/nodes", json={"id": "NODE-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250.0})
        self.assertEqual(r_post1.status_code, 200)

        # 4. GET /api/nodes returns exactly one
        r = self.client.get("/api/nodes")
        nodes_step4 = r.json()
        self.assertEqual(len(nodes_step4), 1)
        self.assertEqual(nodes_step4[0]["id"], "NODE-001")

        # 5 & 6. Refresh / reinitialize client -> still exactly one
        refreshed_client = TestClient(app)
        r = refreshed_client.get("/api/nodes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(r.json()[0]["id"], "NODE-001")

        # 7. Deploy second node (NODE-002)
        r_post2 = self.client.post("/api/nodes", json={"id": "NODE-002", "lat": 13.0850, "lon": 80.2720, "coverage_radius_m": 250.0})
        self.assertEqual(r_post2.status_code, 200)

        # 8. GET /api/nodes returns exactly two
        r = self.client.get("/api/nodes")
        nodes_step8 = r.json()
        self.assertEqual(len(nodes_step8), 2)
        node_ids_step8 = {n["id"] for n in nodes_step8}
        self.assertEqual(node_ids_step8, {"NODE-001", "NODE-002"})

        # 9 & 10. Refresh frontend -> both nodes remain visible
        refreshed_client2 = TestClient(app)
        r = refreshed_client2.get("/api/nodes")
        self.assertEqual(len(r.json()), 2)

        # 11. Delete one from Nodes menu (DELETE /api/nodes/NODE-001)
        r_del1 = self.client.delete("/api/nodes/NODE-001")
        self.assertEqual(r_del1.status_code, 200)
        self.assertTrue(r_del1.json()["success"])

        # 12. Only the remaining node is displayed (NODE-002)
        r = self.client.get("/api/nodes")
        nodes_step12 = r.json()
        self.assertEqual(len(nodes_step12), 1)
        self.assertEqual(nodes_step12[0]["id"], "NODE-002")

        # 13 & 14. Refresh -> remaining node is still displayed
        refreshed_client3 = TestClient(app)
        r = refreshed_client3.get("/api/nodes")
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(r.json()[0]["id"], "NODE-002")

        # 15. Delete the final node (NODE-002)
        r_del2 = self.client.delete("/api/nodes/NODE-002")
        self.assertEqual(r_del2.status_code, 200)

        # 16. GET /api/nodes returns zero
        r = self.client.get("/api/nodes")
        self.assertEqual(len(r.json()), 0)

        # 17 & 18. Refresh -> no nodes appear
        refreshed_client4 = TestClient(app)
        r = refreshed_client4.get("/api/nodes")
        self.assertEqual(len(r.json()), 0)

    # =========================================================================
    # TESTS 19 - 20: NODE DELETE UI INTEGRITY
    # =========================================================================

    def test_requirements_19_20_node_delete_ui(self):
        """
        Verify deletion mechanism:
        19. Clicking a map node cannot delete it (popup contains info only, no delete button).
        20. Delete from Nodes menu endpoint DELETE /api/nodes/{id} works properly.
        """
        # Read frontend HTML and JS files to verify map click deletion is removed
        frontend_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "app.js")
        with open(frontend_js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        # Requirement 19: No delete buttons in popups, no map-click delete handler
        self.assertNotIn("deleteDeployedNode", js_content.split("bindPopup")[1].split("})")[0])
        self.assertNotIn("Click to delete", js_content)

        frontend_html_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html")
        with open(frontend_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        self.assertNotIn("click any node on the map to delete it", html_content)

        # Requirement 20: Delete from Nodes menu works via API
        self.client.post("/api/nodes", json={"id": "NODE-TEST", "lat": 13.08, "lon": 80.27})
        self.assertEqual(len(self.client.get("/api/nodes").json()), 1)
        r_del = self.client.delete("/api/nodes/NODE-TEST")
        self.assertEqual(r_del.status_code, 200)
        self.assertEqual(len(self.client.get("/api/nodes").json()), 0)

    # =========================================================================
    # TESTS 21 - 25: RF NODE SYNCHRONIZATION
    # =========================================================================

    def test_requirements_21_to_25_rf_node_synchronization(self):
        """
        Verify collector synchronization:
        21. One node -> one RSSI stream.
        22. Two nodes -> two RSSI streams.
        23. Delete one -> one RSSI stream.
        24. Delete all -> zero RSSI streams.
        25. No stale deleted-node RSSI remains in current or past survey data.
        """
        # Start scan with 1 node (NODE-001)
        self.client.post("/api/nodes", json={"id": "NODE-001", "lat": 13.0827, "lon": 80.2707})
        self.collector.prepare_scan(
            start_position={"latitude": 13.0827, "longitude": 80.2707, "altitude": 20.0},
            affected_area=None,
            deployed_nodes=list_nodes(),
            survey_waypoint_count=5,
            total_mission_items=6,
        )
        self.collector.start_scan()

        # 21. One node -> exactly one RSSI stream
        s1 = self.collector.ingest_telemetry({
            "latitude": 13.0827, "longitude": 80.2707, "altitude": 20.0,
            "mission_current": 1, "mission_item_reached": 1,
        })
        self.assertIsNotNone(s1)
        self.assertEqual(len(s1["rssi"]), 1)
        self.assertEqual(list(s1["rssi"].keys()), ["NODE-001"])

        # 22. Deploy second node (NODE-002) -> two RSSI streams
        self.client.post("/api/nodes", json={"id": "NODE-002", "lat": 13.0835, "lon": 80.2712})
        s2 = self.collector.ingest_telemetry({
            "latitude": 13.0829, "longitude": 80.2708, "altitude": 20.0,
            "mission_current": 2, "mission_item_reached": 2,
        })
        self.assertIsNotNone(s2)
        self.assertEqual(len(s2["rssi"]), 2)
        self.assertIn("NODE-001", s2["rssi"])
        self.assertIn("NODE-002", s2["rssi"])

        # 23. Delete one (NODE-001) -> one RSSI stream remains
        self.client.delete("/api/nodes/NODE-001")
        s3 = self.collector.ingest_telemetry({
            "latitude": 13.0831, "longitude": 80.2709, "altitude": 20.0,
            "mission_current": 3, "mission_item_reached": 3,
        })
        self.assertIsNotNone(s3)
        self.assertEqual(len(s3["rssi"]), 1)
        self.assertIn("NODE-002", s3["rssi"])
        self.assertNotIn("NODE-001", s3["rssi"])

        # 25. Check that stale NODE-001 is pruned from previous samples
        survey_data = self.collector.get_survey_data()
        for sample in survey_data["samples"]:
            self.assertNotIn("NODE-001", sample["rssi"], "Stale node measurement must be pruned!")

        # 24. Delete all nodes -> zero RSSI streams
        self.client.delete("/api/nodes/NODE-002")
        s4 = self.collector.ingest_telemetry({
            "latitude": 13.0833, "longitude": 80.2710, "altitude": 20.0,
            "mission_current": 4, "mission_item_reached": 4,
        })
        self.assertIsNotNone(s4)
        self.assertEqual(len(s4["rssi"]), 0)

    # =========================================================================
    # TESTS 26 - 33: RSSI & COORDINATE SYSTEM DEBUGGING
    # =========================================================================

    def test_requirements_26_to_33_rssi_pipeline(self):
        """
        Verify RSSI calculation and coordinate system:
        26. Fixed node + UAV near node -> calculate distance accurately.
        27. Move UAV farther away.
        28. Verify distance changes correctly.
        29. Verify RSSI generally becomes weaker as distance increases.
        30. Verify RSSI is not random due to stale/crossed node data.
        31. Verify deterministic node ID to RSSI association.
        32. Verify RFRangeScale = 0.25 applied exactly once.
        33. Verify lat/lon to horizontal metres conversion accuracy.
        """
        # 33. Lat/lon conversion accuracy
        # At latitude 13.0827, 1 degree north is ~111,320m
        x0, y0 = latlon_to_xy_m(13.0827, 80.2707, ref_lat=13.0827, ref_lon=80.2707)
        self.assertAlmostEqual(x0, 0.0, places=2)
        self.assertAlmostEqual(y0, 0.0, places=2)

        x_north, y_north = latlon_to_xy_m(13.0836, 80.2707, ref_lat=13.0827, ref_lon=80.2707)
        # 0.0009 degrees north * 111320 ≈ 100.188m
        self.assertAlmostEqual(y_north, 100.188, delta=1.0)
        self.assertAlmostEqual(x_north, 0.0, delta=0.5)

        # 26. Fixed node at (150.0, 200.0), UAV near node at (152.4, 198.7)
        node_def = [{"id": "NODE-001", "x": 150.0, "y": 200.0}]
        d_near = compute_distance_horizontal_m(152.4, 198.7, 150.0, 200.0)
        self.assertAlmostEqual(d_near, 2.729, places=2)

        rssi_near = calculate_node_rssi_vector(
            uav_x=152.4, uav_y=198.7, deployed_nodes=node_def
        )["NODE-001"]

        # 27 & 28. Move UAV farther away to (180.0, 200.0) -> distance = 30m
        d_far = compute_distance_horizontal_m(180.0, 200.0, 150.0, 200.0)
        self.assertAlmostEqual(d_far, 30.0, places=2)

        rssi_far = calculate_node_rssi_vector(
            uav_x=180.0, uav_y=200.0, deployed_nodes=node_def
        )["NODE-001"]

        # 29. Verify RSSI becomes significantly weaker
        self.assertGreater(rssi_near, rssi_far)
        # Near RSSI (effective dist = 2.73 / 0.25 = 10.9m) -> ~-52.8 dBm (GOOD)
        self.assertGreater(rssi_near, -60.0)
        # Far RSSI (effective dist = 30 / 0.25 = 120m) -> ~-75.7 dBm (WEAK)
        self.assertLessEqual(rssi_far, -75.0)

        # 30 & 31. Deterministic Node ID association and no crosstalk
        multi_nodes = [
            {"id": "NODE-A", "x": 0.0, "y": 0.0},
            {"id": "NODE-B", "x": 200.0, "y": 200.0},
        ]
        # UAV is at (0, 0)
        rssi_multi = calculate_node_rssi_vector(
            uav_x=0.0, uav_y=0.0, deployed_nodes=multi_nodes
        )
        # NODE-A must be very strong, NODE-B must be very weak
        self.assertGreater(rssi_multi["NODE-A"], -50.0)
        self.assertLess(rssi_multi["NODE-B"], -85.0)

        # 32. Verify RFRangeScale is applied exactly once
        # If scale is applied once to distance, effective_dist = d / 0.25
        rssi_s1 = calculate_rssi(distance_m=40.0, rf_range_scale=0.25)
        rssi_s2 = calculate_rssi(distance_m=160.0, rf_range_scale=1.0)
        self.assertAlmostEqual(rssi_s1, rssi_s2, places=1)
        # And RSSI is never multiplied by 0.25
        self.assertNotEqual(rssi_s1, rssi_s2 * 0.25)

    # =========================================================================
    # TESTS 34 - 42: RF SURVEY MISSION GENERATION & TERMINATION
    # =========================================================================

    def test_requirements_34_to_42_rf_survey_mission(self):
        """
        Verify RF Survey End Behavior:
        34. Generate RF survey mission.
        35. Verify survey waypoints are correct.
        36. Verify NO return-to-start waypoint.
        37. Verify NO automatic landing waypoint.
        38. Verify NO RTL.
        39. Verify scan ends at final survey waypoint.
        40. Verify RSSI collection stops after the final survey point.
        41. Verify scan state becomes SCAN_COMPLETE.
        42. Verify collected data remains available.
        """
        survey_alt = 18.0
        wps = [
            {"seq": 0, "lat": 13.082, "lon": 80.270, "alt": survey_alt},
            {"seq": 1, "lat": 13.084, "lon": 80.270, "alt": survey_alt},
            {"seq": 2, "lat": 13.086, "lon": 80.272, "alt": survey_alt},
        ]

        # 34. Generate survey items
        items = mavlink_mission.build_survey_mission_items(
            px4_waypoints=wps,
            home_lat=13.080,
            home_lon=80.268,
        )

        # 35. Total items = TAKEOFF (1) + survey waypoints (3) = 4 items
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        for i in range(1, 4):
            self.assertEqual(items[i]["command"], mavlink_mission._CMD_WAYPOINT)

        # 36. Verify NO return-to-start waypoint (last item is survey waypoint 2, not home)
        self.assertEqual(items[-1]["lat"], 13.086)
        self.assertEqual(items[-1]["lon"], 80.272)

        # 37 & 38. Verify NO automatic landing waypoint and NO RTL
        commands = [it["command"] for it in items]
        self.assertNotIn(mavlink_mission._CMD_LAND, commands)
        self.assertNotIn(mavlink_mission.mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, commands)

        # Initialize collector with 3 survey waypoints (items 1, 2, 3)
        self.collector.prepare_scan(
            start_position={"latitude": 13.080, "longitude": 80.268, "altitude": survey_alt},
            affected_area=None,
            deployed_nodes=[{"id": "NODE-001", "lat": 13.082, "lon": 80.270}],
            survey_waypoint_count=3,
            total_mission_items=4,
        )
        self.collector.start_scan()
        self.assertEqual(self.collector.state, SCAN_STATE_SCANNING)

        # Waypoint 1 & 2 reached
        self.collector.ingest_telemetry({
            "latitude": 13.082, "longitude": 80.270, "altitude": survey_alt,
            "mission_current": 1, "mission_item_reached": 1,
        })
        self.collector.ingest_telemetry({
            "latitude": 13.084, "longitude": 80.270, "altitude": survey_alt,
            "mission_current": 2, "mission_item_reached": 2,
        })
        self.assertEqual(self.collector.state, SCAN_STATE_SCANNING)

        # 39 & 41. Reach final survey waypoint (item 3) -> transitions directly to SCAN_COMPLETE
        self.collector.ingest_telemetry({
            "latitude": 13.086, "longitude": 80.272, "altitude": survey_alt,
            "mission_current": 3, "mission_item_reached": 3,
        })
        self.assertEqual(self.collector.state, SCAN_STATE_COMPLETE)

        count_at_completion = len(self.collector._samples)

        # 40. Verify RSSI collection stops after final survey point
        post_completion_sample = self.collector.ingest_telemetry({
            "latitude": 13.086, "longitude": 80.272, "altitude": survey_alt,
            "mission_current": 3, "mission_item_reached": 3,
        })
        self.assertIsNone(post_completion_sample)
        self.assertEqual(len(self.collector._samples), count_at_completion)

        # 42. Verify collected survey data remains available
        data = self.collector.get_survey_data()
        self.assertEqual(data["state"], SCAN_STATE_COMPLETE)
        self.assertEqual(data["sample_count"], count_at_completion)
        self.assertGreater(data["sample_count"], 0)

    # =========================================================================
    # TESTS 43 - 44: NORMAL MISSION INTEGRITY
    # =========================================================================

    def test_requirements_43_44_normal_mission_unaffected(self):
        """
        Verify existing normal mission behavior remains completely unchanged:
        43. Normal mission upload/start behavior remains unchanged.
        44. Normal mission return/landing behavior remains unchanged (TAKEOFF -> TARGET -> LAND).
        """
        items = mavlink_mission.build_mission_items(
            target_lat=13.085,
            target_lon=80.275,
            target_alt_m=15.0,
            home_lat=13.080,
            home_lon=80.270,
        )

        # Exactly 3 items: TAKEOFF -> TARGET WAYPOINT -> LAND
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        self.assertEqual(items[1]["command"], mavlink_mission._CMD_WAYPOINT)
        self.assertEqual(items[2]["command"], mavlink_mission._CMD_LAND)

        # Target coordinates match target
        self.assertEqual(items[1]["lat"], 13.085)
        self.assertEqual(items[1]["lon"], 80.275)
        # Land coordinates match target
        self.assertEqual(items[2]["lat"], 13.085)
        self.assertEqual(items[2]["lon"], 80.275)


if __name__ == "__main__":
    unittest.main()
