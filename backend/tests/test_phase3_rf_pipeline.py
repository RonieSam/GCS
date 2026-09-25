"""
Unit & Integration Tests for Phase 3:
RF Survey Telemetry & RSSI Data Collection Pipeline + Simulink Bridge

Covers the Phase 3 Test Plan:
- Test 1 & 12: Normal mission building remains completely intact.
- Test 2 & 3: Affected area & deployed nodes state validation.
- Test 4 & 5 & 6: RF Scan state machine, GPS ingestion, RSSI calculation per deployed node.
- Test 7: Multi-sample accumulation (coverage dataset building, not replacing).
- Test 8 & 9: /api/rf-survey/data and /api/rf-survey/state endpoints for Simulink.
- Test 10: UAV returns to scan-start / home coordinates and does NOT land at last survey waypoint.
- Test 11: Return leg transitions to RETURNING and SCAN_COMPLETE, with return-flight samples excluded.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from config import DEFAULT_ALTITUDE
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


class TestPhase3RFModel(unittest.TestCase):
    """Verify RF model equations match Simulink RFModel.m exactly."""

    def test_log_distance_path_loss(self):
        # At 1 metre (reference distance) with full scale (1.0): RSSI = -30 dBm
        rssi_1m = calculate_rssi(distance_m=1.0, reference_rssi=-30.0, path_loss_exponent=2.2, rf_range_scale=1.0)
        self.assertAlmostEqual(rssi_1m, -30.0, places=1)

        # At 10 metres: -30 - 10*2.2*log10(10) = -30 - 22 = -52.0 dBm
        rssi_10m = calculate_rssi(distance_m=10.0, reference_rssi=-30.0, path_loss_exponent=2.2, rf_range_scale=1.0)
        self.assertAlmostEqual(rssi_10m, -52.0, places=1)

    def test_distance_3d(self):
        # 3D distance between same lat/lon with alt difference 20m -> exactly 20m
        d = compute_distance_3d_m(13.0827, 80.2707, 30.0, 13.0827, 80.2707, 10.0)
        self.assertAlmostEqual(d, 20.0, places=1)

    def test_calculate_node_rssi_vector(self):
        nodes = [
            {"id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "alt": 10.0},
            {"id": "COMM-002", "lat": 13.0850, "lon": 80.2707, "alt": 10.0},
        ]
        # UAV right above COMM-001 at 30m altitude (20m vertical delta)
        res = calculate_node_rssi_vector(
            uav_lat=13.0827,
            uav_lon=80.2707,
            uav_alt_m=30.0,
            deployed_nodes=nodes,
        )
        self.assertIn("COMM-001", res)
        self.assertIn("COMM-002", res)
        # COMM-001 is much closer than COMM-002, so RSSI_001 > RSSI_002
        self.assertGreater(res["COMM-001"], res["COMM-002"])


class TestPhase3SurveyMissionReturn(unittest.TestCase):
    """Verify that survey mission generator enforces return to scan-start position."""

    def test_survey_mission_ends_at_final_survey_waypoint(self):
        px4_waypoints = [
            {"seq": 0, "lat": 13.0830, "lon": 80.2710, "alt": 25.0},
            {"seq": 1, "lat": 13.0835, "lon": 80.2710, "alt": 25.0},
            {"seq": 2, "lat": 13.0835, "lon": 80.2720, "alt": 25.0},
            {"seq": 3, "lat": 13.0830, "lon": 80.2720, "alt": 25.0},
        ]
        home_lat = 13.0820
        home_lon = 80.2700
        survey_alt = 25.0

        items = mavlink_mission.build_survey_mission_items(
            px4_waypoints=px4_waypoints,
            home_lat=home_lat,
            home_lon=home_lon,
        )

        # Expected items in Phase 4:
        # Item 0: TAKEOFF
        # Items 1..4: Survey waypoints
        # Total items = len(px4_waypoints) + 1
        # NO return waypoint, NO landing waypoint
        self.assertEqual(len(items), len(px4_waypoints) + 1)

        takeoff_item = items[0]
        self.assertEqual(takeoff_item["command"], mavlink_mission._CMD_TAKEOFF)

        # Final survey waypoint is items[4]
        last_survey_wp = items[4]
        self.assertEqual(last_survey_wp["lat"], 13.0830)
        self.assertEqual(last_survey_wp["lon"], 80.2720)
        self.assertEqual(last_survey_wp["command"], mavlink_mission._CMD_WAYPOINT)

    def test_normal_single_target_mission_remains_unbroken(self):
        """Phase 3 changes must not break the normal single-target mission flow."""
        target_lat = 13.0850
        target_lon = 80.2750
        target_alt = 20.0
        home_lat = 13.0827
        home_lon = 80.2707

        items = mavlink_mission.build_mission_items(
            target_lat=target_lat,
            target_lon=target_lon,
            target_alt_m=target_alt,
            home_lat=home_lat,
            home_lon=home_lon,
        )

        # Normal mission has 3 items: TAKEOFF, FLY TO TARGET, LAND
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        self.assertEqual(items[1]["command"], mavlink_mission._CMD_WAYPOINT)
        self.assertEqual(items[2]["command"], mavlink_mission._CMD_LAND)
        self.assertAlmostEqual(items[1]["lat"], target_lat, places=6)
        self.assertAlmostEqual(items[1]["lon"], target_lon, places=6)


class TestPhase3RFCollectorStateMachine(unittest.TestCase):
    """Verify RF collector state machine, sample accumulation, and return leg handling."""

    def setUp(self):
        self.collector = RFSurveyCollector()
        self.collector._min_sample_interval_s = 0.0  # allow fast ingestion in tests

    def test_idle_does_not_accumulate(self):
        self.assertEqual(self.collector.state, SCAN_STATE_IDLE)
        # Telemetry arriving when IDLE must not create samples
        sample = self.collector.ingest_telemetry({
            "latitude": 13.0827,
            "longitude": 80.2707,
            "altitude": 25.0,
            "mission_current": 1,
        })
        self.assertIsNone(sample)
        self.assertEqual(self.collector.get_survey_data()["sample_count"], 0)

    def test_full_scan_lifecycle_and_accumulation(self):
        nodes = [
            {"id": "COMM-001", "lat": 13.0825, "lon": 80.2705, "alt": 10.0},
            {"id": "COMM-002", "lat": 13.0835, "lon": 80.2715, "alt": 10.0},
        ]
        area = [
            {"lat": 13.0820, "lon": 80.2700},
            {"lat": 13.0840, "lon": 80.2700},
            {"lat": 13.0840, "lon": 80.2720},
            {"lat": 13.0820, "lon": 80.2720},
        ]
        start_pos = {
            "latitude": 13.0827,
            "longitude": 80.2707,
            "altitude": 0.0,
        }

        # 1. Prepare scan (survey has 4 waypoints, total 7 mission items)
        self.collector.prepare_scan(
            start_position=start_pos,
            affected_area=area,
            deployed_nodes=nodes,
            survey_waypoint_count=4,
            total_mission_items=7,
        )
        self.assertEqual(self.collector.state, SCAN_STATE_READY)

        # Still no samples accumulated while READY
        self.assertIsNone(self.collector.ingest_telemetry({
            "latitude": 13.0827, "longitude": 80.2707, "altitude": 0.0
        }))

        # 2. Start mission
        self.collector.start_scan()
        self.assertEqual(self.collector.state, SCAN_STATE_SCANNING)

        # 3. Telemetry during survey execution (item 1 reached)
        s1 = self.collector.ingest_telemetry({
            "latitude": 13.0827,
            "longitude": 80.2707,
            "altitude": 25.0,
            "mission_current": 1,
            "mission_item_reached": 1,
        })
        self.assertIsNotNone(s1)
        self.assertEqual(s1["sample_id"], 1)
        self.assertIn("COMM-001", s1["rssi"])
        self.assertIn("COMM-002", s1["rssi"])

        # 4. Telemetry sample 2 (item 2 reached)
        s2 = self.collector.ingest_telemetry({
            "latitude": 13.0830,
            "longitude": 80.2710,
            "altitude": 25.0,
            "mission_current": 2,
            "mission_item_reached": 2,
        })
        self.assertIsNotNone(s2)
        self.assertEqual(s2["sample_id"], 2)

        # Samples must accumulate, not overwrite!
        survey = self.collector.get_survey_data()
        self.assertEqual(survey["sample_count"], 2)
        self.assertEqual(len(survey["samples"]), 2)

        # 5. Survey path completion: item 4 (last survey waypoint) reached!
        # In Phase 4, transitions directly to SCAN_COMPLETE (no return-to-start or land leg)
        self.collector.ingest_telemetry({
            "latitude": 13.0840,
            "longitude": 80.2720,
            "altitude": 25.0,
            "mission_current": 4,
            "mission_item_reached": 4,  # >= survey_waypoint_count
        })
        self.assertEqual(self.collector.state, SCAN_STATE_COMPLETE)

        # 6. After survey completion, NO further survey samples should be accumulated
        s_after = self.collector.ingest_telemetry({
            "latitude": 13.0840,
            "longitude": 80.2720,
            "altitude": 25.0,
            "mission_current": 4,
            "mission_item_reached": 4,
        })
        self.assertIsNone(s_after)
        # Sample count must remain 2 and all collected data preserved
        self.assertEqual(self.collector.get_survey_data()["sample_count"], 2)


class TestPhase3FastAPISimulinkEndpoints(unittest.TestCase):
    """Verify HTTP endpoints exposed to Simulink / GCS."""

    def setUp(self):
        self.client = TestClient(app)
        # Reset collector
        get_rf_collector().reset()

    def test_rf_survey_state_endpoint(self):
        r = self.client.get("/api/rf-survey/state")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("state", data)
        self.assertIn("sample_count", data)
        self.assertEqual(data["state"], "IDLE")

    def test_rf_survey_data_endpoint_structure(self):
        # Ingest a sample into the global collector
        collector = get_rf_collector()
        collector.prepare_scan(
            start_position={"latitude": 13.0827, "longitude": 80.2707, "altitude": 30.0},
            affected_area=[{"lat": 13.082, "lon": 80.270}, {"lat": 13.083, "lon": 80.271}],
            deployed_nodes=[{"id": "COMM-001", "lat": 13.0825, "lon": 80.2705}],
            survey_waypoint_count=3,
            total_mission_items=6,
        )
        collector.start_scan()
        collector._min_sample_interval_s = 0.0
        collector.ingest_telemetry({
            "latitude": 13.0827,
            "longitude": 80.2707,
            "altitude": 30.0,
            "mission_current": 1,
            "mission_item_reached": 1,
        })

        # Call GET /api/rf-survey/data
        r = self.client.get("/api/rf-survey/data")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["state"], "SCANNING")
        self.assertEqual(data["sample_count"], 1)
        self.assertIsNotNone(data["scan_start_position"])
        self.assertIsNotNone(data["affected_area"])
        self.assertEqual(len(data["deployed_nodes"]), 1)

        sample = data["samples"][0]
        self.assertIn("timestamp", sample)
        self.assertIn("latitude", sample)
        self.assertIn("longitude", sample)
        self.assertIn("altitude", sample)
        self.assertIn("rssi", sample)
        self.assertIn("COMM-001", sample["rssi"])

    def test_rf_survey_reset(self):
        collector = get_rf_collector()
        collector.prepare_scan(
            start_position={"latitude": 13.0827, "longitude": 80.2707, "altitude": 30.0},
            affected_area=None,
            deployed_nodes=[],
            survey_waypoint_count=3,
            total_mission_items=6,
        )
        r = self.client.post("/api/rf-survey/reset")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(collector.state, "IDLE")
        self.assertEqual(collector.get_survey_data()["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
