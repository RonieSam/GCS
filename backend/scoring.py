"""
Phase 4 — candidate deployment site scoring.

Takes the candidates from Phase 3 (backend/candidate_generator.py) and
scores each one with a transparent, deterministic multi-criteria formula —
NOT a machine-learning model. Every number that goes into a candidate's
score can be traced back to a concrete calculation, which is the point:
an operator should be able to see *why* a location was recommended.

Three components per candidate, each normalized to 0-100 relative to the
other candidates in this batch, then combined with configurable weights:

  1. coverage_score      — how much a virtual node at this candidate
                            would improve overall coverage (Phase 2's
                            compute_coverage(), re-run with a temporary
                            extra node, then discarded).
  2. distance_score       — how close the candidate is to the UAV home/
                            launch point (closer is better — shorter
                            flight, less battery, faster deployment).
  3. suitability_score    — how far inside the affected area the
                            candidate sits, away from the polygon
                            boundary (an edge-hugging site is more
                            exposed to the affected area changing shape
                            or the candidate being just outside it).

    score = w1*coverage_score + w2*distance_score + w3*suitability_score

Weights (COVERAGE_WEIGHT / DISTANCE_WEIGHT / SUITABILITY_WEIGHT) live in
config.py. No FastAPI wiring yet (Phase 5) — this module only ranks
candidates that are handed to it.
"""

import math

from config import (
    COVERAGE_RADIUS_DEFAULT_M,
    COVERAGE_WEIGHT,
    DISTANCE_WEIGHT,
    SUITABILITY_WEIGHT,
    GRID_RESOLUTION_M,
    UAV_HOME_LAT,
    UAV_HOME_LON,
)
from coverage import compute_coverage, haversine_distance_m

_METERS_PER_DEG_LAT = 111_320.0


def _local_xy_m(lat, lon, origin_lat, origin_lon):
    """
    Project a lat/lon to local planar meters relative to an origin, using
    a flat-Earth approximation (fine at the scale of a single affected
    area — hundreds of meters to a few km). Used only for the boundary-
    distance geometry below; coverage and long-range distances still use
    real Haversine distance.
    """
    meters_per_deg_lon = _METERS_PER_DEG_LAT * max(math.cos(math.radians(origin_lat)), 1e-9)
    x = (lon - origin_lon) * meters_per_deg_lon
    y = (lat - origin_lat) * _METERS_PER_DEG_LAT
    return x, y


def _point_to_segment_distance_m(px, py, ax, ay, bx, by):
    """Distance in meters from planar point P to segment AB."""
    abx, aby = bx - ax, by - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq == 0:
        return math.hypot(px - ax, py - ay)

    t = ((px - ax) * abx + (py - ay) * aby) / seg_len_sq
    t = max(0.0, min(1.0, t))
    closest_x, closest_y = ax + t * abx, ay + t * aby
    return math.hypot(px - closest_x, py - closest_y)


def distance_to_polygon_boundary_m(lat, lon, polygon):
    """
    Distance from (lat, lon) to the nearest edge of the polygon, in
    meters. Used as the "how far from the affected area's boundary"
    suitability signal — larger means more solidly interior.

    Returns 0.0 for a degenerate polygon (fewer than 2 points forming
    an edge) rather than crashing.
    """
    n = len(polygon)
    if n < 2:
        return 0.0

    px, py = _local_xy_m(lat, lon, lat, lon)  # origin at the point itself -> (0, 0)
    best = None
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        ax, ay = _local_xy_m(a["lat"], a["lon"], lat, lon)
        bx, by = _local_xy_m(b["lat"], b["lon"], lat, lon)
        d = _point_to_segment_distance_m(px, py, ax, ay, bx, by)
        if best is None or d < best:
            best = d

    return best


def _normalize(raw_values):
    """
    Scale a list of raw (non-negative) values to 0-100, relative to the
    max in the batch. All-zero (or empty) input yields all zeros rather
    than dividing by zero — "no signal" should score as no signal, not
    as a false 100.
    """
    if not raw_values:
        return []
    max_val = max(raw_values)
    if max_val <= 0:
        return [0.0 for _ in raw_values]
    return [100.0 * v / max_val for v in raw_values]


