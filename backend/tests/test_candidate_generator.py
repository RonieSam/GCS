"""
Phase 3 unit tests. Run from backend/:

    python3 -m unittest tests.test_candidate_generator -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from candidate_generator import cluster_gap_points, generate_candidates
from coverage import point_in_polygon


class TestClusterGapPoints(unittest.TestCase):
    def setUp(self):
        # Large square, small resolution -> a proper grid with clear
        # room for two separate clusters far apart from each other.
        self.square = [
            {"lat": 13.000, "lon": 80.000},
            {"lat": 13.000, "lon": 80.010},
            {"lat": 13.010, "lon": 80.010},
            {"lat": 13.010, "lon": 80.000},
        ]

    def test_single_contiguous_region_is_one_cluster(self):
        gap_points = [(13.001, 80.001), (13.001, 80.0011), (13.0011, 80.001)]
        clusters = cluster_gap_points(self.square, gap_points, resolution_m=20)
        # Points this close together at 20m resolution should merge into
        # a single cluster rather than three separate ones.
        self.assertEqual(len(clusters), 1)

    def test_no_gap_points_returns_no_clusters(self):
        self.assertEqual(cluster_gap_points(self.square, [], resolution_m=20), [])

    def test_clusters_sorted_largest_first(self):
        gap_points = [(13.001, 80.001)] + [
            (13.005 + i * 0.0002, 80.005) for i in range(4)
        ]
        clusters = cluster_gap_points(self.square, gap_points, resolution_m=20)
        sizes = [len(c) for c in clusters]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class TestGenerateCandidates(unittest.TestCase):
    def setUp(self):
        self.nodes = [{"lat": 20.0, "lon": 90.0, "coverage_radius_m": 250}]  # far away -> all gap
        # Irregular hexagon, large enough to produce a real gap area.
        self.polygon = [
            {"lat": 13.0900, "lon": 80.2650},
            {"lat": 13.0920, "lon": 80.2760},
            {"lat": 13.0850, "lon": 80.2830},
            {"lat": 13.0760, "lon": 80.2800},
            {"lat": 13.0740, "lon": 80.2700},
            {"lat": 13.0800, "lon": 80.2630},
        ]

    def test_generates_at_least_five_candidates_when_gap_area_supports_it(self):
        candidates = generate_candidates(self.polygon, self.nodes)
        self.assertGreaterEqual(len(candidates), 5)

    def test_all_candidates_inside_polygon(self):
        candidates = generate_candidates(self.polygon, self.nodes)
        for c in candidates:
            self.assertTrue(point_in_polygon(c["lat"], c["lon"], self.polygon))

    def test_candidates_are_distinct(self):
        candidates = generate_candidates(self.polygon, self.nodes)
        coords = [(round(c["lat"], 6), round(c["lon"], 6)) for c in candidates]
        self.assertEqual(len(coords), len(set(coords)))

    def test_full_coverage_yields_no_candidates(self):
        # A node right at the centroid with a huge radius covers the
        # whole polygon -> no gap points -> no candidates to propose.
        big_node = [{"lat": 13.0810, "lon": 80.2725, "coverage_radius_m": 5000}]
        candidates = generate_candidates(self.polygon, big_node)
        self.assertEqual(candidates, [])

    def test_degenerate_polygon_returns_empty(self):
        two_points = [{"lat": 13.0, "lon": 80.0}, {"lat": 13.01, "lon": 80.01}]
        self.assertEqual(generate_candidates(two_points, self.nodes), [])


if __name__ == "__main__":
    unittest.main()
