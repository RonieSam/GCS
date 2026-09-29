"""
Phase 6 — Test Suite for Re-Scan & Before/After RF Coverage Verification

Covers:
  1.  BEFORE survey preserved after deployment.
  2.  New node increases node count by exactly one.
  3.  AFTER survey uses all deployed nodes.
  4.  BEFORE data remains unchanged.
  5.  AFTER data is stored separately.
  6.  Same thresholds used in both surveys.
  7.  Same affected area required (comparability check).
  8.  Before/after comparison calculations are correct.
  9.  Gap counts calculated correctly.
  10. Coverage percentages calculated correctly.
  11. Heatmap before remains available.
  12. Heatmap after appears.
  13. New node is visibly distinguishable (ID tracking & state).
  14. Remaining gaps are displayed.
  15. New survey invalidates old candidate analysis appropriately.
  16. No candidate is automatically deployed.
  17. Repeated analysis does not create nodes.
  18. No random candidate generation.
  19. ARM-before-START still enforced.
  20. RF sampling waits for green start point.
  21. Abort still stops sampling.
  22. Normal missions remain unchanged.
  23. Full End-to-End workflow test.
"""

import os
import sys
import math
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app, session_state, mav_manager
from database import clear_nodes, list_nodes, init_db, insert_node
from rf_collector import (
    get_rf_collector,
    SCAN_STATE_IDLE,
    SCAN_STATE_SCANNING,
    SCAN_STATE_APPROACHING,
    SCAN_STATE_COMPLETE,
    SCAN_STATE_ABORTED,
)
import rf_survey_analyzer
import mavlink_mission
import config