def score_candidates(
    candidates,
    polygon,
    nodes,
    home_lat=UAV_HOME_LAT,
    home_lon=UAV_HOME_LON,
    resolution_m=None,
    coverage_weight=COVERAGE_WEIGHT,
    distance_weight=DISTANCE_WEIGHT,
    suitability_weight=SUITABILITY_WEIGHT,
    virtual_node_radius_m=COVERAGE_RADIUS_DEFAULT_M,
):
    """
    Score and rank Phase 3 candidates.

    For each candidate:
      - coverage_improvement_pct = coverage% with a virtual node at the
        candidate MINUS coverage% without it (the virtual node is added
        to a copy of `nodes` and discarded afterward — `nodes` itself is
        never mutated).
      - distance_to_home_m = Haversine distance to (home_lat, home_lon).
      - boundary_distance_m = distance_to_polygon_boundary_m().

    Each raw metric is normalized to 0-100 across this candidate batch
    (distance is inverted first, so "closer" maps to a higher score),
    then combined with the configured weights into a single score.

    Returns a list of dicts (one per candidate, richer than the Phase 3
    input), sorted by score descending:
      {
        "lat", "lon", "cluster_size",       # carried over from Phase 3
        "coverage_improvement_pct",
        "distance_to_home_m",
        "boundary_distance_m",
        "coverage_score", "distance_score", "suitability_score",
        "score",
      }

    Empty `candidates` returns an empty list rather than crashing —
    there is nothing to score.
    """
    if resolution_m is None:
        resolution_m = GRID_RESOLUTION_M

    if not candidates:
        return []

    baseline = compute_coverage(polygon, nodes, resolution_m)
    baseline_pct = baseline["coverage_percentage"]

    raw_improvements = []
    raw_distances = []
    raw_boundary_dists = []

    for c in candidates:
        virtual_node = {
            "lat": c["lat"],
            "lon": c["lon"],
            "coverage_radius_m": virtual_node_radius_m,
        }
        with_virtual = compute_coverage(polygon, nodes + [virtual_node], resolution_m)
        improvement = with_virtual["coverage_percentage"] - baseline_pct
        # Coverage can't be made worse by adding a node; guard against
        # floating-point noise producing a tiny negative value.
        raw_improvements.append(max(0.0, improvement))

        raw_distances.append(haversine_distance_m(c["lat"], c["lon"], home_lat, home_lon))
        raw_boundary_dists.append(distance_to_polygon_boundary_m(c["lat"], c["lon"], polygon))

    coverage_scores = _normalize(raw_improvements)

    # Distance is "smaller is better" — normalize the raw distances,
    # then invert, so the closest candidate lands at 100.
    max_dist = max(raw_distances) if raw_distances else 0.0
    if max_dist <= 0:
        distance_scores = [100.0 for _ in raw_distances]  # all candidates at the same spot as home
    else:
        distance_scores = [100.0 * (1.0 - d / max_dist) for d in raw_distances]

    suitability_scores = _normalize(raw_boundary_dists)

    scored = []
    for c, improvement, dist_m, boundary_m, cov_s, dist_s, suit_s in zip(
        candidates,
        raw_improvements,
        raw_distances,
        raw_boundary_dists,
        coverage_scores,
        distance_scores,
        suitability_scores,
    ):
        total = coverage_weight * cov_s + distance_weight * dist_s + suitability_weight * suit_s
        scored.append(
            {
                **c,
                "coverage_improvement_pct": improvement,
                "distance_to_home_m": dist_m,
                "boundary_distance_m": boundary_m,
                "coverage_score": cov_s,
                "distance_score": dist_s,
                "suitability_score": suit_s,
                "score": total,
            }
        )

    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored


def top_n(scored_candidates, n=2):
    """Convenience slice — the top N already-sorted scored candidates."""
    return scored_candidates[:n]


if __name__ == "__main__":
    # Standalone demo — no FastAPI/server needed. Run:
    #   cd backend && python3 scoring.py
    import json
    import os

    from candidate_generator import generate_candidates

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    with open(os.path.join(data_dir, "nodes.json")) as f:
        demo_nodes = json.load(f)

    # Same irregular hexagon as the Phase 3 demo, so the candidates here
    # match what Phase 3 prints.
    demo_polygon = [
        {"lat": 13.0900, "lon": 80.2650},
        {"lat": 13.0920, "lon": 80.2760},
        {"lat": 13.0850, "lon": 80.2830},
        {"lat": 13.0760, "lon": 80.2800},
        {"lat": 13.0740, "lon": 80.2700},
        {"lat": 13.0800, "lon": 80.2630},
    ]

    candidates = generate_candidates(demo_polygon, demo_nodes)
    ranked = score_candidates(candidates, demo_polygon, demo_nodes)

    print(f"Candidates scored: {len(ranked)}")
    for i, c in enumerate(ranked, 1):
        print(
            f"  #{i}  lat={c['lat']:.5f} lon={c['lon']:.5f}  "
            f"score={c['score']:.1f}  "
            f"(coverage+={c['coverage_improvement_pct']:.1f}pp, "
            f"dist_home={c['distance_to_home_m']:.0f}m, "
            f"boundary={c['boundary_distance_m']:.0f}m)"
        )

    print()
    print("Top 2 recommended locations:")
    for i, c in enumerate(top_n(ranked, 2), 1):
        print(f"  Location {chr(64 + i)}: lat={c['lat']:.5f}, lon={c['lon']:.5f}, score={c['score']:.1f}")
