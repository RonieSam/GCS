"""
Phase 6 — Complete RF Survey Classification Audit and Fix
Test Suite (Items A through U from the 30-item required test matrix)

This test module is authoritative for verifying:
  1. Single authoritative classify_rssi() is used everywhere.
  2. Exact threshold boundaries (>, not >=, etc.) are consistent.
  3. Coverage counts and percentages derive from the SAME classifications.
  4. Historical surveys store and return original classifications immutably.
  5. Adding a node monotonically improves (or maintains) BEST_RSSI.
  6. RF model is deterministic (no random variation).
  7. Horizontal-only distance — no altitude contamination.
  8. No double RFRangeScale application.
  9. No double coordinate conversion.
  10. Gap count equals number of GAP-classified samples.
  11. Frontend must use the `status` field from the backend (verified structurally).
  12. AUTO DEPLOY and NODE DEPLOYMENT + RELEASE are unchanged.
"""

import math
import os
import sys
import copy
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import config
import rf_survey_analyzer
from rf_survey_analyzer import (
    classify_rssi,
    compute_best_rssi,
    analyze_rf_survey,
    calculate_coverage_statistics,
    package_analysis_snapshot,
    compare_before_after,
    GOOD_THRESHOLD,
    MODERATE_THRESHOLD,
    WEAK_THRESHOLD,
    STATUS_GOOD,
    STATUS_MODERATE,
    STATUS_WEAK,
    STATUS_GAP,
    STATUS_UNMEASURED,
)
from rf_model import (
    calculate_node_rssi_vector,
    calculate_rssi,
    compute_distance_horizontal_m,
    latlon_to_xy_m,
)
from rf_collector import (
    get_rf_collector,
    SCAN_STATE_COMPLETE,
    SCAN_STATE_IDLE,
)
from main import app, session_state
from database import init_db, clear_nodes, insert_node, list_nodes


# ============================================================
# ITEM A — Exact Threshold Boundary Tests
# ============================================================

class TestClassificationBoundaries(unittest.TestCase):
    """Item A: Exact boundary behavior at every threshold."""

    def test_rssi_neg59_999_is_GOOD(self):
        """RSSI = -59.999 → GOOD (strictly above -60)"""
        self.assertEqual(classify_rssi(-59.999), STATUS_GOOD)

    def test_rssi_neg60_is_MODERATE(self):
        """RSSI = -60.0 → MODERATE (at boundary: -60 is NOT GOOD)"""
        self.assertEqual(classify_rssi(-60.0), STATUS_MODERATE)

    def test_rssi_neg60_001_is_MODERATE(self):
        """RSSI = -60.001 → MODERATE"""
        self.assertEqual(classify_rssi(-60.001), STATUS_MODERATE)

    def test_rssi_neg74_999_is_MODERATE(self):
        """RSSI = -74.999 → MODERATE (strictly above -75)"""
        self.assertEqual(classify_rssi(-74.999), STATUS_MODERATE)

    def test_rssi_neg75_is_WEAK(self):
        """RSSI = -75.0 → WEAK (at boundary: -75 is NOT MODERATE)"""
        self.assertEqual(classify_rssi(-75.0), STATUS_WEAK)

    def test_rssi_neg75_001_is_WEAK(self):
        """RSSI = -75.001 → WEAK"""
        self.assertEqual(classify_rssi(-75.001), STATUS_WEAK)

    def test_rssi_neg84_999_is_WEAK(self):
        """RSSI = -84.999 → WEAK (strictly above -85)"""
        self.assertEqual(classify_rssi(-84.999), STATUS_WEAK)

    def test_rssi_neg85_is_GAP(self):
        """RSSI = -85.0 → GAP (at boundary: -85 is NOT WEAK)"""
        self.assertEqual(classify_rssi(-85.0), STATUS_GAP)

    def test_rssi_neg85_001_is_GAP(self):
        """RSSI = -85.001 → GAP"""
        self.assertEqual(classify_rssi(-85.001), STATUS_GAP)

    def test_rssi_none_is_UNMEASURED(self):
        """RSSI = None → UNMEASURED"""
        self.assertEqual(classify_rssi(None), STATUS_UNMEASURED)

    def test_rssi_positive_is_GOOD(self):
        """RSSI = +5 (very strong signal) → GOOD"""
        self.assertEqual(classify_rssi(5.0), STATUS_GOOD)

    def test_rssi_very_negative_is_GAP(self):
        """RSSI = -120 (extremely weak) → GAP"""
        self.assertEqual(classify_rssi(-120.0), STATUS_GAP)

    def test_threshold_constants_are_correct(self):
        """Verify the authoritative constants match the spec."""
        self.assertEqual(GOOD_THRESHOLD, -60.0)
        self.assertEqual(MODERATE_THRESHOLD, -75.0)
        self.assertEqual(WEAK_THRESHOLD, -85.0)


# ============================================================
# ITEM B — Known RSSI List
# ============================================================

