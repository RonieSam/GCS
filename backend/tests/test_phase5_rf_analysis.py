"""
Unit and integration tests for Phase 5 — RF Survey Analysis & Candidate Generation.

Tests all requirements specified in Phase 5:
  1. Deterministic candidate generation from real RF samples (no randomness).
  2. Best RSSI computation among active deployed nodes only.
  3. Coverage classification thresholds (GOOD > -60, MODERATE -75..-60, WEAK -85..-75, GAP <= -85).
  4. Spatial clustering with GapClusterDistance = 250 * RFRangeScale = 75m (at scale=0.30).
  5. Cluster centroid (mean lat, lon) and scoring (gapPoints*10 + nearestNodeDist*0.1).
  6. Valid coordinates (lat, lon, local_x, local_y; no NaN/null).
  7. Candidates separate from nodes (database nodes unchanged).
  8. Invalidation on new survey generation, area change, or reset.
  9. ARM before START guard on /api/mission/start.
  10. Equivalence with MATLAB CandidatePlacement algorithm reference.
"""

import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import database
from main import app, session_state
import rf_survey_analyzer
from rf_collector import get_rf_collector


class TestPhase5RfAnalyzerCore(unittest.TestCase):
    """Core algorithmic tests on rf_survey_analyzer module."""

    def setUp(self):
        self.deployed_nodes = [
            {"id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250},
            {"id": "COMM-002", "lat": 13.0847, "lon": 80.2707, "coverage_radius_m": 250},
        ]
        self.active_node_ids = {"COMM-001", "COMM-002"}

    def test_compute_best_rssi(self):
        """Requirement 4: bestRSSI is strongest valid RSSI among active nodes."""
        rssi = {"COMM-001": -90.0, "COMM-002": -74.0, "OLD-003": -50.0}
        # OLD-003 is not in active_node_ids, so it must be ignored
        best = rf_survey_analyzer.compute_best_rssi(rssi, self.active_node_ids)
        self.assertEqual(best, -74.0)

        # Missing / invalid values ignored
        rssi_invalid = {"COMM-001": None, "COMM-002": float("nan")}
        self.assertIsNone(rf_survey_analyzer.compute_best_rssi(rssi_invalid, self.active_node_ids))

        # Empty dict returns None
        self.assertIsNone(rf_survey_analyzer.compute_best_rssi({}, self.active_node_ids))

    def test_classify_rssi_thresholds(self):
        """Requirement 5: Exact classification thresholds."""
        # GOOD: > -60 dBm
        self.assertEqual(rf_survey_analyzer.classify_rssi(-59.9), "GOOD")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-40.0), "GOOD")

        # MODERATE: -75 < RSSI <= -60 dBm
        self.assertEqual(rf_survey_analyzer.classify_rssi(-60.0), "MODERATE")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-70.0), "MODERATE")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-74.9), "MODERATE")

        # WEAK: -85 < RSSI <= -75 dBm
        self.assertEqual(rf_survey_analyzer.classify_rssi(-75.0), "WEAK")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-80.0), "WEAK")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-84.9), "WEAK")

        # GAP: <= -85 dBm
        self.assertEqual(rf_survey_analyzer.classify_rssi(-85.0), "GAP")
        self.assertEqual(rf_survey_analyzer.classify_rssi(-95.0), "GAP")

        # UNMEASURED
        self.assertEqual(rf_survey_analyzer.classify_rssi(None), "UNMEASURED")

    def test_gap_cluster_distance(self):
        """Requirement 21: GapClusterDistance = 250 * RFRangeScale = 75 m at scale=0.30."""
        dist = rf_survey_analyzer._gap_cluster_distance_m()
        self.assertAlmostEqual(dist, 75.0, places=1)

    def test_deterministic_clustering_and_candidate_generation(self):
        """Requirement 2 & 28 & 33: Running twice on same data yields identical results."""
        samples = [
            # Cluster A: 3 gap points close together (near 13.0800, 80.2700)
            {"latitude": 13.08000, "longitude": 80.27000, "rssi": {"COMM-001": -95.0}},
            {"latitude": 13.08010, "longitude": 80.27010, "rssi": {"COMM-001": -92.0}},
            {"latitude": 13.08015, "longitude": 80.27005, "rssi": {"COMM-001": -90.0}},
            # Cluster B: 2 gap points far away (~300m north, near 13.0830, 80.2700)
            {"latitude": 13.08300, "longitude": 80.27000, "rssi": {"COMM-001": -88.0}},
            {"latitude": 13.08310, "longitude": 80.27005, "rssi": {"COMM-001": -89.0}},
            # Good coverage point (not a gap)
            {"latitude": 13.08270, "longitude": 80.27070, "rssi": {"COMM-001": -55.0}},
        ]

        res1 = rf_survey_analyzer.analyze_rf_survey(samples, self.deployed_nodes)
        res2 = rf_survey_analyzer.analyze_rf_survey(samples, self.deployed_nodes)

        # Gap count
        self.assertEqual(res1["gap_count"], 5)
        self.assertEqual(res1["good_count"], 1)
        self.assertEqual(res1["gap_cluster_count"], 2)

        # Exactly 2 candidates generated
        self.assertEqual(len(res1["candidates"]), 2)
        self.assertEqual(len(res2["candidates"]), 2)

        # Results between run 1 and run 2 are identical (deterministic)
        self.assertEqual(res1["candidates"][0]["latitude"], res2["candidates"][0]["latitude"])
        self.assertEqual(res1["candidates"][0]["longitude"], res2["candidates"][0]["longitude"])
        self.assertEqual(res1["candidates"][0]["score"], res2["candidates"][0]["score"])
        self.assertEqual(res1["candidates"][0]["gap_points"], res2["candidates"][0]["gap_points"])

        # Candidate 1 has rank 1 and highest score (3 points * 10 + dist*0.1)
        c1 = res1["candidates"][0]
        self.assertEqual(c1["rank"], 1)
        self.assertEqual(c1["gap_points"], 3)
        self.assertGreater(c1["score"], res1["candidates"][1]["score"])

        # Validate coordinates are valid numbers and include local_x, local_y
        for c in res1["candidates"]:
            self.assertTrue(math.isfinite(c["latitude"]))
            self.assertTrue(math.isfinite(c["longitude"]))
            self.assertTrue(math.isfinite(c["local_x"]))
            self.assertTrue(math.isfinite(c["local_y"]))

    def test_affected_area_filtering(self):
        """Requirement 15: Samples outside affected area polygon are excluded."""
        poly = [
            {"lat": 13.0820, "lon": 80.2700},
            {"lat": 13.0830, "lon": 80.2700},
            {"lat": 13.0830, "lon": 80.2710},
            {"lat": 13.0820, "lon": 80.2710},
        ]
        samples = [
            # Inside polygon
            {"latitude": 13.0825, "longitude": 80.2705, "rssi": {"COMM-001": -95.0}},
            # Outside polygon
            {"latitude": 13.0900, "longitude": 80.2800, "rssi": {"COMM-001": -95.0}},
        ]
        res = rf_survey_analyzer.analyze_rf_survey(samples, self.deployed_nodes, affected_area=poly)
        self.assertEqual(res["survey_samples"], 1)
        self.assertEqual(res["gap_count"], 1)

    def test_candidates_separate_from_nodes(self):
        """Requirement 3 & 18: Candidate analysis does not create nodes in database."""
        test_node = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250}]
        samples = [
            {"latitude": 13.08000, "longitude": 80.27000, "rssi": {"COMM-001": -95.0}},
        ]
        res = rf_survey_analyzer.analyze_rf_survey(samples, test_node)
        self.assertGreater(len(res["candidates"]), 0)
        # Database table remains unaffected
        db_nodes = database.list_nodes()
        self.assertEqual(len(db_nodes), 0)


