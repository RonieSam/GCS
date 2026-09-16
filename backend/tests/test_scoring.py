"""
Phase 4 unit tests. Run from backend/:

    python3 -m unittest tests.test_scoring -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scoring import (
    distance_to_polygon_boundary_m,
    score_candidates,
    top_n,
)


class TestDistanceToPolygonBoundary(unittest.TestCase):
    def setUp(self):
        # ~1.1km square (0.01 deg side), centered near (13.005, 80.005).
        self.square = [
            {"lat": 13.000, "lon": 80.000},
            {"lat": 13.000, "lon": 80.010},
            {"lat": 13.010, "lon": 80.010},
            {"lat": 13.010, "lon": 80.000},
        ]

    def test_center_is_farther_from_boundary_than_near_edge(self):
        center = distance_to_polygon_boundary_m(13.005, 80.005, self.square)
        near_edge = distance_to_polygon_boundary_m(13.0005, 80.005, self.square)
        self.assertGreater(center, near_edge)

    def test_point_on_vertex_is_zero(self):
        d = distance_to_polygon_boundary_m(13.000, 80.000, self.square)
        self.assertAlmostEqual(d, 0.0, delta=1.0)

    def test_degenerate_polygon_returns_zero(self):
        self.assertEqual(distance_to_polygon_boundary_m(13.0, 80.0, []), 0.0)
        self.assertEqual(distance_to_polygon_boundary_m(13.0, 80.0, [{"lat": 13.0, "lon": 80.0}]), 0.0)


class TestScoreCandidates(unittest.TestCase):
    def setUp(self):
        self.polygon = [
            {"lat": 13.0900, "lon": 80.2650},
            {"lat": 13.0920, "lon": 80.2760},
            {"lat": 13.0850, "lon": 80.2830},
            {"lat": 13.0760, "lon": 80.2800},
            {"lat": 13.0740, "lon": 80.2700},
            {"lat": 13.0800, "lon": 80.2630},
        ]
        self.nodes = [{"lat": 20.0, "lon": 90.0, "coverage_radius_m": 250}]  # far away -> all gap
        self.home_lat, self.home_lon = 13.0827, 80.2707

    def test_empty_candidates_returns_empty(self):
        self.assertEqual(score_candidates([], self.polygon, self.nodes), [])

    def test_original_nodes_list_not_mutated(self):
        candidates = [{"lat": 13.0800, "lon": 80.2700, "cluster_size": 10}]
        nodes_before = [dict(n) for n in self.nodes]
        score_candidates(candidates, self.polygon, self.nodes)
        self.assertEqual(self.nodes, nodes_before)

    def test_every_candidate_gets_all_score_fields(self):
        candidates = [
            {"lat": 13.0800, "lon": 80.2700, "cluster_size": 10},
            {"lat": 13.0900, "lon": 80.2650, "cluster_size": 5},
        ]
        scored = score_candidates(candidates, self.polygon, self.nodes)
        for s in scored:
            for field in (
                "coverage_improvement_pct",
                "distance_to_home_m",
                "boundary_distance_m",
                "coverage_score",
                "distance_score",
                "suitability_score",
                "score",
            ):
                self.assertIn(field, s)

    def test_scores_normalized_between_0_and_100(self):
        candidates = [
            {"lat": 13.0800, "lon": 80.2700, "cluster_size": 10},
            {"lat": 13.0900, "lon": 80.2650, "cluster_size": 5},
            {"lat": 13.0850, "lon": 80.2830, "cluster_size": 3},
        ]
        scored = score_candidates(candidates, self.polygon, self.nodes)
        for s in scored:
            for field in ("coverage_score", "distance_score", "suitability_score"):
                self.assertGreaterEqual(s[field], 0.0)
                self.assertLessEqual(s[field], 100.0)

    def test_ranked_descending_by_score(self):
        candidates = [
            {"lat": 13.0800, "lon": 80.2700, "cluster_size": 10},
            {"lat": 13.0900, "lon": 80.2650, "cluster_size": 5},
            {"lat": 13.0850, "lon": 80.2830, "cluster_size": 3},
            {"lat": 13.0760, "lon": 80.2800, "cluster_size": 8},
        ]
        scored = score_candidates(candidates, self.polygon, self.nodes)
        scores = [s["score"] for s in scored]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_closer_candidate_gets_higher_distance_score(self):
        near_home = {"lat": self.home_lat + 0.0005, "lon": self.home_lon, "cluster_size": 1}
        far_from_home = {"lat": 13.0920, "lon": 80.2760, "cluster_size": 1}
        scored = score_candidates([near_home, far_from_home], self.polygon, self.nodes)
        by_coords = {(round(s["lat"], 4), round(s["lon"], 4)): s for s in scored}
        near_score = by_coords[(round(near_home["lat"], 4), round(near_home["lon"], 4))]["distance_score"]
        far_score = by_coords[(round(far_from_home["lat"], 4), round(far_from_home["lon"], 4))]["distance_score"]
        self.assertGreater(near_score, far_score)

    def test_weights_are_configurable(self):
        candidates = [
            {"lat": 13.0800, "lon": 80.2700, "cluster_size": 10},
            {"lat": 13.0900, "lon": 80.2650, "cluster_size": 5},
        ]
        default_scored = score_candidates(candidates, self.polygon, self.nodes)
        # Put all weight on distance -> ranking should follow distance_score exactly.
        distance_only = score_candidates(
            candidates,
            self.polygon,
            self.nodes,
            coverage_weight=0.0,
            distance_weight=1.0,
            suitability_weight=0.0,
        )
        for s in distance_only:
            self.assertAlmostEqual(s["score"], s["distance_score"], places=6)
        # Sanity: changing weights can change the total score (not asserting
        # a specific ranking flip, just that the weights actually apply).
        self.assertNotEqual(
            [c["score"] for c in default_scored], [c["score"] for c in distance_only]
        )

    def test_no_gap_area_yields_zero_coverage_score(self):
        # A node that already fully covers the polygon -> no candidate can
        # improve coverage -> coverage_score should be 0 for all.
        full_coverage_nodes = [{"lat": 13.0810, "lon": 80.2725, "coverage_radius_m": 5000}]
        candidates = [{"lat": 13.0800, "lon": 80.2700, "cluster_size": 1}]
        scored = score_candidates(candidates, self.polygon, full_coverage_nodes)
        self.assertEqual(scored[0]["coverage_score"], 0.0)


class TestTopN(unittest.TestCase):
    def test_returns_first_n_of_sorted_input(self):
        scored = [{"score": 90}, {"score": 80}, {"score": 70}]
        self.assertEqual(top_n(scored, 2), [{"score": 90}, {"score": 80}])

    def test_n_larger_than_list_returns_all(self):
        scored = [{"score": 90}]
        self.assertEqual(top_n(scored, 2), [{"score": 90}])


if __name__ == "__main__":
    unittest.main()