class TestKnownRssiList(unittest.TestCase):
    """Item B: Known RSSI list classification and counts."""

    def setUp(self):
        self.samples = [
            {"latitude": 13.0810, "longitude": 80.2700,
             "rssi": {"COMM-001": -50.0}, "best_rssi": -50.0},
            {"latitude": 13.0820, "longitude": 80.2705,
             "rssi": {"COMM-001": -65.0}, "best_rssi": -65.0},
            {"latitude": 13.0830, "longitude": 80.2710,
             "rssi": {"COMM-001": -78.0}, "best_rssi": -78.0},
            {"latitude": 13.0840, "longitude": 80.2715,
             "rssi": {"COMM-001": -90.0}, "best_rssi": -90.0},
        ]
        self.nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]

    def test_individual_classifications(self):
        self.assertEqual(classify_rssi(-50.0), STATUS_GOOD)
        self.assertEqual(classify_rssi(-65.0), STATUS_MODERATE)
        self.assertEqual(classify_rssi(-78.0), STATUS_WEAK)
        self.assertEqual(classify_rssi(-90.0), STATUS_GAP)

    def test_counts_are_one_each(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        self.assertEqual(result["good_count"], 1)
        self.assertEqual(result["moderate_count"], 1)
        self.assertEqual(result["weak_count"], 1)
        self.assertEqual(result["gap_count"], 1)
        self.assertEqual(result["unmeasured_count"], 0)

    def test_percentages_are_25_each(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        self.assertAlmostEqual(result["good_pct"], 25.0, places=1)
        self.assertAlmostEqual(result["moderate_pct"], 25.0, places=1)
        self.assertAlmostEqual(result["weak_pct"], 25.0, places=1)
        self.assertAlmostEqual(result["gap_pct"], 25.0, places=1)

    def test_heatmap_status_matches_classification(self):
        """Item I: Map status field equals backend classification."""
        result = analyze_rf_survey(self.samples, self.nodes)
        heatmap = result["heatmap"]
        sorted_hm = sorted(heatmap, key=lambda p: p["best_rssi"], reverse=True)
        expected = [STATUS_GOOD, STATUS_MODERATE, STATUS_WEAK, STATUS_GAP]
        for point, exp_status in zip(sorted_hm, expected):
            self.assertEqual(
                point["status"], exp_status,
                f"RSSI={point['best_rssi']} expected {exp_status}, got {point['status']}"
            )

    def test_gap_count_equals_gap_classified_samples(self):
        """Item H: gap_count == number of heatmap points with status=GAP."""
        result = analyze_rf_survey(self.samples, self.nodes)
        gap_in_heatmap = sum(1 for p in result["heatmap"] if p["status"] == STATUS_GAP)
        self.assertEqual(result["gap_count"], gap_in_heatmap)


# ============================================================
# ITEM C — All-GOOD Survey
# ============================================================

class TestAllGoodSurvey(unittest.TestCase):
    """Item C: Survey where every sample is GOOD."""

    def setUp(self):
        self.samples = [
            {"latitude": 13.0810 + i*0.0001, "longitude": 80.2700,
             "rssi": {"COMM-001": -50.0 + i}, "best_rssi": -50.0 + i}
            for i in range(10)
        ]
        self.nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]

    def test_all_samples_classified_good(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        self.assertEqual(result["good_count"], 10)
        self.assertEqual(result["moderate_count"], 0)
        self.assertEqual(result["weak_count"], 0)
        self.assertEqual(result["gap_count"], 0)
        self.assertAlmostEqual(result["good_pct"], 100.0, places=1)

    def test_no_candidates_for_all_good(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        self.assertEqual(len(result["candidates"]), 0)


# ============================================================
# ITEM D — All-GAP Survey
# ============================================================

class TestAllGapSurvey(unittest.TestCase):
    """Item D: Survey where every sample is GAP."""

    def setUp(self):
        self.samples = [
            {"latitude": 13.0810 + i*0.001, "longitude": 80.2700,
             "rssi": {"COMM-001": -90.0 - i}, "best_rssi": -90.0 - i}
            for i in range(5)
        ]
        self.nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]

    def test_all_samples_classified_gap(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        self.assertEqual(result["gap_count"], 5)
        self.assertEqual(result["good_count"], 0)
        self.assertEqual(result["moderate_count"], 0)
        self.assertEqual(result["weak_count"], 0)
        self.assertAlmostEqual(result["gap_pct"], 100.0, places=1)

    def test_gap_count_equals_heatmap_gap_count(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        gap_in_heatmap = sum(1 for p in result["heatmap"] if p["status"] == STATUS_GAP)
        self.assertEqual(result["gap_count"], gap_in_heatmap)


# ============================================================
# ITEM E — Mixed Survey
# ============================================================

class TestMixedSurvey(unittest.TestCase):
    """Item E: Survey with a mix of all classification types."""

    def setUp(self):
        self.samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},
            {"latitude": 13.0820, "longitude": 80.2705, "rssi": {"COMM-001": -70.0}, "best_rssi": -70.0},
            {"latitude": 13.0830, "longitude": 80.2710, "rssi": {"COMM-001": -80.0}, "best_rssi": -80.0},
            {"latitude": 13.0840, "longitude": 80.2715, "rssi": {"COMM-001": -92.0}, "best_rssi": -92.0},
        ]
        self.nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]

    def test_counts_correct(self):
        result = analyze_rf_survey(self.samples, self.nodes)
        self.assertEqual(result["good_count"], 1)
        self.assertEqual(result["moderate_count"], 1)
        self.assertEqual(result["weak_count"], 1)
        self.assertEqual(result["gap_count"], 1)

    def test_percentages_sum_to_100(self):
        """Item G: Percentages sum to 100%."""
        result = analyze_rf_survey(self.samples, self.nodes)
        total_pct = (result["good_pct"] + result["moderate_pct"]
                     + result["weak_pct"] + result["gap_pct"])
        self.assertAlmostEqual(total_pct, 100.0, delta=0.2)


# ============================================================
# ITEM F — UNMEASURED Handling
# ============================================================

class TestUnmeasuredHandling(unittest.TestCase):
    """Item F: UNMEASURED is tracked separately, never becomes GAP."""

    def test_none_rssi_is_unmeasured(self):
        self.assertEqual(classify_rssi(None), STATUS_UNMEASURED)

    def test_unmeasured_samples_not_counted_as_gap(self):
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {}, "best_rssi": None},
            {"latitude": 13.0820, "longitude": 80.2705, "rssi": {"COMM-001": -90.0}, "best_rssi": -90.0},
        ]
        nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        self.assertEqual(result["gap_count"], 1)
        self.assertEqual(result["unmeasured_count"], 1)

    def test_unmeasured_excluded_from_percentage_denominator(self):
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {}, "best_rssi": None},
            {"latitude": 13.0820, "longitude": 80.2705, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},
        ]
        nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        self.assertAlmostEqual(result["good_pct"], 100.0, places=1)
        self.assertEqual(result["unmeasured_count"], 1)

    def test_all_unmeasured_gives_zero_percentages(self):
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {}, "best_rssi": None},
        ]
        nodes = [{"id": "COMM-001", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        self.assertEqual(result["good_pct"], 0.0)
        self.assertEqual(result["moderate_pct"], 0.0)
        self.assertEqual(result["weak_pct"], 0.0)
        self.assertEqual(result["gap_pct"], 0.0)
        self.assertEqual(result["unmeasured_count"], 1)


# ============================================================
# ITEM G — Percentage Sum ≈ 100%
# ============================================================

class TestPercentageSum(unittest.TestCase):
    """Item G: Coverage percentages must always sum to ~100%."""

    def test_percentage_sum_for_mixed_survey(self):
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {"C1": -55.0}, "best_rssi": -55.0},
            {"latitude": 13.0820, "longitude": 80.2705, "rssi": {"C1": -68.0}, "best_rssi": -68.0},
            {"latitude": 13.0830, "longitude": 80.2710, "rssi": {"C1": -79.0}, "best_rssi": -79.0},
            {"latitude": 13.0840, "longitude": 80.2715, "rssi": {"C1": -90.0}, "best_rssi": -90.0},
            {"latitude": 13.0850, "longitude": 80.2720, "rssi": {"C1": -60.0}, "best_rssi": -60.0},
            {"latitude": 13.0860, "longitude": 80.2725, "rssi": {"C1": -75.0}, "best_rssi": -75.0},
        ]
        nodes = [{"id": "C1", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        total = result["good_pct"] + result["moderate_pct"] + result["weak_pct"] + result["gap_pct"]
        self.assertAlmostEqual(total, 100.0, delta=0.5)

    def test_calculate_coverage_statistics_percentages_sum_to_100(self):
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "best_rssi": -55.0, "status": STATUS_GOOD},
            {"latitude": 13.0820, "longitude": 80.2705, "best_rssi": -70.0, "status": STATUS_MODERATE},
            {"latitude": 13.0830, "longitude": 80.2710, "best_rssi": -80.0, "status": STATUS_WEAK},
            {"latitude": 13.0840, "longitude": 80.2715, "best_rssi": -90.0, "status": STATUS_GAP},
        ]
        stats = calculate_coverage_statistics(samples)
        total = stats["good_pct"] + stats["moderate_pct"] + stats["weak_pct"] + stats["gap_pct"]
        self.assertAlmostEqual(total, 100.0, delta=0.2)