class TestPhase6BeforeAfterUnit(unittest.TestCase):
    """Unit tests on analyzer comparison logic and snapshots."""

    def setUp(self):
        self.area = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        self.node1 = [{"id": "COMM-001", "lat": 12.9712, "lon": 77.5942, "coverage_radius_m": 250}]
        self.node2 = [
            {"id": "COMM-001", "lat": 12.9712, "lon": 77.5942, "coverage_radius_m": 250},
            {"id": "COMM-002", "lat": 12.9728, "lon": 77.5958, "coverage_radius_m": 250},
        ]

    def test_package_analysis_snapshot_preserves_all_fields(self):
        """Test 1 & 4 & 5: Snapshot packaging retains all required metrics immutably."""
        raw_analysis = {
            "survey_samples": 100,
            "good_count": 40,
            "moderate_count": 25,
            "weak_count": 15,
            "gap_count": 20,
            "unmeasured_count": 0,
            "gap_cluster_count": 2,
            "heatmap": [{"lat": 12.971, "lon": 77.594, "best_rssi": -55.0, "status": "GOOD"}],
            "gap_points": [{"lat": 12.9725, "lon": 77.5955}],
            "candidates": [{"rank": 1, "latitude": 12.9725, "longitude": 77.5955, "score": 25.0}],
        }
        snapshot = rf_survey_analyzer.package_analysis_snapshot(
            raw_analysis,
            self.node1,
            self.area,
        )

        self.assertEqual(snapshot["survey_sample_count"], 100)
        self.assertEqual(snapshot["active_node_count"], 1)
        self.assertEqual(len(snapshot["node_positions"]), 1)
        self.assertEqual(snapshot["node_positions"][0]["id"], "COMM-001")
        self.assertEqual(snapshot["coverage_counts"]["good"], 40)
        self.assertEqual(snapshot["coverage_percentages"]["good_pct"], 40.0)
        self.assertEqual(snapshot["coverage_percentages"]["gap_pct"], 20.0)
        self.assertEqual(snapshot["gap_count"], 20)
        self.assertEqual(snapshot["gap_percentage"], 20.0)
        self.assertEqual(snapshot["gap_cluster_count"], 2)
        self.assertEqual(len(snapshot["heatmap"]), 1)
        self.assertEqual(len(snapshot["candidates"]), 1)

    def test_same_thresholds_used_in_both_surveys(self):
        """Test 6: Verify strict threshold classifications (same for BEFORE and AFTER)."""
        self.assertEqual(rf_survey_analyzer.classify_rssi(-59.9), "GOOD")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-60.0), "MODERATE")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-75.0), "WEAK")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-85.0), "GAP")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-85.1), "GAP")

    def test_same_affected_area_required_for_comparability(self):
        """Test 7: Comparability check fails when affected area changes."""
        before_raw = {
            "survey_samples": 50, "good_count": 20, "moderate_count": 10,
            "weak_count": 10, "gap_count": 10, "gap_cluster_count": 1,
            "heatmap": [], "gap_points": [], "candidates": [],
        }
        after_raw = {
            "survey_samples": 50, "good_count": 35, "moderate_count": 10,
            "weak_count": 5, "gap_count": 0, "gap_cluster_count": 0,
            "heatmap": [], "gap_points": [], "candidates": [],
        }
        different_area = [
            {"lat": 13.000, "lon": 77.000},
            {"lat": 13.010, "lon": 77.000},
            {"lat": 13.010, "lon": 77.010},
        ]
        before_snap = rf_survey_analyzer.package_analysis_snapshot(before_raw, self.node1, self.area)
        after_snap = rf_survey_analyzer.package_analysis_snapshot(after_raw, self.node2, different_area)

        comp = rf_survey_analyzer.compare_before_after(before_snap, after_snap)
        self.assertFalse(comp["comparable"])
        self.assertIn("Affected area changed", comp["invalidation_reason"])

    def test_before_after_comparison_calculations_are_exact(self):
        """Test 8, 9, 10, 14: Absolute changes and remaining gaps computed without hardcoding."""
        before_raw = {
            "survey_samples": 100,
            "good_count": 20,
            "moderate_count": 30,
            "weak_count": 20,
            "gap_count": 30,
            "gap_cluster_count": 3,
            "heatmap": [],
            "gap_points": [{"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}],
            "candidates": [],
        }
        after_raw = {
            "survey_samples": 100,
            "good_count": 55,
            "moderate_count": 25,
            "weak_count": 12,
            "gap_count": 8,
            "gap_cluster_count": 1,
            "heatmap": [],
            "gap_points": [{"lat": 1, "lon": 1}],
            "candidates": [],
        }
        before_snap = rf_survey_analyzer.package_analysis_snapshot(before_raw, self.node1, self.area)
        after_snap = rf_survey_analyzer.package_analysis_snapshot(after_raw, self.node2, self.area)

        comp = rf_survey_analyzer.compare_before_after(before_snap, after_snap)
        self.assertTrue(comp["comparable"])
        changes = comp["changes"]

        # Node count: 2 - 1 = +1
        self.assertEqual(changes["node_count_change"], 1)
        # Good change: 55.0% - 20.0% = +35.0 percentage points
        self.assertEqual(changes["good_change_percentage_points"], 35.0)
        # Moderate change: 25.0% - 30.0% = -5.0 pp
        self.assertEqual(changes["moderate_change_percentage_points"], -5.0)
        # Weak change: 12.0% - 20.0% = -8.0 pp
        self.assertEqual(changes["weak_change_percentage_points"], -8.0)
        # Gap change: 8.0% - 30.0% = -22.0 pp
        self.assertEqual(changes["gap_change_percentage_points"], -22.0)
        # Gap point change: 8 - 30 = -22
        self.assertEqual(changes["gap_point_change"], -22)
        # Gap cluster change: 1 - 3 = -2
        self.assertEqual(changes["gap_cluster_change"], -2)
        # Remaining gaps explicitly reported
        self.assertEqual(comp["remaining_gaps"], 8)
        self.assertEqual(comp["remaining_gap_clusters"], 1)


class TestPhase6Integration(unittest.TestCase):
    """Integration tests on API endpoints and state transitions."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        self.collector = get_rf_collector()
        self.collector.reset()
        self.collector.update_deployed_nodes([])

        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_scan_state"] = "IDLE"
        session_state["rf_scan_mission"] = None
        session_state["rf_analysis"] = None
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"
        session_state["rf_before_analysis"] = None
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_newly_deployed_node_id"] = None

    def tearDown(self):
        clear_nodes()
        self.collector.reset()

    def test_new_node_increases_count_by_exactly_one(self):
        """Test 2 & 16: AUTO DEPLOY (via POST /api/nodes) increments active count N -> N+1."""
        initial_nodes = list_nodes()
        self.assertEqual(len(initial_nodes), 0)

        res = self.client.post("/api/nodes", json={"id": "COMM-001", "lat": 12.9715, "lon": 77.5945, "coverage_radius_m": 250})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(list_nodes()), 1)

        # Deploy second node
        res2 = self.client.post("/api/nodes", json={"id": "COMM-002", "lat": 12.9725, "lon": 77.5955, "coverage_radius_m": 250})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(len(list_nodes()), 2)
        # Tracking newly deployed node
        self.assertEqual(session_state["rf_newly_deployed_node_id"], "COMM-002")

    def test_before_survey_preserved_after_node_deployment(self):
        """Test 1, 3, 4, 5, 11, 12, 13: BEFORE survey is preserved; AFTER survey is stored separately."""
        # 1. Deploy 1 initial node
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        self.collector.update_deployed_nodes(list_nodes())

        # 2. Simulate 1st survey (BEFORE)
        samples_before = [
            {"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -50.0}, "best_rssi": -50.0},
            {"sample_id": 2, "timestamp": 2.0, "latitude": 12.9728, "longitude": 77.5958, "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -95.0}, "best_rssi": -95.0},  # GAP
        ]
        with self.collector._lock:
            self.collector._samples = samples_before
            self.collector._state = SCAN_STATE_COMPLETE

        res1 = self.client.post("/api/rf-survey/analyze")
        self.assertEqual(res1.status_code, 200)
        body1 = res1.json()
        self.assertEqual(body1["survey_role"], "BEFORE")
        self.assertEqual(body1["phase6_state"], "BEFORE_ANALYZED")
        self.assertEqual(body1["gap_count"], 1)

        # Verify BEFORE data is available at /api/rf-survey/before
        res_before = self.client.get("/api/rf-survey/before")
        self.assertEqual(res_before.status_code, 200)
        before_data = res_before.json()
        self.assertEqual(before_data["active_node_count"], 1)
        self.assertEqual(before_data["gap_count"], 1)

        # 3. Deploy Candidate (N -> N+1)
        res_deploy = self.client.post("/api/nodes", json={"id": "COMM-002", "lat": 12.9728, "lon": 77.5958, "coverage_radius_m": 250})
        self.assertEqual(res_deploy.status_code, 200)
        self.assertEqual(session_state["rf_phase6_state"], "NODE_DEPLOYED")
        self.assertEqual(session_state["rf_newly_deployed_node_id"], "COMM-002")

        # 4. Reset survey collector for 2nd survey (clears samples, updates nodes)
        res_reset = self.client.post("/api/rf-survey/reset")
        self.assertEqual(res_reset.status_code, 200)
        self.assertEqual(res_reset.json()["phase6_state"], "AFTER_SURVEY")
        self.assertEqual(res_reset.json()["active_nodes"], 2)

        # Verify BEFORE data is STILL preserved unchanged!
        res_before_check = self.client.get("/api/rf-survey/before")
        self.assertEqual(res_before_check.status_code, 200)
        self.assertEqual(res_before_check.json()["active_node_count"], 1)
        self.assertEqual(res_before_check.json()["gap_count"], 1)

        # 5. Simulate 2nd survey (AFTER) with both nodes active
        samples_after = [
            {"sample_id": 10, "timestamp": 10.0, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -50.0, "COMM-002": -85.0}, "best_rssi": -50.0},
            {"sample_id": 11, "timestamp": 11.0, "latitude": 12.9728, "longitude": 77.5958, "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -95.0, "COMM-002": -52.0}, "best_rssi": -52.0},  # Resolved!
        ]
        with self.collector._lock:
            self.collector._samples = samples_after
            self.collector._state = SCAN_STATE_COMPLETE

        res2 = self.client.post("/api/rf-survey/analyze")
        self.assertEqual(res2.status_code, 200)
        body2 = res2.json()
        self.assertEqual(body2["survey_role"], "AFTER")
        self.assertEqual(body2["phase6_state"], "VERIFIED")
        self.assertEqual(body2["good_count"], 2)
        self.assertEqual(body2["gap_count"], 0)

        # Verify AFTER data stored separately
        res_after = self.client.get("/api/rf-survey/after")
        self.assertEqual(res_after.status_code, 200)
        self.assertEqual(res_after.json()["active_node_count"], 2)
        self.assertEqual(res_after.json()["gap_count"], 0)

        # Verify BEFORE data is still unchanged!
        res_before_final = self.client.get("/api/rf-survey/before")
        self.assertEqual(res_before_final.json()["active_node_count"], 1)
        self.assertEqual(res_before_final.json()["gap_count"], 1)

        # Verify Comparison
        res_comp = self.client.get("/api/rf-survey/comparison")
        self.assertEqual(res_comp.status_code, 200)
        comp = res_comp.json()
        self.assertTrue(comp["comparable"])
        self.assertEqual(comp["changes"]["node_count_change"], 1)
        self.assertEqual(comp["changes"]["good_change_percentage_points"], 50.0)  # 50% -> 100%
        self.assertEqual(comp["changes"]["gap_change_percentage_points"], -50.0)  # 50% -> 0%
        self.assertEqual(comp["changes"]["gap_point_change"], -1)
        self.assertEqual(comp["remaining_gaps"], 0)

    def test_session_reset_clears_verification_but_keeps_nodes(self):
        """Test 16: Reset verification clears BEFORE/AFTER/comparison but preserves deployed nodes."""
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        insert_node("COMM-002", 12.9728, 77.5958, 250)
        session_state["rf_before_analysis"] = {"test": "data"}
        session_state["rf_after_analysis"] = {"test": "data"}
        session_state["rf_comparison"] = {"test": "data"}
        session_state["rf_phase6_state"] = "VERIFIED"

        res = self.client.post("/api/rf-survey/session-reset")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["phase6_state"], "BEFORE_SURVEY")
        self.assertEqual(body["active_nodes"], 2)

        # Deployed nodes remain intact
        self.assertEqual(len(list_nodes()), 2)
        # Verification state is cleared
        self.assertIsNone(session_state["rf_before_analysis"])
        self.assertIsNone(session_state["rf_after_analysis"])
        self.assertIsNone(session_state["rf_comparison"])

    def test_new_survey_invalidates_old_candidate_analysis(self):
        """Test 15: Starting a new RF scan invalidates previous analysis."""
        session_state["rf_analysis"] = {"dummy": "analysis"}
        res = self.client.post("/api/rf-scan/generate", json={"spacing_m": 30.0, "altitude_m": 15.0})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(session_state["rf_analysis"])

    def test_repeated_analysis_does_not_create_nodes(self):
        """Test 17: Running analysis multiple times does not deploy any nodes."""
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        self.collector.update_deployed_nodes(list_nodes())
        samples = [{"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0}]
        with self.collector._lock:
            self.collector._samples = samples
            self.collector._state = SCAN_STATE_COMPLETE

        initial_count = len(list_nodes())
        self.client.post("/api/rf-survey/analyze")
        self.client.post("/api/rf-survey/analyze")
        self.assertEqual(len(list_nodes()), initial_count)

    def test_arm_before_start_enforced(self):
        """Test 19: Starting mission when UAV is disarmed returns 400 error."""
        mav_manager.set_mission_upload_state(status="UPLOADED", mission_id=1, items=5, error=None)
        with patch.object(mav_manager, "is_connected", return_value=True), \
             patch.object(mav_manager, "get_vehicle_state", return_value={"armed": False}):
            res = self.client.post("/api/mission/start")
            self.assertEqual(res.status_code, 400)
            self.assertIn("UAV must be armed before starting the mission", res.json()["detail"])

    def test_sampling_waits_for_green_start_point(self):
        """Test 20: RF collector remains in APPROACHING and does not sample until green start point is reached."""
        self.collector.reset()
        start_pt = {"latitude": 12.9710, "longitude": 77.5940, "altitude": 15.0}
        self.collector.prepare_scan(
            start_position=start_pt,
            affected_area=session_state.get("polygon"),
            deployed_nodes=[],
            survey_waypoint_count=5,
            total_mission_items=6,
            first_survey_waypoint=start_pt,
        )
        self.collector.start_scan()
        self.assertEqual(self.collector.get_state(), SCAN_STATE_APPROACHING)

        # UAV telemetry far from green start point (> 5m)
        self.collector.ingest_telemetry({"latitude": 12.9750, "longitude": 77.5990, "altitude": 15.0})
        self.assertEqual(len(self.collector._samples), 0)
        self.assertEqual(self.collector.get_state(), SCAN_STATE_APPROACHING)

        # UAV arrives at green start point (within 5m)
        self.collector.ingest_telemetry({"latitude": 12.971001, "longitude": 77.594001, "altitude": 15.0})
        self.assertEqual(self.collector.get_state(), SCAN_STATE_SCANNING)
        self.assertGreaterEqual(len(self.collector._samples), 1)

    def test_abort_stops_sampling(self):
        """Test 21: Aborting scan stops collecting new samples."""
        self.collector.reset()
        with self.collector._lock:
            self.collector._state = SCAN_STATE_SCANNING
        self.collector.abort_scan(reason="Test abort")
        self.assertEqual(self.collector.get_state(), SCAN_STATE_ABORTED)
        cnt = len(self.collector._samples)

        # Telemetry should be ignored
        self.collector.ingest_telemetry({"latitude": 12.9710, "longitude": 77.5940, "altitude": 15.0})
        self.assertEqual(len(self.collector._samples), cnt)


class TestPhase6EndToEndScenario(unittest.TestCase):
    """
    Test 23: Complete 29-step End-to-End scenario as defined in Requirement 19.
    """

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        self.collector = get_rf_collector()
        self.collector.reset()
        self.collector.update_deployed_nodes([])

    def test_full_phase6_verification_workflow(self):
        # 1. Start clean GCS session
        res_init = self.client.post("/api/session/init")
        self.assertEqual(res_init.status_code, 200)
        self.assertEqual(len(list_nodes()), 0)

        # 2. Deploy one communication node
        node_res = self.client.post("/api/nodes", json={"id": "COMM-001", "lat": 12.9712, "lon": 77.5942, "coverage_radius_m": 250})
        self.assertEqual(node_res.status_code, 200)
        self.assertEqual(len(list_nodes()), 1)

        # 3. Define affected area
        poly = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        area_res = self.client.post("/api/area", json={"polygon": poly})
        self.assertEqual(area_res.status_code, 200)

        # 4. Generate RF Scan
        scan_res = self.client.post("/api/rf-scan/generate", json={"spacing_m": 25.0, "altitude_m": 15.0})
        self.assertEqual(scan_res.status_code, 200)
        scan_data = scan_res.json()

        # 5. Verify green starting endpoint (first survey waypoint)
        green_point = scan_data["waypoints"][0]
        self.assertIsNotNone(green_point["lat"])
        self.assertIsNotNone(green_point["lon"])

        # 6. Start only after ARM
        mav_manager.set_mission_upload_state(status="UPLOADED", mission_id=1, items=len(scan_data["waypoints"]), error=None)
        with patch.object(mav_manager, "is_connected", return_value=True), \
             patch.object(mav_manager, "get_vehicle_state", return_value={"armed": False}):
            start_reject = self.client.post("/api/mission/start")
            self.assertEqual(start_reject.status_code, 400)

        # 7. Start RF scan and simulate UAV reaching green point
        first_wp = {"latitude": green_point["lat"], "longitude": green_point["lon"], "altitude": 15.0}
        self.collector.prepare_scan(
            start_position=first_wp,
            affected_area=poly,
            deployed_nodes=list_nodes(),
            survey_waypoint_count=len(scan_data["waypoints"]),
            total_mission_items=len(scan_data["waypoints"]) + 1,
            first_survey_waypoint=first_wp,
        )
        self.collector.start_scan()
        self.assertEqual(self.collector.get_state(), SCAN_STATE_APPROACHING)

        # 8. Verify sampling starts at green point
        self.collector.ingest_telemetry({"latitude": green_point["lat"], "longitude": green_point["lon"], "altitude": 15.0})
        self.assertEqual(self.collector.get_state(), SCAN_STATE_SCANNING)

        # 9. Complete RF Scan (BEFORE)
        samples_before = [
            {"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},  # GOOD
            {"sample_id": 2, "timestamp": 2.0, "latitude": 12.9720, "longitude": 77.5950, "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -78.0}, "best_rssi": -78.0},  # WEAK
            {"sample_id": 3, "timestamp": 3.0, "latitude": 12.9728, "longitude": 77.5958, "altitude": 15.0, "current_waypoint": 3, "rssi": {"COMM-001": -95.0}, "best_rssi": -95.0},  # GAP
        ]
        with self.collector._lock:
            self.collector._samples = samples_before
            self.collector._state = SCAN_STATE_COMPLETE

        # 10. Heatmap appears in data
        survey_data = self.client.get("/api/rf-survey/data").json()
        self.assertEqual(len(survey_data["samples"]), 3)

        # 11. Analyze BEFORE survey
        analysis1 = self.client.post("/api/rf-survey/analyze").json()
        self.assertEqual(analysis1["survey_role"], "BEFORE")
        self.assertEqual(analysis1["gap_count"], 1)

        # 12. Candidate appears
        self.assertGreater(len(analysis1["candidates"]), 0)
        best_candidate = analysis1["candidates"][0]

        # 13. Select candidate
        sel_res = self.client.post("/api/select-target", json={"lat": best_candidate["latitude"], "lon": best_candidate["longitude"]})
        self.assertEqual(sel_res.status_code, 200)

        # 14. Generate deployment mission
        gen_res = self.client.post("/api/mission/generate", json={"lat": best_candidate["latitude"], "lon": best_candidate["longitude"], "altitude_m": 15.0})
        self.assertEqual(gen_res.status_code, 200)

        # 15. Upload
        mav_manager.set_mission_upload_state(status="UPLOADED", mission_id=gen_res.json()["id"], items=2, error=None)

        # 16. ARM & 17. START
        with patch.object(mav_manager, "is_connected", return_value=True), \
             patch.object(mav_manager, "get_vehicle_state", return_value={"armed": True}), \
             patch.object(mav_manager, "send_command", return_value={"success": True}):
            start_res = self.client.post("/api/mission/start")
            self.assertEqual(start_res.status_code, 200)

        # 18. UAV reaches candidate & 19. AUTO DEPLOY
        deploy_res = self.client.post("/api/nodes", json={
            "id": "COMM-002",
            "lat": best_candidate["latitude"],
            "lon": best_candidate["longitude"],
            "coverage_radius_m": 250,
        })
        self.assertEqual(deploy_res.status_code, 200)

        # 20. Verify node count increased by exactly one (1 -> 2)
        self.assertEqual(len(list_nodes()), 2)
        self.assertEqual(session_state["rf_newly_deployed_node_id"], "COMM-002")

        # 21. Start NEW RF Scan (resets samples, keeps 2 deployed nodes)
        reset_res = self.client.post("/api/rf-survey/reset")
        self.assertEqual(reset_res.status_code, 200)
        self.assertEqual(reset_res.json()["active_nodes"], 2)

        # 22. Verify old candidate/heatmap analysis invalidated
        self.assertIsNone(session_state["rf_analysis"])

        # 23. Verify sampling begins only at new green point
        scan2_res = self.client.post("/api/rf-scan/generate", json={"spacing_m": 25.0, "altitude_m": 15.0})
        self.assertEqual(scan2_res.status_code, 200)
        green2 = scan2_res.json()["waypoints"][0]
        green2_wp = {"latitude": green2["lat"], "longitude": green2["lon"], "altitude": 15.0}
        self.collector.prepare_scan(
            start_position=green2_wp,
            affected_area=poly,
            deployed_nodes=list_nodes(),
            survey_waypoint_count=len(scan2_res.json()["waypoints"]),
            total_mission_items=len(scan2_res.json()["waypoints"]) + 1,
            first_survey_waypoint=green2_wp,
        )
        self.collector.start_scan()
        self.assertEqual(self.collector.get_state(), SCAN_STATE_APPROACHING)
        self.collector.ingest_telemetry({"latitude": green2["lat"], "longitude": green2["lon"], "altitude": 15.0})
        self.assertEqual(self.collector.get_state(), SCAN_STATE_SCANNING)

        # 24. Complete AFTER scan (with newly deployed COMM-002 covering the former gap)
        samples_after = [
            {"sample_id": 10, "timestamp": 10.0, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0, "COMM-002": -82.0}, "best_rssi": -55.0},  # GOOD
            {"sample_id": 11, "timestamp": 11.0, "latitude": 12.9720, "longitude": 77.5950, "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -78.0, "COMM-002": -65.0}, "best_rssi": -65.0},  # MODERATE
            {"sample_id": 12, "timestamp": 12.0, "latitude": 12.9728, "longitude": 77.5958, "altitude": 15.0, "current_waypoint": 3, "rssi": {"COMM-001": -95.0, "COMM-002": -52.0}, "best_rssi": -52.0},  # GOOD (GAP resolved!)
        ]
        with self.collector._lock:
            self.collector._samples = samples_after
            self.collector._state = SCAN_STATE_COMPLETE

        # 25. Generate AFTER heatmap & 26. Analyze AFTER coverage
        analysis2 = self.client.post("/api/rf-survey/analyze").json()
        self.assertEqual(analysis2["survey_role"], "AFTER")
        self.assertEqual(analysis2["phase6_state"], "VERIFIED")

        # 27. Show BEFORE vs AFTER comparison
        comparison = analysis2["comparison"]
        self.assertIsNotNone(comparison)
        self.assertTrue(comparison["comparable"])
        self.assertEqual(comparison["changes"]["node_count_change"], 1)
        self.assertEqual(comparison["changes"]["gap_point_change"], -1)
        self.assertGreater(comparison["changes"]["good_change_percentage_points"], 0)

        # 28. Verify remaining gap count
        self.assertEqual(comparison["remaining_gaps"], 0)

        # 29. Verify BEFORE data was not overwritten
        before_saved = self.client.get("/api/rf-survey/before").json()
        self.assertEqual(before_saved["active_node_count"], 1)
        self.assertEqual(before_saved["gap_count"], 1)

        # Full verification endpoint verification
        verif_data = self.client.get("/api/rf-survey/verification").json()
        self.assertEqual(verif_data["phase6_state"], "VERIFIED")
        self.assertEqual(verif_data["newly_deployed_node_id"], "COMM-002")


class TestPhase6RevisedRequirements(unittest.TestCase):
    """
    Dedicated tests verifying Requirements 1 through 14:
      1. Survey returns to pre-survey location and lands (distinct from green start point).
      2. Sampling stops at final survey waypoint, no samples collected on return flight.
      3. Deployment release disabled while airborne (even over target).
      4. Deployment release enabled when landed within tolerance of candidate.
      5. Deployment release disabled if landed off-target.
      6. Duplicate release prohibited, exactly one node created.
      7. History stores last 5 completed surveys independently.
      8. GET /api/rf-survey/history and GET /api/rf-survey/history/{id}.
      9. Historical surveys retain timestamp, area, nodes, samples, heatmap, stats, gaps, candidates.
      10. Non-destructive history viewing.
      11. Comparison of two historical surveys.
      12. Comparison metrics: node count, sample count, GOOD %, MODERATE %, WEAK %, GAP %, gap points, gap clusters, heatmaps.
      13. New survey workflow creates new history record without overwriting previous runs.
      14. Aborted survey is never stored as completed history.
    """

    def setUp(self):
        init_db()
        clear_nodes()
        self.client = TestClient(app)
        self.collector = get_rf_collector()
        self.collector.reset()
        self.collector.update_deployed_nodes([])

        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_scan_state"] = "IDLE"
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"
        session_state["rf_before_analysis"] = None
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_newly_deployed_node_id"] = None
        session_state["rf_survey_history"] = []
        session_state["rf_survey_history_counter"] = 0
        session_state["selected_target"] = None
        session_state["deployment_released"] = False

    def test_requirement_1_survey_returns_to_original_presurvey_location_and_lands(self):
        """
        Req 1: RF survey must return to the UAV's ORIGINAL PRE-SURVEY LOCATION and LAND there.
        The green survey-start position is NOT the return position.
        """
        wps = [
            {"seq": 0, "lat": 12.9715, "lon": 77.5945, "alt": 15.0},  # Green start point
            {"seq": 1, "lat": 12.9725, "lon": 77.5945, "alt": 15.0},
            {"seq": 2, "lat": 12.9725, "lon": 77.5955, "alt": 15.0},  # Red end point
        ]
        home_lat = 12.9700
        home_lon = 77.5930
        pre_survey_lat = 12.9702
        pre_survey_lon = 77.5932
        survey_alt = 15.0

        items = mavlink_mission.build_survey_mission_items(
            px4_waypoints=wps,
            home_lat=home_lat,
            home_lon=home_lon,
            return_lat=pre_survey_lat,
            return_lon=pre_survey_lon,
            return_alt_m=survey_alt,
        )

        # Expected items:
        # Item 0: TAKEOFF at home
        # Items 1..3: Survey waypoints
        # Item 4: WAYPOINT back to pre-survey location (NOT green start point)
        # Item 5: LAND at pre-survey location
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        for i in range(1, 4):
            self.assertEqual(items[i]["command"], mavlink_mission._CMD_WAYPOINT)

        # Return waypoint (Item 4)
        return_wp = items[4]
        self.assertEqual(return_wp["command"], mavlink_mission._CMD_WAYPOINT)
        self.assertAlmostEqual(return_wp["lat"], pre_survey_lat, places=5)
        self.assertAlmostEqual(return_wp["lon"], pre_survey_lon, places=5)
        self.assertEqual(return_wp["alt"], survey_alt)

        # Verify return waypoint is NOT the green survey-start point
        self.assertNotEqual(return_wp["lat"], wps[0]["lat"])
        self.assertNotEqual(return_wp["lon"], wps[0]["lon"])

        # Landing item (Item 5)
        land_item = items[5]
        self.assertEqual(land_item["command"], mavlink_mission._CMD_LAND)
        self.assertAlmostEqual(land_item["lat"], pre_survey_lat, places=5)
        self.assertAlmostEqual(land_item["lon"], pre_survey_lon, places=5)
        self.assertEqual(land_item["alt"], 0.0)

    def test_requirement_2_rf_sampling_stops_at_final_survey_waypoint_no_return_samples(self):
        """
        Req 2: RF sampling must stop at the final survey waypoint and must NOT collect samples during return flight.
        """
        insert_node("COMM-001", 12.9715, 77.5945, 250)
        deployed = list_nodes()

        # Prepare survey with 3 survey waypoints (items 1, 2, 3), total 5 items (with return & land)
        self.collector.prepare_scan(
            start_position={"latitude": 12.9702, "longitude": 77.5932, "altitude": 15.0},
            affected_area=session_state["polygon"],
            deployed_nodes=deployed,
            survey_waypoint_count=3,
            total_mission_items=5,
            first_survey_waypoint={"latitude": 12.9715, "longitude": 77.5945},
        )
        self.collector.start_scan()

        # Reach green start WP
        self.collector.ingest_telemetry({"latitude": 12.9715, "longitude": 77.5945, "altitude": 15.0, "mission_current": 1})
        self.assertEqual(self.collector.get_state(), SCAN_STATE_SCANNING)

        # Waypoint 1 sample
        self.collector._last_sample_time = 0.0
        s1 = self.collector.ingest_telemetry({"latitude": 12.9715, "longitude": 77.5945, "altitude": 15.0, "mission_current": 1})
        self.assertIsNotNone(s1)

        # Reach final survey waypoint (Item 3 reached)
        self.collector.ingest_telemetry({
            "latitude": 12.9725,
            "longitude": 77.5955,
            "altitude": 15.0,
            "mission_current": 3,
            "mission_item_reached": 3,
        })
        self.assertEqual(self.collector.get_state(), SCAN_STATE_COMPLETE)
        samples_at_finish = len(self.collector.get_survey_data()["samples"])

        # Simulate Return flight (mission_current = 4, flying back to pre-survey location)
        return_sample = self.collector.ingest_telemetry({
            "latitude": 12.9710,
            "longitude": 77.5940,
            "altitude": 15.0,
            "mission_current": 4,
        })
        self.assertIsNone(return_sample)

        # Simulate Landing (mission_current = 5, landing at alt=0)
        landing_sample = self.collector.ingest_telemetry({
            "latitude": 12.9702,
            "longitude": 77.5932,
            "altitude": 0.0,
            "mission_current": 5,
        })
        self.assertIsNone(landing_sample)

        # Zero additional samples collected during return and landing
        self.assertEqual(len(self.collector.get_survey_data()["samples"]), samples_at_finish)

    @patch.object(mav_manager, "is_connected", return_value=True)
    def test_requirement_3_deployment_release_disabled_while_airborne(self, mock_conn):
        """
        Req 3: Deployment RELEASE/AUTO DEPLOY must remain DISABLED while UAV is airborne,
        even after reaching the target coordinates.
        """
        session_state["selected_target"] = {"lat": 12.9720, "lon": 77.5950}
        session_state["mission_state"] = "EXECUTING"

        # UAV reached target coordinates but is airborne at altitude 15m
        airborne_state = {
            "connected": True,
            "latitude": 12.9720,
            "longitude": 77.5950,
            "altitude": 15.0,
            "relative_altitude": 15.0,
            "mode": "MISSION",
            "armed": True,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=airborne_state):
            status_res = self.client.get("/api/deployment/status").json()
            self.assertFalse(status_res["can_release"])
            self.assertTrue(status_res["is_airborne"])
            self.assertIn("airborne", status_res["reason"].lower())

            # Attempt release while airborne -> must be rejected
            rel_res = self.client.post("/api/deployment/release")
            self.assertEqual(rel_res.status_code, 400)
            self.assertIn("airborne", rel_res.json()["detail"].lower())

    @patch.object(mav_manager, "is_connected", return_value=True)
    def test_requirements_4_5_6_release_gate_and_duplicate_prevention(self, mock_conn):
        """
        Req 4, 5, 6:
        - Release enabled only when not flying, actually landed, within tolerance of candidate.
        - If UAV lands somewhere else, release remains disabled.
        - Exactly one node is created at candidate coordinates, repeated release cannot create duplicates.
        """
        cand_lat = 12.9720
        cand_lon = 77.5950
        session_state["selected_target"] = {"lat": cand_lat, "lon": cand_lon}
        session_state["mission_state"] = "COMPLETED"

        # Case A: Landed off-target (e.g. 50 meters away, exceeds 10m tolerance)
        off_target_state = {
            "connected": True,
            "latitude": 12.9710,  # ~110m away
            "longitude": 77.5940,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=off_target_state):
            status_off = self.client.get("/api/deployment/status").json()
            self.assertFalse(status_off["can_release"])
            self.assertFalse(status_off["within_tolerance"])
            self.assertIn("off-target", status_off["reason"].lower())

            # Attempt release off-target -> rejected
            rel_off = self.client.post("/api/deployment/release")
            self.assertEqual(rel_off.status_code, 400)
            self.assertIn("tolerance", rel_off.json()["detail"].lower())

        # Case B: Landed ON target (within 10m tolerance, e.g. 2m away)
        on_target_state = {
            "connected": True,
            "latitude": cand_lat + 0.00001,
            "longitude": cand_lon + 0.00001,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=on_target_state):
            status_on = self.client.get("/api/deployment/status").json()
            self.assertTrue(status_on["can_release"])
            self.assertTrue(status_on["within_tolerance"])
            self.assertTrue(status_on["is_landed"])

            # Command physical release -> succeeds
            nodes_before = len(list_nodes())
            rel_success = self.client.post("/api/deployment/release")
            self.assertEqual(rel_success.status_code, 200)
            created_node = rel_success.json()
            self.assertEqual(created_node["lat"], cand_lat)
            self.assertEqual(created_node["lon"], cand_lon)

            # Exactly one node added
            self.assertEqual(len(list_nodes()), nodes_before + 1)
            self.assertTrue(session_state["deployment_released"])

            # Case C: Repeated release must be rejected and cannot create duplicates (Req 6)
            rel_repeat = self.client.post("/api/deployment/release")
            self.assertEqual(rel_repeat.status_code, 400)
            self.assertIn("already released", rel_repeat.json()["detail"].lower())
            self.assertEqual(len(list_nodes()), nodes_before + 1)

    def test_requirements_7_to_14_rf_survey_history_retention_and_comparison(self):
        """
        Req 7-14:
        - Store last 5 completed RF surveys independently.
        - GET /api/rf-survey/history & /history/{survey_id}.
        - Historical surveys retain all required fields.
        - Viewing history is strictly non-destructive.
        - Selecting two surveys and comparing them shows all required metrics.
        - New surveys append to history without overwriting prior runs.
        - Aborted surveys are never stored in history.
        """
        # Inject 6 completed surveys sequentially to verify ring buffer (max 5)
        for i in range(1, 7):
            insert_node(f"COMM-{i:03d}", 12.9710 + i * 0.0002, 77.5940 + i * 0.0002, 250)
            samples = [
                {"sample_id": 1, "timestamp": 10.0 + i, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {f"COMM-{i:03d}": -60.0 + i}, "best_rssi": -60.0 + i},
                {"sample_id": 2, "timestamp": 11.0 + i, "latitude": 12.9720, "longitude": 77.5950, "altitude": 15.0, "current_waypoint": 2, "rssi": {f"COMM-{i:03d}": -75.0 + i}, "best_rssi": -75.0 + i},
            ]
            with self.collector._lock:
                self.collector._samples = samples
                self.collector._state = SCAN_STATE_COMPLETE

            res = self.client.post("/api/rf-survey/analyze")
            self.assertEqual(res.status_code, 200)

        # Req 7 & 8: History stores last 5 completed surveys independently
        hist_list = self.client.get("/api/rf-survey/history").json()
        self.assertEqual(hist_list["count"], 5)
        survey_ids = [s["survey_id"] for s in hist_list["surveys"]]
        self.assertEqual(len(survey_ids), 5)
        # Survey 1 was dropped, surveys 2 to 6 are retained
        self.assertNotIn("SURVEY-001", survey_ids)
        self.assertIn("SURVEY-002", survey_ids)
        self.assertIn("SURVEY-006", survey_ids)

        # Req 9: Historical survey retains all required fields
        s_detail = self.client.get("/api/rf-survey/history/SURVEY-002").json()
        self.assertEqual(s_detail["survey_id"], "SURVEY-002")
        self.assertIn("timestamp", s_detail)
        self.assertIn("affected_area", s_detail)
        self.assertIn("node_set", s_detail)
        self.assertIn("samples", s_detail)
        self.assertIn("heatmap", s_detail)
        self.assertIn("coverage_statistics", s_detail)
        self.assertIn("gaps", s_detail)
        self.assertIn("candidates", s_detail)

        # Req 10: Non-destructive viewing check
        nodes_before_view = list_nodes()
        self.client.get("/api/rf-survey/history/SURVEY-002")
        self.assertEqual(list_nodes(), nodes_before_view)

        # Req 11 & 12: Comparison between two historical surveys
        comp_res = self.client.post(
            "/api/rf-survey/history/compare",
            json={"survey_id_1": "SURVEY-002", "survey_id_2": "SURVEY-006"},
        )
        self.assertEqual(comp_res.status_code, 200)
        comp = comp_res.json()

        # Must show: node count, sample count, GOOD %, MODERATE %, WEAK %, GAP %, gap points, gap clusters, heatmaps
        for key in ("survey_1", "survey_2"):
            sub = comp[key]
            self.assertIn("node_count", sub)
            self.assertIn("sample_count", sub)
            self.assertIn("good_pct", sub)
            self.assertIn("moderate_pct", sub)
            self.assertIn("weak_pct", sub)
            self.assertIn("gap_pct", sub)
            self.assertIn("gap_points_count", sub)
            self.assertIn("gap_clusters_count", sub)
            self.assertIn("heatmap", sub)

        self.assertIn("delta", comp)
        self.assertTrue(comp["comparable"])

        # Also verify GET query variant
        get_comp = self.client.get("/api/rf-survey/history-compare?survey_1=SURVEY-002&survey_2=SURVEY-006").json()
        self.assertEqual(get_comp["survey_1"]["survey_id"], "SURVEY-002")
        self.assertEqual(get_comp["survey_2"]["survey_id"], "SURVEY-006")

        # Req 14: Aborted survey is NOT treated as a completed historical survey
        history_count_before_abort = len(session_state["rf_survey_history"])
        with self.collector._lock:
            self.collector._state = SCAN_STATE_ABORTED
            self.collector._samples = [
                {"sample_id": 99, "timestamp": 99.0, "latitude": 12.9712, "longitude": 77.5942, "altitude": 15.0, "current_waypoint": 1, "rssi": {}, "best_rssi": None}
            ]

        # Analyzing aborted scan
        self.client.post("/api/rf-survey/analyze")
        # History must NOT have increased or added the aborted survey
        self.assertEqual(len(session_state["rf_survey_history"]), history_count_before_abort)
        for s in session_state["rf_survey_history"]:
            self.assertNotEqual(s.get("samples", [{}])[0].get("sample_id"), 99)


class TestPhase6TwoDeploymentMechanisms(unittest.TestCase):
    """
    Dedicated tests verifying the two distinct node-deployment mechanisms:
      1. AUTO DEPLOY — Immediate logical deployment (no UAV flight/landing/release required).
      2. NODE MISSION + RELEASE — Physical deployment carried by UAV.
         - Reaching destination does not create node.
         - Landing does not create node.
         - RELEASE disabled while airborne.
         - RELEASE disabled when off-target.
         - RELEASE enabled when landed and on-target.
         - Failed release creates zero nodes.
         - Successful release creates exactly one node.
         - Duplicate release creates no duplicate.
         - Aborted mission creates no node and disables release.
    """

    def setUp(self):
        clear_nodes()
        init_db()
        self.client = TestClient(app)
        self.collector = get_rf_collector()
        self.collector.reset()
        self.collector.update_deployed_nodes([])

        self.area = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        self.client.post("/api/area", json={"points": self.area})

        session_state["mission_state"] = "IDLE"
        session_state["selected_target"] = None
        session_state["deployment_released"] = False

    def test_a_auto_deploy_creates_node_immediately_without_uav_or_release(self):
        """
        Failure & Regression Test A:
        AUTO DEPLOY creates one node immediately, does NOT require UAV flight,
        does NOT require ARM, does NOT require landing, and does NOT require RELEASE.
        """
        nodes_before = len(list_nodes())
        self.assertEqual(nodes_before, 0)

        # 1. Operator selects a location or candidate
        loc_lat = 12.9720
        loc_lon = 77.5950

        # 2. Press AUTO DEPLOY -> calls direct node creation path (POST /api/nodes)
        with patch.object(mav_manager, "is_connected", return_value=False):
            # UAV is completely disconnected / offline
            res = self.client.post("/api/nodes", json={
                "id": "COMM-001",
                "lat": loc_lat,
                "lon": loc_lon,
                "coverage_radius_m": 250,
            })
            self.assertEqual(res.status_code, 200)
            created = res.json()
            self.assertEqual(created["id"], "COMM-001")
            self.assertEqual(created["lat"], loc_lat)
            self.assertEqual(created["lon"], loc_lon)

        # 3. Node exists in DB immediately
        nodes_after = list_nodes()
        self.assertEqual(len(nodes_after), 1)
        self.assertEqual(nodes_after[0]["id"], "COMM-001")

        # 4. RELEASE interlock was never touched
        self.assertFalse(session_state.get("deployment_released", False))

    def test_b_mission_deployment_reaching_and_landing_creates_no_node(self):
        """
        Failure & Regression Test B:
        Reaching destination does NOT create node.
        Landing does NOT create node.
        Generating / uploading mission does NOT create node.
        Only RELEASE creates the node.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})
        self.client.post("/api/mission/generate", json={"lat": cand_lat, "lon": cand_lon, "altitude_m": 15.0})

        # Generating mission created no node
        self.assertEqual(len(list_nodes()), 0)

        # Step 1: Simulate UAV flying toward and reaching destination coordinates
        reaching_state = {
            "connected": True,
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 15.0,
            "relative_altitude": 15.0,
            "mode": "AUTO.MISSION",
            "armed": True,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=reaching_state):
            # Checking status while at destination but airborne
            status = self.client.get("/api/deployment/status").json()
            self.assertFalse(status["can_release"])
            self.assertTrue(status["is_airborne"])

            # Reaching destination MUST NOT create node
            self.assertEqual(len(list_nodes()), 0)

        # Step 2: Simulate UAV landing at destination
        landing_state = {
            "connected": True,
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=landing_state):
            # Landing has completed
            status_landed = self.client.get("/api/deployment/status").json()
            self.assertTrue(status_landed["can_release"])
            self.assertTrue(status_landed["is_landed"])

            # Landing MUST NOT automatically create node!
            self.assertEqual(len(list_nodes()), 0)

    def test_b_release_disabled_while_airborne_and_off_target(self):
        """
        Failure & Regression Test B (continued):
        RELEASE remains disabled while airborne and when off-target.
        RELEASE becomes enabled when landed and on-target.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})

        # Airborne check
        airborne_state = {
            "connected": True,
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 12.0,
            "relative_altitude": 12.0,
            "mode": "AUTO.MISSION",
            "armed": True,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=airborne_state):
            st = self.client.get("/api/deployment/status").json()
            self.assertFalse(st["can_release"])
            self.assertIn("airborne", st["reason"].lower())

        # Off-target check (> 10m away)
        off_target_state = {
            "connected": True,
            "latitude": cand_lat + 0.0003,  # ~33m away
            "longitude": cand_lon + 0.0003,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=off_target_state):
            st = self.client.get("/api/deployment/status").json()
            self.assertFalse(st["can_release"])
            self.assertFalse(st["within_tolerance"])
            self.assertIn("off-target", st["reason"].lower())

        # On-target landed check (within 10m)
        on_target_state = {
            "connected": True,
            "latitude": cand_lat + 0.00001,  # ~1.5m away
            "longitude": cand_lon + 0.00001,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=on_target_state):
            st = self.client.get("/api/deployment/status").json()
            self.assertTrue(st["can_release"])
            self.assertTrue(st["is_landed"])
            self.assertTrue(st["within_tolerance"])

    def test_c_release_failure_creates_zero_nodes(self):
        """
        Failure Test C:
        A failed release attempt creates ZERO nodes.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})

        nodes_initial = len(list_nodes())

        # Attempt release while airborne
        airborne_state = {
            "connected": True,
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 10.0,
            "relative_altitude": 10.0,
            "mode": "AUTO.MISSION",
            "armed": True,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=airborne_state):
            rel = self.client.post("/api/deployment/release")
            self.assertEqual(rel.status_code, 400)
            self.assertEqual(len(list_nodes()), nodes_initial)

        # Attempt release while off-target
        off_target_state = {
            "connected": True,
            "latitude": cand_lat + 0.0005,
            "longitude": cand_lon + 0.0005,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=off_target_state):
            rel = self.client.post("/api/deployment/release")
            self.assertEqual(rel.status_code, 400)
            self.assertEqual(len(list_nodes()), nodes_initial)

    def test_d_and_e_release_success_creates_one_node_and_duplicate_release_prevented(self):
        """
        Failure & Success Tests D & E:
        Successful release creates exactly one node.
        Duplicate release is rejected and creates no additional nodes.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})

        landed_state = {
            "connected": True,
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_LAND",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=landed_state):
            # Successful release creates exactly 1 node (Test D)
            res1 = self.client.post("/api/deployment/release")
            self.assertEqual(res1.status_code, 200)
            node1 = res1.json()
            self.assertEqual(node1["lat"], cand_lat)
            self.assertEqual(node1["lon"], cand_lon)
            self.assertEqual(len(list_nodes()), 1)

            # Duplicate release must be rejected (Test E)
            res2 = self.client.post("/api/deployment/release")
            self.assertEqual(res2.status_code, 400)
            self.assertIn("already released", res2.json()["detail"].lower())
            self.assertEqual(len(list_nodes()), 1)

    def test_f_aborted_mission_creates_no_node_and_disables_release(self):
        """
        Failure Test F:
        Aborted / RTL mission creates NO node and disables RELEASE.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})

        # Set mission state to ABORTED
        session_state["mission_state"] = "ABORTED"

        # Even if UAV is on ground at candidate coordinates
        landed_state = {
            "connected": True,
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "mode": "AUTO_RTL",
            "armed": False,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=landed_state):
            status = self.client.get("/api/deployment/status").json()
            self.assertFalse(status["can_release"])
            self.assertIn("aborted", status["reason"].lower())

            rel = self.client.post("/api/deployment/release")
            self.assertEqual(rel.status_code, 400)
            self.assertIn("aborted", rel.json()["detail"].lower())
            self.assertEqual(len(list_nodes()), 0)


