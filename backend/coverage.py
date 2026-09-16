"""
Phase 2 — coverage analysis.

A SIMPLE PLANNING-LEVEL coverage model, deliberately not an RF propagation
model:

  1. The affected polygon is sampled as a grid of points.
  2. For each grid point, compute the distance to every existing node.
  3. If any node's coverage radius reaches the point, it's COVERED.
     Otherwise it's a COVERAGE GAP.

No FastAPI/backend wiring yet — that's Phase 5. This module is plain,
dependency-free Python so it can be exercised directly (see the demo at
the bottom) and by the unit tests in backend/tests/test_coverage.py.
"""

import math

from config import COVERAGE_RADIUS_DEFAULT_M, GRID_RESOLUTION_M

# Meters per degree of latitude is ~constant; longitude varies with latitude.
_METERS_PER_DEG_LAT = 111_320.0


def haversine_distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in meters."""
    r = 6_371_000.0  # mean Earth radius, meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def point_in_polygon(lat, lon, polygon):
    """
    Ray-casting point-in-polygon test.

    polygon: list of {"lat": ..., "lon": ...} dicts, in order, describing
    a closed ring (the first point is not repeated at the end).
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["lon"], polygon[i]["lat"]
        xj, yj = polygon[j]["lon"], polygon[j]["lat"]

        # Does the horizontal ray at this latitude cross edge (j -> i)?
        crosses = (yi > lat) != (yj > lat)
        if crosses:
            x_intersect = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_intersect:
                inside = not inside

        j = i

    return inside


def _polygon_bbox(polygon):
    lats = [p["lat"] for p in polygon]
    lons = [p["lon"] for p in polygon]
    return min(lats), max(lats), min(lons), max(lons)


def grid_parameters(polygon, resolution_m=GRID_RESOLUTION_M):
    """
    The lattice parameters generate_grid() samples on: (min_lat, min_lon,
    step_lat, step_lon, n_lat_steps, n_lon_steps).

    Exposed so callers that need to re-derive a grid point's (row, col)
    index — e.g. Phase 3's gap clustering, which walks grid neighbors —
    can align to exactly the same lattice generate_grid() used, instead
    of duplicating the step-size math. Returns None for a degenerate
    polygon (fewer than 3 points) or a resolution that yields no steps.
    """
    if len(polygon) < 3:
        return None

    min_lat, max_lat, min_lon, max_lon = _polygon_bbox(polygon)

    avg_lat = (min_lat + max_lat) / 2
    step_lat = resolution_m / _METERS_PER_DEG_LAT
    meters_per_deg_lon = _METERS_PER_DEG_LAT * max(math.cos(math.radians(avg_lat)), 1e-9)
    step_lon = resolution_m / meters_per_deg_lon

    if step_lat <= 0 or step_lon <= 0:
        return None

    n_lat_steps = int((max_lat - min_lat) / step_lat) + 1
    n_lon_steps = int((max_lon - min_lon) / step_lon) + 1

    return min_lat, min_lon, step_lat, step_lon, n_lat_steps, n_lon_steps


def generate_grid(polygon, resolution_m=GRID_RESOLUTION_M):
    """
    Sample the polygon's bounding box on a regular grid (spacing
    ~resolution_m), keeping only points that fall inside the polygon.

    Returns a list of (lat, lon) tuples. Empty list for a degenerate
    polygon (fewer than 3 points) or one so small no grid point lands
    inside it.
    """
    params = grid_parameters(polygon, resolution_m)
    if params is None:
        return []

    min_lat, min_lon, step_lat, step_lon, n_lat_steps, n_lon_steps = params

    # Index-based stepping (lat = min_lat + i*step_lat) rather than
    # repeated += accumulation, so floating-point error can't drift the
    # lattice — this matters because Phase 3 re-derives each point's
    # (i, j) index from its lat/lon to walk grid neighbors, and that
    # round-trip only stays exact if the lattice itself doesn't drift.
    points = []
    for i in range(n_lat_steps):
        lat = min_lat + i * step_lat
        for j in range(n_lon_steps):
            lon = min_lon + j * step_lon
            if point_in_polygon(lat, lon, polygon):
                points.append((lat, lon))

    return points


def compute_coverage(polygon, nodes, resolution_m=GRID_RESOLUTION_M):
    """
    Grid the affected polygon and classify each point as covered or a
    coverage gap against the given nodes.

    nodes: list of {"lat", "lon", "coverage_radius_m"} dicts (radius is
    optional per node; falls back to COVERAGE_RADIUS_DEFAULT_M).

    Returns a dict:
      {
        "total_points": int,
        "covered_points": [(lat, lon), ...],
        "gap_points": [(lat, lon), ...],
        "coverage_percentage": float,
        "gap_percentage": float,
      }
    total_points == 0 (no grid points — degenerate/too-small polygon)
    yields 0.0 for both percentages rather than dividing by zero.
    """
    grid = generate_grid(polygon, resolution_m)
    total = len(grid)

    if total == 0:
        return {
            "total_points": 0,
            "covered_points": [],
            "gap_points": [],
            "coverage_percentage": 0.0,
            "gap_percentage": 0.0,
        }

    covered_points = []
    gap_points = []

    for lat, lon in grid:
        covered = False
        for node in nodes:
            radius = node.get("coverage_radius_m", COVERAGE_RADIUS_DEFAULT_M)
            if haversine_distance_m(lat, lon, node["lat"], node["lon"]) <= radius:
                covered = True
                break
        (covered_points if covered else gap_points).append((lat, lon))

    coverage_pct = 100.0 * len(covered_points) / total
    gap_pct = 100.0 - coverage_pct

    return {
        "total_points": total,
        "covered_points": covered_points,
        "gap_points": gap_points,
        "coverage_percentage": coverage_pct,
        "gap_percentage": gap_pct,
    }


if __name__ == "__main__":
    # Standalone demo — no FastAPI/server needed. Run:
    #   cd backend && python3 coverage.py
    import json
    import os

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    with open(os.path.join(data_dir, "nodes.json")) as f:
        demo_nodes = json.load(f)

    # A small triangle straddling one existing node (partial coverage
    # expected) — deliberately not centered on any node, so the demo
    # shows both covered and gap points.
    demo_polygon = [
        {"lat": 13.0845, "lon": 80.2690},
        {"lat": 13.0845, "lon": 80.2740},
        {"lat": 13.0800, "lon": 80.2715},
    ]

    result = compute_coverage(demo_polygon, demo_nodes)
    print(f"Grid points sampled : {result['total_points']}")
    print(f"Covered             : {len(result['covered_points'])}")
    print(f"Gap                 : {len(result['gap_points'])}")
    print(f"Coverage %          : {result['coverage_percentage']:.1f}")
    print(f"Gap %               : {result['gap_percentage']:.1f}")