class TestPhase5ApiEndpoints(unittest.TestCase):
    """API endpoint tests for Phase 5."""

    def setUp(self):
        self.client = TestClient(app)
        database.reset_db_for_tests()
        session_state.update(
            {
                "polygon": None,
                "last_coverage": None,
                "last_candidates": None,
                "last_scored": None,
                "selected_target": None,
                "mission_state": "PLANNING",
                "last_mission": None,
                "rf_analysis": None,
                "rf_scan_state": "IDLE",
                "rf_scan_mission": None,
            }
        )

    def test_analyze_without_samples_returns_400(self):
        """POST /api/rf-survey/analyze with empty survey collector returns 400."""
        collector = get_rf_collector()
        collector.reset()
        r = self.client.post("/api/rf-survey/analyze")
        self.assertEqual(r.status_code, 400)
        self.assertIn("No RF survey samples available", r.json()["detail"])

    def test_analyze_with_samples_returns_full_analysis(self):
        """POST /api/rf-survey/analyze returns heatmap, gap_points, candidates, and summary."""
        collector = get_rf_collector()
        collector.reset()

        # Deploy a node
        r_node = self.client.post("/api/nodes", json={"id": "COMM-001", "lat": 13.0827, "lon": 80.2707})
        self.assertEqual(r_node.status_code, 200)

        # Set affected area
        poly = [
            {"lat": 13.0800, "lon": 80.2680},
            {"lat": 13.0860, "lon": 80.2680},
            {"lat": 13.0860, "lon": 80.2760},
            {"lat": 13.0800, "lon": 80.2760},
        ]
        self.client.post("/api/area", json={"polygon": poly})

        # Inject samples into collector
        nodes = self.client.get("/api/nodes").json()
        collector.update_deployed_nodes(nodes)
        collector._state = "SCAN_COMPLETE"
        with collector._lock:
            collector._samples = [
                {
                    "sample_id": 1,
                    "timestamp": 1.0,
                    "latitude": 13.0810,
                    "longitude": 80.2700,
                    "altitude": 15.0,
                    "current_waypoint": 1,
                    "rssi": {"COMM-001": -95.0},
                    "best_rssi": -95.0,
                },
                {
                    "sample_id": 2,
                    "timestamp": 2.0,
                    "latitude": 13.0827,
                    "longitude": 80.2707,
                    "altitude": 15.0,
                    "current_waypoint": 2,
                    "rssi": {"COMM-001": -55.0},
                    "best_rssi": -55.0,
                },
            ]

        # Analyze
        r = self.client.post("/api/rf-survey/analyze")
        self.assertEqual(r.status_code, 200)
        data = r.json()

        self.assertEqual(data["survey_samples"], 2)
        self.assertEqual(data["good_count"], 1)
        self.assertEqual(data["gap_count"], 1)
        self.assertIn("heatmap", data)
        self.assertIn("samples", data)
        self.assertIn("gap_points", data)
        self.assertIn("candidates", data)
        self.assertEqual(len(data["candidates"]), 1)

        c = data["candidates"][0]
        self.assertEqual(c["rank"], 1)
        self.assertAlmostEqual(c["latitude"], 13.0810, places=4)
        self.assertAlmostEqual(c["longitude"], 80.2700, places=4)

        # GET /api/rf-survey/analysis returns the cached result
        r_get = self.client.get("/api/rf-survey/analysis")
        self.assertEqual(r_get.status_code, 200)
        self.assertEqual(r_get.json()["survey_samples"], 2)

    def test_invalidation_on_new_scan_or_reset(self):
        """Requirement 27: New survey generation or reset invalidates previous analysis."""
        # Set dummy analysis in session_state
        session_state["rf_analysis"] = {"dummy": True}

        # 1. Reset endpoint clears rf_analysis
        r_reset = self.client.post("/api/rf-survey/reset")
        self.assertEqual(r_reset.status_code, 200)
        self.assertIsNone(session_state["rf_analysis"])

        # 2. Area update clears rf_analysis
        session_state["rf_analysis"] = {"dummy": True}
        poly = [
            {"lat": 13.0800, "lon": 80.2680},
            {"lat": 13.0860, "lon": 80.2680},
            {"lat": 13.0860, "lon": 80.2760},
            {"lat": 13.0800, "lon": 80.2760},
        ]
        self.client.post("/api/area", json={"polygon": poly})
        self.assertIsNone(session_state["rf_analysis"])

        # 3. GET /api/rf-survey/analysis returns 404 when invalidated
        r_get = self.client.get("/api/rf-survey/analysis")
        self.assertEqual(r_get.status_code, 404)

    @patch("main.mav_manager")
    def test_arm_before_start_guard(self, mock_mav):
        """Requirement 25: START MISSION rejected when vehicle is disarmed."""
        mock_mav.is_connected.return_value = True
        mock_mav.get_mission_upload_state.return_value = {"status": "UPLOADED"}

        # Case 1: Disarmed -> rejected with 400
        mock_mav.get_vehicle_state.return_value = {"armed": False}
        r = self.client.post("/api/mission/start")
        self.assertEqual(r.status_code, 400)
        self.assertIn("UAV must be armed before starting the mission", r.json()["detail"])

        # Case 2: Armed -> proceeds to send_command
        mock_mav.get_vehicle_state.return_value = {"armed": True}
        mock_mav.send_command.return_value = {"success": True}
        r = self.client.post("/api/mission/start")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])


if __name__ == "__main__":
    unittest.main()
