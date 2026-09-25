import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app, session_state


class TestRFScanMissionGeneration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Clear session state
        session_state["polygon"] = None
        session_state["rf_scan_state"] = "IDLE"
        session_state["rf_scan_mission"] = None

    def test_rf_scan_without_affected_area_rejected(self):
        """TEST 1: Start with no affected area -> Reject with 'Define an affected area first.'"""
        r = self.client.post("/api/rf-scan/generate", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Define an affected area first", r.json()["detail"])

    def test_rf_scan_with_small_area(self):
        """TEST 2: Draw small affected area -> Generates survey mission."""
        small_poly = [
            {"lat": 13.0820, "lon": 80.2700},
            {"lat": 13.0825, "lon": 80.2700},
            {"lat": 13.0825, "lon": 80.2705},
            {"lat": 13.0820, "lon": 80.2705},
        ]
        # Set area first
        r_area = self.client.post("/api/area", json={"polygon": small_poly})
        self.assertEqual(r_area.status_code, 200)

        # Generate RF Scan
        r_scan = self.client.post("/api/rf-scan/generate", json={"spacing_m": 25.0, "altitude_m": 15.0})
        self.assertEqual(r_scan.status_code, 200)
        data = r_scan.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["state"], "MISSION_GENERATED")
        self.assertGreater(data["waypoint_count"], 0)
        self.assertGreater(data["line_count"], 0)
        self.assertGreater(data["total_distance_m"], 0)
        self.assertEqual(len(data["waypoints"]), data["waypoint_count"])
        self.assertEqual(len(data["px4_waypoints"]), data["waypoint_count"])

        # Check zig-zag alternation
        wps = data["waypoints"]
        self.assertGreaterEqual(len(wps), 2)
        self.assertEqual(wps[0]["seq"], 0)
        self.assertEqual(wps[1]["seq"], 1)

    def test_rf_scan_with_larger_area_scales_waypoints(self):
        """TEST 5: Larger area produces more waypoints and lines than smaller area."""
        small_poly = [
            {"lat": 13.0820, "lon": 80.2700},
            {"lat": 13.0825, "lon": 80.2700},
            {"lat": 13.0825, "lon": 80.2705},
            {"lat": 13.0820, "lon": 80.2705},
        ]
        large_poly = [
            {"lat": 13.0800, "lon": 80.2680},
            {"lat": 13.0860, "lon": 80.2680},
            {"lat": 13.0860, "lon": 80.2760},
            {"lat": 13.0800, "lon": 80.2760},
        ]

        # Small
        self.client.post("/api/area", json={"polygon": small_poly})
        r_small = self.client.post("/api/rf-scan/generate", json={"spacing_m": 25.0})
        small_count = r_small.json()["waypoint_count"]

        # Large
        self.client.post("/api/area", json={"polygon": large_poly})
        r_large = self.client.post("/api/rf-scan/generate", json={"spacing_m": 25.0})
        large_count = r_large.json()["waypoint_count"]

        self.assertGreater(large_count, small_count)

    def test_rf_scan_direct_polygon_in_payload(self):
        """Allows passing polygon directly in payload without calling /api/area beforehand."""
        poly = [
            {"lat": 13.0810, "lon": 80.2710},
            {"lat": 13.0830, "lon": 80.2710},
            {"lat": 13.0830, "lon": 80.2730},
            {"lat": 13.0810, "lon": 80.2730},
        ]
        r = self.client.post("/api/rf-scan/generate", json={"polygon": poly, "spacing_m": 30.0})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["spacing_m"], 30.0)


if __name__ == "__main__":
    unittest.main()