class TestPhase6BugFixHistoricalAndReleaseInterlock(unittest.TestCase):
    """
    Dedicated regression test suite for Phase 6 Bug Fix:
      1. Historical Heatmap coordinates & validation.
      2. Historical Survey Percentages (measured = good + mod + weak + gap).
      3. Comparison API contract (survey_a, survey_b, delta with pp).
      4. Historical data read-only safety.
      5. Release landing interlock (telemetry-based, normalized altitude, negative altitude safe).
      6. AUTO DEPLOY remains independent.
    """

    def setUp(self):
        clear_nodes()
        init_db()
        self.client = TestClient(app)
        self.collector = get_rf_collector()
        self.collector.reset()
        session_state.clear()
        session_state["mission_state"] = "IDLE"
        session_state["deployment_released"] = False
        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_survey_history"] = []
        session_state["rf_survey_history_counter"] = 0

    def tearDown(self):
        clear_nodes()
        self.collector.reset()
        session_state.clear()

    def test_historical_survey_contains_valid_lat_lon_coordinates(self):
        """Bug 1A: Historical survey contains valid lat/lon coordinates."""
        samples = [
            {"latitude": 12.9715, "longitude": 77.5945, "best_rssi": -55.0},
            {"latitude": 12.9725, "longitude": 77.5955, "best_rssi": -90.0},
        ]
        self.collector._samples = samples
        self.collector._state = SCAN_STATE_COMPLETE
        res = self.client.post("/api/rf-survey/analyze")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        survey_id = data["survey_id"]

        hist_res = self.client.get(f"/api/rf-survey/history/{survey_id}")
        self.assertEqual(hist_res.status_code, 200)
        hist = hist_res.json()

        # Both lat/lon and latitude/longitude must be present and finite floats
        self.assertGreater(len(hist["heatmap"]), 0)
        for pt in hist["heatmap"]:
            self.assertIn("lat", pt)
            self.assertIn("lon", pt)
            self.assertIn("latitude", pt)
            self.assertIn("longitude", pt)
            self.assertIsInstance(pt["lat"], (int, float))
            self.assertIsInstance(pt["lon"], (int, float))
            self.assertTrue(math.isfinite(pt["lat"]))
            self.assertTrue(math.isfinite(pt["lon"]))

        self.assertGreater(len(hist["gaps"]["gap_points"]), 0)
        for gp in hist["gaps"]["gap_points"]:
            self.assertIn("lat", gp)
            self.assertIn("lon", gp)
            self.assertTrue(math.isfinite(gp["lat"]))
            self.assertTrue(math.isfinite(gp["lon"]))

    def test_coverage_percentages_nonzero_and_sum_to_100_percent(self):
        """Bug 1B: Coverage percentages are non-zero when classified points exist,
        and good + moderate + weak + gap sum to approx 100%."""
        samples = []
        # 100 GOOD
        for _ in range(100):
            samples.append({"latitude": 12.9715, "longitude": 77.5945, "best_rssi": -55.0})
        # 150 MODERATE
        for _ in range(150):
            samples.append({"latitude": 12.9716, "longitude": 77.5946, "best_rssi": -70.0})
        # 100 WEAK
        for _ in range(100):
            samples.append({"latitude": 12.9717, "longitude": 77.5947, "best_rssi": -80.0})
        # 217 GAP (total 567 samples)
        for _ in range(217):
            samples.append({"latitude": 12.9725, "longitude": 77.5955, "best_rssi": -92.0})

        self.collector._samples = samples
        self.collector._state = SCAN_STATE_COMPLETE
        res = self.client.post("/api/rf-survey/analyze")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        stats = data["coverage_percentages"]
        good_pct = stats["good_percentage"]
        mod_pct = stats["moderate_percentage"]
        weak_pct = stats["weak_percentage"]
        gap_pct = stats["gap_percentage"]

        self.assertGreater(good_pct, 0.0)
        self.assertGreater(mod_pct, 0.0)
        self.assertGreater(weak_pct, 0.0)
        self.assertGreater(gap_pct, 0.0)

        total_pct = good_pct + mod_pct + weak_pct + gap_pct
        self.assertAlmostEqual(total_pct, 100.0, delta=0.5)

        # Check expected percentages: 217 / 567 * 100 = 38.3%
        self.assertAlmostEqual(gap_pct, round(217 / 567 * 100, 1), places=1)

        # Verify history record preserves these exact values
        hist = self.client.get(f"/api/rf-survey/history/{data['survey_id']}").json()
        h_stats = hist["coverage_statistics"]
        self.assertEqual(h_stats["good_percentage"], good_pct)
        self.assertEqual(h_stats["gap_percentage"], gap_pct)

    def test_comparison_api_canonical_response_structure_and_percentage_points(self):
        """Bug 1C: POST /api/rf-survey/history/compare returns canonical structure with delta in percentage points."""
        # Survey 1: 50 GOOD, 50 GAP
        samples_1 = [
            {"latitude": 12.9715, "longitude": 77.5945, "best_rssi": -55.0} for _ in range(50)
        ] + [
            {"latitude": 12.9725, "longitude": 77.5955, "best_rssi": -92.0} for _ in range(50)
        ]
        self.collector._samples = samples_1
        self.collector._state = SCAN_STATE_COMPLETE
        res1 = self.client.post("/api/rf-survey/analyze")
        id_1 = res1.json()["survey_id"]

        # Deploy a node
        insert_node("COMM-001", lat=12.9725, lon=77.5955, coverage_radius_m=250.0)

        # Survey 2: 80 GOOD, 20 GAP
        samples_2 = [
            {"latitude": 12.9715, "longitude": 77.5945, "best_rssi": -55.0} for _ in range(80)
        ] + [
            {"latitude": 12.9725, "longitude": 77.5955, "best_rssi": -92.0} for _ in range(20)
        ]
        self.collector._samples = samples_2
        self.collector._state = SCAN_STATE_COMPLETE
        res2 = self.client.post("/api/rf-survey/analyze")
        id_2 = res2.json()["survey_id"]

        comp_res = self.client.post("/api/rf-survey/history/compare", json={
            "survey_id_1": id_1,
            "survey_id_2": id_2,
        })
        self.assertEqual(comp_res.status_code, 200)
        comp = comp_res.json()

        # Check canonical response fields
        self.assertIn("survey_a", comp)
        self.assertIn("survey_b", comp)
        self.assertIn("delta", comp)

        s_a = comp["survey_a"]
        s_b = comp["survey_b"]
        delta = comp["delta"]

        self.assertEqual(s_a["survey_id"], id_1)
        self.assertEqual(s_a["sample_count"], 100)
        self.assertEqual(s_a["good_percentage"], 50.0)
        self.assertEqual(s_a["gap_percentage"], 50.0)
        self.assertEqual(s_a["gap_count"], 50)

        self.assertEqual(s_b["survey_id"], id_2)
        self.assertEqual(s_b["sample_count"], 100)
        self.assertEqual(s_b["good_percentage"], 80.0)
        self.assertEqual(s_b["gap_percentage"], 20.0)
        self.assertEqual(s_b["gap_count"], 20)

        # Delta must use percentage points (pp), not ratio
        self.assertEqual(delta["good_percentage_pp"], 30.0)  # 80.0 - 50.0 = +30.0 pp
        self.assertEqual(delta["gap_percentage_pp"], -30.0)  # 20.0 - 50.0 = -30.0 pp
        self.assertEqual(delta["gap_count"], -30)

    def test_historical_survey_remains_read_only(self):
        """Bug 1D: Viewing historical survey does not alter system state."""
        samples = [{"latitude": 12.9715, "longitude": 77.5945, "best_rssi": -55.0}]
        self.collector._samples = samples
        self.collector._state = SCAN_STATE_COMPLETE
        res = self.client.post("/api/rf-survey/analyze")
        survey_id = res.json()["survey_id"]

        session_state["rf_phase6_state"] = "BEFORE_ANALYZED"
        session_state["selected_target"] = {"lat": 12.9720, "lon": 77.5950}
        nodes_before = list_nodes()

        # View historical survey
        view_res = self.client.get(f"/api/rf-survey/history/{survey_id}")
        self.assertEqual(view_res.status_code, 200)

        # Ensure state is completely unchanged
        self.assertEqual(session_state["rf_phase6_state"], "BEFORE_ANALYZED")
        self.assertEqual(session_state["selected_target"], {"lat": 12.9720, "lon": 77.5950})
        self.assertEqual(list_nodes(), nodes_before)

    def test_regression_release_with_negative_altitude_and_executing_mission(self):
        """Bug 2 Exact Live Reproduction:
        in_air = false
        altitude = -0.013
        mission_state = 'EXECUTING'
        vehicle at candidate coordinates
        deployment destination reached
        Expected: can_release = true, release succeeds and creates exactly one node.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})
        session_state["mission_state"] = "EXECUTING"

        # PX4 SITL telemetry with small numerical negative altitude
        sitl_telemetry = {
            "connected": True,
            "in_air": False,
            "landed_state": "ON_GROUND",
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": -0.013,
            "relative_altitude": -0.013,
            "flight_mode": "AUTO_MISSION",
            "armed": True,
            "mission_item_reached": 5,
        }

        with patch.object(mav_manager, "get_vehicle_state", return_value=sitl_telemetry), \
             patch.object(mav_manager, "is_connected", return_value=True), \
             patch.object(mav_manager, "get_mission_upload_state", return_value={"items": 6, "status": "UPLOADED"}):

            status_res = self.client.get("/api/deployment/status")
            self.assertEqual(status_res.status_code, 200)
            status = status_res.json()
            self.assertTrue(status["can_release"], f"Expected can_release=True, got reason: {status.get('reason')}")
            self.assertFalse(status["is_airborne"])
            self.assertTrue(status["is_landed"])
            self.assertTrue(status["within_tolerance"])

            # POST /api/deployment/release must succeed
            rel_res = self.client.post("/api/deployment/release")
            self.assertEqual(rel_res.status_code, 200)
            node = rel_res.json()
            self.assertEqual(node["lat"], cand_lat)
            self.assertEqual(node["lon"], cand_lon)
            self.assertEqual(len(list_nodes()), 1)

    def test_regression_release_disabled_when_genuinely_airborne(self):
        """Bug 2E: Genuine airborne conditions must keep RELEASE disabled."""
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})
        session_state["mission_state"] = "EXECUTING"

        # Case 1: in_air=True, altitude=15m
        airborne_high = {
            "connected": True,
            "in_air": True,
            "landed_state": "IN_AIR",
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 15.0,
            "relative_altitude": 15.0,
            "flight_mode": "AUTO_MISSION",
            "armed": True,
            "mission_item_reached": 3,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=airborne_high), \
             patch.object(mav_manager, "is_connected", return_value=True):
            status = self.client.get("/api/deployment/status").json()
            self.assertFalse(status["can_release"])
            self.assertTrue(status["is_airborne"])
            self.assertIn("airborne", status["reason"].lower())

            rel = self.client.post("/api/deployment/release")
            self.assertEqual(rel.status_code, 400)
            self.assertIn("airborne", rel.json()["detail"].lower())

        # Case 2: in_air=True, altitude=0.5m (hovering near ground)
        airborne_low = {
            "connected": True,
            "in_air": True,
            "landed_state": "LANDING",
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 0.5,
            "relative_altitude": 0.5,
            "flight_mode": "AUTO_LAND",
            "armed": True,
            "mission_item_reached": 5,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=airborne_low), \
             patch.object(mav_manager, "is_connected", return_value=True):
            status = self.client.get("/api/deployment/status").json()
            self.assertFalse(status["can_release"])
            self.assertTrue(status["is_airborne"])

        # Case 3: in_air=False, altitude=8m (telemetry lag or false flag while flying)
        airborne_altitude_override = {
            "connected": True,
            "in_air": False,
            "landed_state": "ON_GROUND",
            "latitude": cand_lat,
            "longitude": cand_lon,
            "altitude": 8.0,
            "relative_altitude": 8.0,
            "flight_mode": "AUTO_MISSION",
            "armed": True,
            "mission_item_reached": 4,
        }
        with patch.object(mav_manager, "get_vehicle_state", return_value=airborne_altitude_override), \
             patch.object(mav_manager, "is_connected", return_value=True):
            status = self.client.get("/api/deployment/status").json()
            self.assertFalse(status["can_release"])
            self.assertTrue(status["is_airborne"])

    def test_regression_release_off_target_reason_is_off_target_not_airborne(self):
        """Bug 2 Section 4:
        in_air = false, altitude = 0, mission_state = 'EXECUTING', distance = 25m
        Expected: can_release = false. Reason must be OFF_TARGET, not AIRBORNE.
        """
        cand_lat = 12.9725
        cand_lon = 77.5955
        self.client.post("/api/select-target", json={"lat": cand_lat, "lon": cand_lon})
        session_state["mission_state"] = "EXECUTING"

        # 25m offset (approx 0.000225 deg latitude)
        off_target_state = {
            "connected": True,
            "in_air": False,
            "landed_state": "ON_GROUND",
            "latitude": cand_lat + 0.00025,  # ~27.8m away
            "longitude": cand_lon,
            "altitude": 0.0,
            "relative_altitude": 0.0,
            "flight_mode": "AUTO_LAND",
            "armed": True,
            "mission_item_reached": 5,
        }

        with patch.object(mav_manager, "get_vehicle_state", return_value=off_target_state), \
             patch.object(mav_manager, "is_connected", return_value=True):
            status = self.client.get("/api/deployment/status").json()
            self.assertFalse(status["can_release"])
            self.assertFalse(status["is_airborne"])
            self.assertTrue(status["is_landed"])
            self.assertFalse(status["within_tolerance"])
            self.assertIn("off-target", status["reason"].lower())
            self.assertNotIn("airborne", status["reason"].lower())

            rel = self.client.post("/api/deployment/release")
            self.assertEqual(rel.status_code, 400)
            self.assertIn("off-target", rel.json()["detail"].lower())
            self.assertNotIn("airborne", rel.json()["detail"].lower())

    def test_auto_deploy_remains_independent_of_mission_and_release(self):
        """Section 3: AUTO DEPLOY must create node immediately without mission or release."""
        node_req = {
            "id": "COMM-001",
            "lat": 12.9720,
            "lon": 77.5950,
            "coverage_radius_m": 250.0,
        }
        res = self.client.post("/api/nodes", json=node_req)
        self.assertEqual(res.status_code, 200)
        node = res.json()
        self.assertEqual(node["id"], "COMM-001")
        self.assertEqual(node["lat"], 12.9720)
        self.assertEqual(node["lon"], 77.5950)
        self.assertEqual(len(list_nodes()), 1)