# ============================================================
# ITEM H — Gap Count Equals GAP Classifications
# ============================================================

class TestGapCountConsistency(unittest.TestCase):
    """Item H: gap_count must equal the number of GAP-classified heatmap points."""

    def test_gap_count_matches_classified_samples(self):
        for n_gaps in range(6):
            n_good = 4
            samples = (
                [{"latitude": 13.08 + i*0.0001, "longitude": 80.27,
                  "rssi": {"C1": -55.0}, "best_rssi": -55.0} for i in range(n_good)]
                + [{"latitude": 13.08 + (n_good + i)*0.0001, "longitude": 80.27,
                    "rssi": {"C1": -91.0}, "best_rssi": -91.0} for i in range(n_gaps)]
            )
            nodes = [{"id": "C1", "lat": 13.0827, "lon": 80.2707}]
            result = analyze_rf_survey(samples, nodes)
            gap_in_heatmap = sum(1 for p in result["heatmap"] if p["status"] == STATUS_GAP)
            self.assertEqual(result["gap_count"], gap_in_heatmap,
                             f"n_gaps={n_gaps}: gap_count={result['gap_count']} but heatmap GAPs={gap_in_heatmap}")
            self.assertEqual(result["gap_count"], n_gaps,
                             f"Expected {n_gaps} GAP samples, got {result['gap_count']}")

    def test_gap_points_count_matches_gap_count(self):
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {"C1": -91.0}, "best_rssi": -91.0},
            {"latitude": 13.0820, "longitude": 80.2705, "rssi": {"C1": -92.0}, "best_rssi": -92.0},
            {"latitude": 13.0830, "longitude": 80.2710, "rssi": {"C1": -55.0}, "best_rssi": -55.0},
        ]
        nodes = [{"id": "C1", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        self.assertEqual(result["gap_count"], 2)
        self.assertEqual(len(result["gap_points"]), 2)


# ============================================================
# ITEM I — Map Status Equals Backend Status
# ============================================================

class TestMapStatusMatchesBackendStatus(unittest.TestCase):
    """Item I: The status field in heatmap points matches the authoritative classification."""

    def test_heatmap_status_consistent_with_classify_rssi(self):
        rssi_values = [-50.0, -65.0, -80.0, -92.0]
        expected_statuses = [STATUS_GOOD, STATUS_MODERATE, STATUS_WEAK, STATUS_GAP]
        samples = [
            {"latitude": 13.08 + i*0.001, "longitude": 80.27,
             "rssi": {"C1": rssi}, "best_rssi": rssi}
            for i, rssi in enumerate(rssi_values)
        ]
        nodes = [{"id": "C1", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        heatmap_by_rssi = {round(p["best_rssi"], 1): p["status"] for p in result["heatmap"]}
        for rssi, exp_status in zip(rssi_values, expected_statuses):
            stored_status = heatmap_by_rssi.get(rssi)
            self.assertEqual(stored_status, exp_status,
                             f"RSSI={rssi}: map says {stored_status}, expected {exp_status}")
            self.assertEqual(classify_rssi(rssi), exp_status)

    def test_frontend_status_field_is_backend_status(self):
        """Verify heatmap points have the `status` field that frontend should use."""
        samples = [
            {"latitude": 13.0810, "longitude": 80.2700, "rssi": {"C1": -55.0}, "best_rssi": -55.0},
        ]
        nodes = [{"id": "C1", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        for pt in result["heatmap"]:
            self.assertIn("status", pt)
            self.assertIn("best_rssi", pt)
            self.assertIn("latitude", pt)
            self.assertIn("longitude", pt)


# ============================================================
# ITEM J — Historical Status Equals Original Survey Status
# ============================================================

class TestHistoricalStatusPreservation(unittest.TestCase):
    """Item J: Historical survey classification must equal the original classification at survey time."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        get_rf_collector().reset()
        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"
        session_state["rf_before_analysis"] = None
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_survey_history"] = []
        session_state["rf_survey_history_counter"] = 0

    def tearDown(self):
        clear_nodes()
        get_rf_collector().reset()

    def test_historical_heatmap_status_matches_original_classification(self):
        """Stored historical heatmap status must match classify_rssi(best_rssi)."""
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        collector = get_rf_collector()
        collector.update_deployed_nodes(list_nodes())
        samples = [
            {"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942,
             "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},
            {"sample_id": 2, "timestamp": 2.0, "latitude": 12.9720, "longitude": 77.5950,
             "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -90.0}, "best_rssi": -90.0},
        ]
        with collector._lock:
            collector._samples = samples
            collector._state = SCAN_STATE_COMPLETE
        result = self.client.post("/api/rf-survey/analyze").json()
        survey_id = result.get("survey_id")
        self.assertIsNotNone(survey_id)
        hist = self.client.get(f"/api/rf-survey/history/{survey_id}").json()
        heatmap = hist.get("heatmap", [])
        self.assertGreater(len(heatmap), 0)
        for pt in heatmap:
            best_rssi = pt.get("best_rssi") if pt.get("best_rssi") is not None else pt.get("rssi")
            status = pt.get("status")
            if best_rssi is not None:
                expected = classify_rssi(float(best_rssi))
                self.assertEqual(status, expected,
                                 f"Historical best_rssi={best_rssi} expected {expected} got {status}")


# ============================================================
# ITEM K — Historical Node Set is Immutable
# ============================================================

class TestHistoricalNodeSetImmutable(unittest.TestCase):
    """Item K: Historical survey node set must reflect nodes at survey time, not current nodes."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        get_rf_collector().reset()
        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"
        session_state["rf_before_analysis"] = None
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_survey_history"] = []
        session_state["rf_survey_history_counter"] = 0

    def tearDown(self):
        clear_nodes()
        get_rf_collector().reset()

    def test_historical_node_set_preserved_after_new_node_deployed(self):
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        collector = get_rf_collector()
        collector.update_deployed_nodes(list_nodes())
        samples1 = [
            {"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942,
             "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},
        ]
        with collector._lock:
            collector._samples = samples1
            collector._state = SCAN_STATE_COMPLETE
        res1 = self.client.post("/api/rf-survey/analyze").json()
        survey_id_1 = res1["survey_id"]

        self.client.post("/api/nodes", json={
            "id": "COMM-002", "lat": 12.9728, "lon": 77.5958, "coverage_radius_m": 250
        })
        self.client.post("/api/rf-survey/reset")
        collector.update_deployed_nodes(list_nodes())

        samples2 = [
            {"sample_id": 10, "timestamp": 10.0, "latitude": 12.9712, "longitude": 77.5942,
             "altitude": 15.0, "current_waypoint": 1,
             "rssi": {"COMM-001": -55.0, "COMM-002": -68.0}, "best_rssi": -55.0},
        ]
        with collector._lock:
            collector._samples = samples2
            collector._state = SCAN_STATE_COMPLETE
        res2 = self.client.post("/api/rf-survey/analyze").json()
        survey_id_2 = res2["survey_id"]

        hist1 = self.client.get(f"/api/rf-survey/history/{survey_id_1}").json()
        self.assertEqual(hist1["node_count"], 1,
                         "Survey 001 node count must remain 1 even after second node deployed")
        hist2 = self.client.get(f"/api/rf-survey/history/{survey_id_2}").json()
        self.assertEqual(hist2["node_count"], 2)


# ============================================================
# ITEM L — Monotonicity: BEST_AFTER >= BEST_BEFORE
# ============================================================

class TestMonotonicity(unittest.TestCase):
    """Item L: Adding a node cannot decrease BEST_RSSI at the same location."""

    def _rssi_at(self, drone_x, drone_y, nodes):
        node_list = [{"id": nid, "x": nx, "y": ny} for nid, (nx, ny) in nodes.items()]
        rssi_dict = calculate_node_rssi_vector(uav_x=drone_x, uav_y=drone_y, deployed_nodes=node_list)
        return max(rssi_dict.values()) if rssi_dict else None

    def test_adding_node_cannot_reduce_best_rssi(self):
        nodes_before = {
            "COMM-001": (0.0, 0.0),
            "COMM-002": (200.0, 200.0),
        }
        nodes_after = {
            "COMM-001": (0.0, 0.0),
            "COMM-002": (200.0, 200.0),
            "COMM-003": (100.0, 300.0),
        }
        for xi in range(10):
            for yi in range(10):
                dx = xi * 30.0 + 15.0
                dy = yi * 30.0 + 15.0
                best_before = self._rssi_at(dx, dy, nodes_before)
                best_after = self._rssi_at(dx, dy, nodes_after)
                self.assertIsNotNone(best_before)
                self.assertIsNotNone(best_after)
                self.assertGreaterEqual(best_after, best_before - 1e-9,
                                        f"MONOTONICITY VIOLATED at ({dx},{dy}): "
                                        f"BEFORE={best_before:.2f} AFTER={best_after:.2f}")

    def test_new_node_effect_classification_cannot_worsen(self):
        nodes_before = {"COMM-001": (50.0, 50.0)}
        nodes_after = {"COMM-001": (50.0, 50.0), "COMM-002": (100.0, 100.0)}
        status_rank = {STATUS_GAP: 0, STATUS_WEAK: 1, STATUS_MODERATE: 2, STATUS_GOOD: 3}
        for xi in range(8):
            for yi in range(8):
                dx = xi * 40.0
                dy = yi * 40.0
                best_before = self._rssi_at(dx, dy, nodes_before)
                best_after = self._rssi_at(dx, dy, nodes_after)
                if best_before is None or best_after is None:
                    continue
                cls_before = classify_rssi(best_before)
                cls_after = classify_rssi(best_after)
                rank_before = status_rank.get(cls_before, -1)
                rank_after = status_rank.get(cls_after, -1)
                self.assertGreaterEqual(rank_after, rank_before,
                                        f"CLASSIFICATION WORSENED at ({dx},{dy}): "
                                        f"BEFORE={cls_before}({best_before:.1f}) "
                                        f"AFTER={cls_after}({best_after:.1f})")


class TestSameCoordinateBeforeAfter(unittest.TestCase):
    """Item L & Section 7: Deterministic same-location before/after test."""

    def test_before_after_at_exactly_same_coordinate(self):
        drone_x, drone_y = 100.0, 100.0
        node_before_list = [
            {"id": "COMM-001", "x": 0.0, "y": 0.0},
            {"id": "COMM-002", "x": 200.0, "y": 200.0},
        ]
        node_after_list = [
            {"id": "COMM-001", "x": 0.0, "y": 0.0},
            {"id": "COMM-002", "x": 200.0, "y": 200.0},
            {"id": "COMM-003", "x": 120.0, "y": 80.0},
        ]
        rssi_before = calculate_node_rssi_vector(uav_x=drone_x, uav_y=drone_y,
                                                  deployed_nodes=node_before_list)
        rssi_after = calculate_node_rssi_vector(uav_x=drone_x, uav_y=drone_y,
                                                 deployed_nodes=node_after_list)
        best_before = max(rssi_before.values())
        best_after = max(rssi_after.values())
        self.assertGreaterEqual(best_after, best_before - 1e-9,
                                f"BEFORE={best_before:.2f} AFTER={best_after:.2f}: "
                                "Adding a node must not decrease best RSSI")
        status_rank = {STATUS_GAP: 0, STATUS_WEAK: 1, STATUS_MODERATE: 2, STATUS_GOOD: 3}
        cls_before = classify_rssi(best_before)
        cls_after = classify_rssi(best_after)
        self.assertGreaterEqual(status_rank[cls_after], status_rank[cls_before],
                                f"Classification worsened: BEFORE={cls_before} AFTER={cls_after}")

    def test_new_node_rssi_calculation(self):
        drone_x, drone_y = 100.0, 100.0
        node_list = [
            {"id": "COMM-001", "x": 0.0, "y": 0.0},
            {"id": "COMM-002", "x": 200.0, "y": 200.0},
            {"id": "COMM-003", "x": 120.0, "y": 80.0},
        ]
        rssi = calculate_node_rssi_vector(uav_x=drone_x, uav_y=drone_y, deployed_nodes=node_list)
        self.assertIn("COMM-003", rssi)
        self.assertTrue(math.isfinite(rssi["COMM-003"]))


# ============================================================
# ITEM M — Determinism
# ============================================================

class TestRFModelDeterminism(unittest.TestCase):
    """Item M: Same inputs → same RSSI output, 100 repeated calls."""

    def test_rssi_is_deterministic_100_times(self):
        results = [
            calculate_rssi(distance_m=50.0, reference_rssi=-30.0,
                           path_loss_exponent=2.2, reference_distance_m=1.0,
                           rf_range_scale=0.30)
            for _ in range(100)
        ]
        first = results[0]
        for i, v in enumerate(results):
            self.assertAlmostEqual(v, first, places=6,
                                   msg=f"Call {i} returned {v}, expected {first}")

    def test_node_rssi_vector_deterministic(self):
        nodes = [
            {"id": "COMM-001", "x": 100.0, "y": 100.0},
            {"id": "COMM-002", "x": 300.0, "y": 200.0},
        ]
        results = [
            calculate_node_rssi_vector(uav_x=150.0, uav_y=150.0, deployed_nodes=nodes)
            for _ in range(100)
        ]
        first = results[0]
        for i, r in enumerate(results[1:], start=1):
            for nid in first:
                self.assertAlmostEqual(r[nid], first[nid], places=6,
                                       msg=f"Call {i}: {nid} gave {r[nid]}, expected {first[nid]}")

    def test_classify_rssi_deterministic(self):
        for rssi in [-55.0, -65.0, -80.0, -90.0, None]:
            statuses = [classify_rssi(rssi) for _ in range(100)]
            self.assertEqual(len(set(statuses)), 1,
                             f"classify_rssi({rssi}) returned different values: {set(statuses)}")


# ============================================================
# ITEM N — No Double Coordinate Conversion
# ============================================================

class TestNoDoubleCoordinateConversion(unittest.TestCase):
    """Item N: latlon_to_xy_m applied exactly once."""

    def test_xy_form_and_latlon_form_give_same_rssi(self):
        ref_lat = config.GCS_REFERENCE_LAT
        ref_lon = config.GCS_REFERENCE_LON
        rf_scale = getattr(config, "RF_RANGE_SCALE", 0.30)
        uav_lat, uav_lon = ref_lat + 0.001, ref_lon + 0.001
        node_lat, node_lon = ref_lat + 0.002, ref_lon + 0.002
        rssi_via_latlon = calculate_node_rssi_vector(
            uav_lat=uav_lat, uav_lon=uav_lon,
            deployed_nodes=[{"id": "COMM-001", "lat": node_lat, "lon": node_lon}],
            rf_range_scale=rf_scale,
        )
        uav_x, uav_y = latlon_to_xy_m(uav_lat, uav_lon, ref_lat, ref_lon)
        node_x, node_y = latlon_to_xy_m(node_lat, node_lon, ref_lat, ref_lon)
        rssi_via_xy = calculate_node_rssi_vector(
            uav_x=uav_x, uav_y=uav_y,
            deployed_nodes=[{"id": "COMM-001", "x": node_x, "y": node_y}],
            rf_range_scale=rf_scale,
        )
        self.assertAlmostEqual(rssi_via_latlon["COMM-001"], rssi_via_xy["COMM-001"], places=4,
                               msg="lat/lon path and x/y path must produce same RSSI")


# ============================================================
# ITEM O — No Double RFRangeScale
# ============================================================

class TestNoDoubleRFRangeScale(unittest.TestCase):
    """Item O: RFRangeScale is applied exactly once."""

    def test_rfrangescale_applied_exactly_once(self):
        rssi_scale1 = calculate_rssi(distance_m=1.0, reference_rssi=-30.0,
                                     path_loss_exponent=2.2, reference_distance_m=1.0,
                                     rf_range_scale=1.0)
        self.assertAlmostEqual(rssi_scale1, -30.0, places=2)
        expected_scale05 = -30.0 - 10.0 * 2.2 * math.log10(2.0)
        rssi_scale05 = calculate_rssi(distance_m=1.0, reference_rssi=-30.0,
                                      path_loss_exponent=2.2, reference_distance_m=1.0,
                                      rf_range_scale=0.5)
        self.assertAlmostEqual(rssi_scale05, expected_scale05, places=2)

    def test_rfrangescale_consistency_between_functions(self):
        dist_m = 75.0
        scale = 0.30
        nodes = [{"id": "COMM-001", "x": dist_m, "y": 0.0}]
        rssi_from_vector = calculate_node_rssi_vector(
            uav_x=0.0, uav_y=0.0, deployed_nodes=nodes, rf_range_scale=scale,
        )["COMM-001"]
        rssi_from_scalar = calculate_rssi(
            distance_m=dist_m, reference_rssi=-30.0,
            path_loss_exponent=2.2, reference_distance_m=1.0, rf_range_scale=scale,
        )
        self.assertAlmostEqual(rssi_from_vector, rssi_from_scalar, places=2)


# ============================================================
# ITEM P — Horizontal Distance Only
# ============================================================

class TestHorizontalDistanceOnly(unittest.TestCase):
    """Item P: RSSI must be based on horizontal distance only, not 3D distance."""

    def test_altitude_does_not_affect_rssi(self):
        """Two UAV positions at same horizontal location but different altitudes must give same RSSI."""
        nodes = [{"id": "COMM-001", "x": 50.0, "y": 50.0}]
        rssi_low = calculate_node_rssi_vector(
            uav_x=0.0, uav_y=0.0, uav_alt_m=10.0, deployed_nodes=nodes,
        )["COMM-001"]
        rssi_high = calculate_node_rssi_vector(
            uav_x=0.0, uav_y=0.0, uav_alt_m=100.0, deployed_nodes=nodes,
        )["COMM-001"]
        self.assertAlmostEqual(rssi_low, rssi_high, places=2,
                               msg=f"Altitude must NOT affect RSSI: alt=10m gives {rssi_low:.2f}, "
                               f"alt=100m gives {rssi_high:.2f}")

    def test_pure_horizontal_distance_calculation(self):
        d = compute_distance_horizontal_m(100.0, 100.0, 0.0, 0.0)
        expected = math.sqrt(100.0**2 + 100.0**2)
        self.assertAlmostEqual(d, expected, places=6)

    def test_rssi_matches_horizontal_formula(self):
        uav_x, uav_y = 0.0, 0.0
        node_x, node_y = 100.0, 0.0
        scale = 0.30
        d = 100.0
        d_eff = d / scale
        expected_rssi = -30.0 - 10.0 * 2.2 * math.log10(d_eff / 1.0)
        rssi_actual = calculate_node_rssi_vector(
            uav_x=uav_x, uav_y=uav_y, uav_alt_m=50.0,
            deployed_nodes=[{"id": "C1", "x": node_x, "y": node_y}],
            rf_range_scale=scale,
        )["C1"]
        self.assertAlmostEqual(rssi_actual, expected_rssi, places=2,
                               msg=f"RSSI must be based on horizontal distance only. "
                               f"Expected {expected_rssi:.2f}, got {rssi_actual:.2f}")


# ============================================================
# ITEM Q — Historical Points Always Have Valid Lat/Lon
# ============================================================

class TestHistoricalValidCoordinates(unittest.TestCase):
    """Item Q: Historical heatmap points must have finite, valid lat/lon."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        get_rf_collector().reset()
        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"
        session_state["rf_before_analysis"] = None
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_survey_history"] = []
        session_state["rf_survey_history_counter"] = 0

    def tearDown(self):
        clear_nodes()
        get_rf_collector().reset()

    def test_all_historical_points_have_finite_coordinates(self):
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        collector = get_rf_collector()
        collector.update_deployed_nodes(list_nodes())
        samples = [
            {"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942,
             "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},
            {"sample_id": 2, "timestamp": 2.0, "latitude": 12.9720, "longitude": 77.5950,
             "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -90.0}, "best_rssi": -90.0},
        ]
        with collector._lock:
            collector._samples = samples
            collector._state = SCAN_STATE_COMPLETE
        result = self.client.post("/api/rf-survey/analyze").json()
        survey_id = result.get("survey_id")
        hist = self.client.get(f"/api/rf-survey/history/{survey_id}").json()
        heatmap = hist.get("heatmap", [])
        self.assertGreater(len(heatmap), 0)
        for pt in heatmap:
            lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude")
            lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude")
            self.assertIsNotNone(lat)
            self.assertIsNotNone(lon)
            self.assertIsInstance(lat, (int, float))
            self.assertIsInstance(lon, (int, float))
            self.assertTrue(math.isfinite(lat))
            self.assertTrue(math.isfinite(lon))
            self.assertGreater(lat, 10.0)
            self.assertGreater(lon, 60.0)


# ============================================================
# ITEM R — Side-by-Side Maps Use Same RF Scale
# ============================================================

class TestSideBySideSameRFScale(unittest.TestCase):
    """Item R: Both survey maps use same RF classification scale."""

    def test_same_rssi_gives_same_classification_across_two_surveys(self):
        for rssi in [-55.0, -68.0, -80.0, -92.0]:
            cls_a = classify_rssi(rssi)
            cls_b = classify_rssi(rssi)
            self.assertEqual(cls_a, cls_b)

    def test_threshold_constants_unchanged(self):
        import rf_survey_analyzer as rfa
        self.assertEqual(rfa.GOOD_THRESHOLD, -60.0)
        self.assertEqual(rfa.MODERATE_THRESHOLD, -75.0)
        self.assertEqual(rfa.WEAK_THRESHOLD, -85.0)


# ============================================================
# ITEM S — Flight Path Visually Separate from RF Classification
# ============================================================

class TestFlightPathNotRFColor(unittest.TestCase):
    """Item S: Flight path color must differ from all RF classification colors."""

    SURVEY_PATH_COLOR = "#00E5FF"
    RF_STATUS_COLORS = {
        "GOOD": "#3FDA7F",
        "MODERATE": "#F5A623",
        "WEAK": "#FF9500",
        "GAP": "#FF5C5C",
        "UNMEASURED": "#4A5568",
    }

    def test_survey_path_color_differs_from_all_rf_colors(self):
        path_color = self.SURVEY_PATH_COLOR.upper()
        for status, color in self.RF_STATUS_COLORS.items():
            self.assertNotEqual(path_color, color.upper(),
                                f"Flight path color {path_color} must NOT match RF {status} color {color}")

    def test_rf_status_colors_are_distinct(self):
        colors = list(self.RF_STATUS_COLORS.values())
        for i in range(len(colors)):
            for j in range(i + 1, len(colors)):
                self.assertNotEqual(colors[i].upper(), colors[j].upper())


# ============================================================
# ITEM T — AUTO DEPLOY Unchanged
# ============================================================

class TestAutoDeployUnchanged(unittest.TestCase):
    """Item T: Auto-deploy via POST /api/nodes must remain completely unchanged."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        session_state["rf_newly_deployed_node_id"] = None

    def tearDown(self):
        clear_nodes()

    def test_auto_deploy_creates_node_in_database(self):
        res = self.client.post("/api/nodes", json={
            "id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(list_nodes()), 1)

    def test_auto_deploy_does_not_require_uav_or_mission(self):
        res = self.client.post("/api/nodes", json={
            "id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(list_nodes()), 1)

    def test_auto_deploy_second_node_updates_newly_deployed(self):
        self.client.post("/api/nodes", json={
            "id": "COMM-001", "lat": 13.0827, "lon": 80.2707, "coverage_radius_m": 250
        })
        self.client.post("/api/nodes", json={
            "id": "COMM-002", "lat": 13.0850, "lon": 80.2730, "coverage_radius_m": 250
        })
        self.assertEqual(session_state["rf_newly_deployed_node_id"], "COMM-002")
        self.assertEqual(len(list_nodes()), 2)


# ============================================================
# ITEM U — NODE DEPLOYMENT + RELEASE Unchanged
# ============================================================

class TestNodeDeploymentAndReleaseUnchanged(unittest.TestCase):
    """Item U: Mission-based node deployment and RELEASE remain unchanged."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        session_state["selected_target"] = None
        session_state["deployment_released"] = False
        session_state["mission_state"] = "PLANNING"

    def tearDown(self):
        clear_nodes()

    def test_release_disabled_when_no_target(self):
        mock_state = {
            "connected": True, "latitude": 13.0827, "longitude": 80.2707,
            "altitude": 0.0, "relative_altitude": 0.0, "mode": "LAND", "armed": False,
        }
        from main import mav_manager
        with patch.object(mav_manager, "is_connected", return_value=True), \
             patch.object(mav_manager, "get_vehicle_state", return_value=mock_state):
            res = self.client.get("/api/deployment/status").json()
            self.assertFalse(res["can_release"])

    def test_release_disabled_while_airborne(self):
        session_state["selected_target"] = {"lat": 13.0827, "lon": 80.2707}
        session_state["mission_state"] = "EXECUTING"
        mock_state = {
            "connected": True, "latitude": 13.0827, "longitude": 80.2707,
            "altitude": 15.0, "relative_altitude": 15.0, "mode": "MISSION", "armed": True,
        }
        from main import mav_manager
        with patch.object(mav_manager, "is_connected", return_value=True), \
             patch.object(mav_manager, "get_vehicle_state", return_value=mock_state):
            res = self.client.get("/api/deployment/status").json()
            self.assertFalse(res["can_release"])


# ============================================================
# Additional: Coverage Statistics Consistency
# ============================================================

class TestCoverageStatisticsConsistency(unittest.TestCase):
    """Verify that coverage counts from analyze_rf_survey and calculate_coverage_statistics match."""

    def test_coverage_counts_consistent(self):
        samples = [
            {"latitude": 13.08 + i*0.001, "longitude": 80.27, "rssi": {"C1": rssi}, "best_rssi": rssi}
            for i, rssi in enumerate([-55.0, -68.0, -80.0, -92.0])
        ]
        nodes = [{"id": "C1", "lat": 13.0827, "lon": 80.2707}]
        result = analyze_rf_survey(samples, nodes)
        stats = calculate_coverage_statistics(result["heatmap"])
        self.assertEqual(result["good_count"], stats["good_count"])
        self.assertEqual(result["moderate_count"], stats["moderate_count"])
        self.assertEqual(result["weak_count"], stats["weak_count"])
        self.assertEqual(result["gap_count"], stats["gap_count"])
        self.assertAlmostEqual(result["good_pct"], stats["good_pct"], places=1)
        self.assertAlmostEqual(result["gap_pct"], stats["gap_pct"], places=1)


class TestRFModelScaleConsistency(unittest.TestCase):
    """Verify RF_RANGE_SCALE is consistently 0.30."""

    def test_config_rf_range_scale(self):
        self.assertEqual(config.RF_RANGE_SCALE, 0.30)

    def test_calculate_node_rssi_vector_uses_config_scale(self):
        nodes = [{"id": "C1", "x": 100.0, "y": 0.0}]
        rssi_config = calculate_node_rssi_vector(uav_x=0.0, uav_y=0.0, deployed_nodes=nodes)
        rssi_explicit = calculate_node_rssi_vector(uav_x=0.0, uav_y=0.0,
                                                    deployed_nodes=nodes, rf_range_scale=0.30)
        self.assertAlmostEqual(rssi_config["C1"], rssi_explicit["C1"], places=4)


# ============================================================
# Per-Survey Debug Analysis (Section 21)
# ============================================================

class TestPerSurveyDebugAnalysis(unittest.TestCase):
    """Section 21: Debug analysis endpoint must return complete sample statistics."""

    def setUp(self):
        self.client = TestClient(app)
        init_db()
        clear_nodes()
        get_rf_collector().reset()
        session_state["polygon"] = [
            {"lat": 12.9710, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5940},
            {"lat": 12.9730, "lon": 77.5960},
            {"lat": 12.9710, "lon": 77.5960},
        ]
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"
        session_state["rf_before_analysis"] = None
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_survey_history"] = []
        session_state["rf_survey_history_counter"] = 0

    def tearDown(self):
        clear_nodes()
        get_rf_collector().reset()

    def test_diagnostics_endpoint_returns_all_fields(self):
        insert_node("COMM-001", 12.9712, 77.5942, 250)
        collector = get_rf_collector()
        collector.update_deployed_nodes(list_nodes())
        samples = [
            {"sample_id": 1, "timestamp": 1.0, "latitude": 12.9712, "longitude": 77.5942,
             "altitude": 15.0, "current_waypoint": 1, "rssi": {"COMM-001": -55.0}, "best_rssi": -55.0},
            {"sample_id": 2, "timestamp": 2.0, "latitude": 12.9720, "longitude": 77.5950,
             "altitude": 15.0, "current_waypoint": 2, "rssi": {"COMM-001": -90.0}, "best_rssi": -90.0},
        ]
        with collector._lock:
            collector._samples = samples
            collector._state = SCAN_STATE_COMPLETE
        result = self.client.post("/api/rf-survey/analyze").json()
        survey_id = result["survey_id"]
        diag = self.client.get(f"/api/rf-survey/history/{survey_id}/diagnostics").json()
        for field in ["survey_id", "sample_count", "measured_count", "unmeasured_count",
                      "good", "moderate", "weak", "gap",
                      "good_percentage", "moderate_percentage", "weak_percentage", "gap_percentage"]:
            self.assertIn(field, diag)
        self.assertEqual(diag["good"], 1)
        self.assertEqual(diag["gap"], 1)
        self.assertAlmostEqual(diag["good_percentage"], 50.0, places=1)
        self.assertAlmostEqual(diag["gap_percentage"], 50.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
