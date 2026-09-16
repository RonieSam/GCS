"""
Phase 3 — candidate deployment location generation.

Takes the coverage-gap points from Phase 2 (backend/coverage.py) and turns
them into candidate deployment locations:

  1. Group gap points into connected clusters (grid-adjacency, not raw
     distance — two gap points are neighbors if they're adjacent cells
     on the same lattice compute_coverage() sampled).
  2. For each cluster, propose the centroid as the candidate — snapped
     to the nearest actual gap point if the centroid itself isn't
     inside the affected polygon (can happen for a crescent-shaped
     cluster wrapping a concave part of the polygon).
  3. Always return at least MIN_CANDIDATES candidates: if there aren't
     enough distinct gap clusters, the largest clusters are split along
     their longer geographic axis to produce additional, still-genuine
     candidates, rather than inventing points that aren't backed by an
     actual gap.

No FastAPI wiring yet (Phase 5). No scoring yet (Phase 4) — this module
only proposes candidates, it doesn't rank them.
"""

from config import MIN_CANDIDATES, MIN_CLUSTER_SIZE
from coverage import compute_coverage, grid_parameters, haversine_distance_m, point_in_polygon


def _grid_index(lat, lon, min_lat, min_lon, step_lat, step_lon):
    return round((lat - min_lat) / step_lat), round((lon - min_lon) / step_lon)


def cluster_gap_points(polygon, gap_points, resolution_m):
    """
    Connected-component clustering of gap points using 8-connected grid
    adjacency (aligned to the same lattice compute_coverage() sampled).

    Returns a list of clusters (each a list of (lat, lon) tuples),
    sorted largest-first.
    """
    if not gap_points:
        return []

    params = grid_parameters(polygon, resolution_m)
    if params is None:
        return []
    min_lat, min_lon, step_lat, step_lon, _, _ = params

    index_to_point = {}
    for lat, lon in gap_points:
        idx = _grid_index(lat, lon, min_lat, min_lon, step_lat, step_lon)
        index_to_point[idx] = (lat, lon)

    visited = set()
    clusters = []
    neighbor_offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    for idx in index_to_point:
        if idx in visited:
            continue

        # BFS over grid-adjacent gap cells.
        cluster = []
        queue = [idx]
        visited.add(idx)
        while queue:
            cur = queue.pop()
            cluster.append(index_to_point[cur])
            for di, dj in neighbor_offsets:
                nb = (cur[0] + di, cur[1] + dj)
                if nb in index_to_point and nb not in visited:
                    visited.add(nb)
                    queue.append(nb)

        clusters.append(cluster)

    clusters.sort(key=len, reverse=True)
    return clusters


def _centroid(points):
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return lat, lon


def _cluster_candidate(cluster_points, polygon):
    """
    The cluster's centroid, unless that falls outside the affected area
    (possible for a non-convex cluster) — in which case fall back to
    the actual gap point in the cluster closest to the centroid, which
    is guaranteed to be inside the polygon.
    """
    lat, lon = _centroid(cluster_points)
    if point_in_polygon(lat, lon, polygon):
        return lat, lon
    return min(cluster_points, key=lambda p: haversine_distance_m(p[0], p[1], lat, lon))


def _split_cluster(cluster_points):
    """
    Split a cluster into two halves along its longer geographic axis.
    Used only to produce additional candidates when there aren't enough
    distinct gap clusters yet — both halves are still real gap points,
    nothing is fabricated.
    """
    lats = [p[0] for p in cluster_points]
    lons = [p[1] for p in cluster_points]
    lat_range = max(lats) - min(lats)
    lon_range = max(lons) - min(lons)

    key = (lambda p: p[0]) if lat_range >= lon_range else (lambda p: p[1])
    ordered = sorted(cluster_points, key=key)
    mid = len(ordered) // 2
    return ordered[:mid], ordered[mid:]


def generate_candidates(
    polygon,
    nodes,
    resolution_m=None,
    min_candidates=MIN_CANDIDATES,
    min_cluster_size=MIN_CLUSTER_SIZE,
):
    """
    Full Phase 3 pipeline: run coverage analysis, cluster the gap
    points, and propose one candidate per cluster — splitting the
    largest clusters further if fewer than min_candidates distinct
    clusters exist.

    Returns a list of dicts: [{"lat", "lon", "cluster_size"}, ...],
    largest-source-cluster first. May return fewer than min_candidates
    if the affected area has too little gap area to support it (e.g.
    coverage is already near 100%) — that's reported honestly rather
    than padded with meaningless duplicates.
    """
    from config import GRID_RESOLUTION_M

    if resolution_m is None:
        resolution_m = GRID_RESOLUTION_M

    coverage_result = compute_coverage(polygon, nodes, resolution_m)
    gap_points = coverage_result["gap_points"]

    clusters = cluster_gap_points(polygon, gap_points, resolution_m)
    if not clusters:
        return []

    candidates = []
    work_queue = clusters  # already sorted largest-first

    while len(candidates) < min_candidates and work_queue:
        work_queue.sort(key=len, reverse=True)
        cluster = work_queue.pop(0)

        lat, lon = _cluster_candidate(cluster, polygon)
        candidates.append({"lat": lat, "lon": lon, "cluster_size": len(cluster)})

        # Only split a cluster further if it's big enough that both
        # halves would still clear the "meaningful" size floor —
        # otherwise we'd be manufacturing candidates from noise.
        if len(cluster) >= 2 * min_cluster_size and len(candidates) < min_candidates:
            half_a, half_b = _split_cluster(cluster)
            work_queue.append(half_a)
            work_queue.append(half_b)

    return candidates


if __name__ == "__main__":
    # Standalone demo — no FastAPI/server needed. Run:
    #   cd backend && python3 candidate_generator.py
    import json
    import os

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    with open(os.path.join(data_dir, "nodes.json")) as f:
        demo_nodes = json.load(f)

    # A larger, deliberately irregular polygon so it produces more than
    # one gap cluster — a small convex triangle (like the Phase 2 demo)
    # tends to yield just one.
    demo_polygon = [
        {"lat": 13.0900, "lon": 80.2650},
        {"lat": 13.0920, "lon": 80.2760},
        {"lat": 13.0850, "lon": 80.2830},
        {"lat": 13.0760, "lon": 80.2800},
        {"lat": 13.0740, "lon": 80.2700},
        {"lat": 13.0800, "lon": 80.2630},
    ]

    candidates = generate_candidates(demo_polygon, demo_nodes)
    print(f"Candidates generated: {len(candidates)}")
    for i, c in enumerate(candidates, 1):
        print(
            f"  Candidate {i}: lat={c['lat']:.5f}, lon={c['lon']:.5f}, "
            f"source cluster size={c['cluster_size']}"
        )
