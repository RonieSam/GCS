"""
Phase 2 unit tests. Run from backend/:

    python3 -m unittest tests.test_coverage -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from coverage import (
    compute_coverage,
    generate_grid,
    haversine_distance_m,
    point_in_polygon,
)


class TestHaversineDistance(unittest.TestCase):
    def test_same_point_is_zero(self):
        d = haversine_distance_m(13.0827, 80.2707, 13.0827, 80.2707)
        self.assertAlmostEqual(d, 0.0, places=6)

    def test_known_short_distance(self):
        # ~0.001 deg latitude ~ 111.32 m at any longitude.
        d = haversine_distance_m(13.0000, 80.0000, 13.0010, 80.0000)
        self.assertAlmostEqual(d, 111.32, delta=1.0)

    def test_symmetric(self):
        d1 = haversine_distance_m(13.05, 80.20, 13.09, 80.28)
        d2 = haversine_distance_m(13.09, 80.28, 13.05, 80.20)
        self.assertAlmostEqual(d1, d2, places=6)


class TestPointInPolygon(unittest.TestCase):
    def setUp(self):
        # A simple square: lat 13.00-13.01, lon 80.00-80.01
        self.square = [
            {"lat": 13.00, "lon": 80.00},
            {"lat": 13.00, "lon": 80.01},
            {"lat": 13.01, "lon": 80.01},
            {"lat": 13.01, "lon": 80.00},
        ]

    def test_point_inside(self):
        self.assertTrue(point_in_polygon(13.005, 80.005, self.square))

    def test_point_outside(self):
        self.assertFalse(point_in_polygon(13.02, 80.02, self.square))
        self.assertFalse(point_in_polygon(12.99, 80.005, self.square))

    def test_degenerate_polygon_returns_false(self):
        self.assertFalse(point_in_polygon(13.005, 80.005, []))
        self.assertFalse(
            point_in_polygon(
                13.005, 80.005, [{"lat": 13.0, "lon": 80.0}, {"lat": 13.01, "lon": 80.01}]
            )
        )


class TestCoverageCalculation(unittest.TestCase):
    def setUp(self):
        # Square fully containing a single node at its center, radius
        # large enough to cover the whole square -> 100% coverage expected.
        self.square = [
            {"lat": 13.000, "lon": 80.000},
            {"lat": 13.000, "lon": 80.002},
            {"lat": 13.002, "lon": 80.002},
            {"lat": 13.002, "lon": 80.000},
        ]
        self.center_node = [{"lat": 13.001, "lon": 80.001, "coverage_radius_m": 500}]
        self.far_node = [{"lat": 20.000, "lon": 90.000, "coverage_radius_m": 250}]

    def test_full_coverage_when_node_reaches_everywhere(self):
        result = compute_coverage(self.square, self.center_node, resolution_m=25)
        self.assertGreater(result["total_points"], 0)
        self.assertEqual(len(result["gap_points"]), 0)
        self.assertAlmostEqual(result["coverage_percentage"], 100.0, delta=0.01)

    def test_full_gap_when_no_node_in_range(self):
        result = compute_coverage(self.square, self.far_node, resolution_m=25)
        self.assertGreater(result["total_points"], 0)
        self.assertEqual(len(result["covered_points"]), 0)
        self.assertAlmostEqual(result["gap_percentage"], 100.0, delta=0.01)

    def test_percentages_sum_to_100(self):
        result = compute_coverage(self.square, self.center_node, resolution_m=25)
        self.assertAlmostEqual(
            result["coverage_percentage"] + result["gap_percentage"], 100.0, places=6
        )

    def test_node_missing_radius_uses_default(self):
        node_no_radius = [{"lat": 13.001, "lon": 80.001}]
        # Should not raise, and should still produce a coverage result.
        result = compute_coverage(self.square, node_no_radius, resolution_m=25)
        self.assertGreaterEqual(result["total_points"], 0)


class TestInvalidInput(unittest.TestCase):
    def test_polygon_with_too_few_points_yields_empty_grid(self):
        two_points = [{"lat": 13.0, "lon": 80.0}, {"lat": 13.01, "lon": 80.01}]
        self.assertEqual(generate_grid(two_points), [])

    def test_empty_polygon_yields_no_crash(self):
        result = compute_coverage([], [{"lat": 13.0, "lon": 80.0, "coverage_radius_m": 250}])
        self.assertEqual(result["total_points"], 0)
        self.assertEqual(result["coverage_percentage"], 0.0)
        self.assertEqual(result["gap_percentage"], 0.0)

    def test_no_nodes_yields_full_gap(self):
        square = [
            {"lat": 13.000, "lon": 80.000},
            {"lat": 13.000, "lon": 80.002},
            {"lat": 13.002, "lon": 80.002},
            {"lat": 13.002, "lon": 80.000},
        ]
        result = compute_coverage(square, [], resolution_m=25)
        self.assertGreater(result["total_points"], 0)
        self.assertEqual(len(result["covered_points"]), 0)


if __name__ == "__main__":
    unittest.main()
