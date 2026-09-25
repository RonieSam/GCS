"""
RF Survey Mission Planner.

Generates a lawnmower / zig-zag survey flight path covering an arbitrary
affected area polygon.

Concept:
    ┌──────────────────────────────┐
    │ → → → → → → → → → → → →      │
    │                             ↓│
    │ ← ← ← ← ← ← ← ← ← ← ← ←      │
    │↓                             │
    │ → → → → → → → → → → → →      │
    │                             ↓│
    │ ← ← ← ← ← ← ← ← ← ← ← ←      │
    └──────────────────────────────┘

Features:
- Dynamically scales to any polygon shape and size (no hardcoded survey dimensions)
- Configurable line spacing (default 25 m)
- Alternates sweep direction across consecutive survey lines
- Retains coordinates in GCS reference frame for map display, with
  PX4 simulation-space translations calculated via coordinate_mapper
- Calculates total flight path distance
"""

import math
from typing import Dict, List, Optional, Tuple

import config
import coordinate_mapper
from coverage import haversine_distance_m, point_in_polygon

_METRES_PER_DEG_LAT = 111_320.0


def _polygon_bbox(polygon: List[Dict[str, float]]) -> Tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lon, max_lon) for the polygon."""
    lats = [p["lat"] for p in polygon]
    lons = [p["lon"] for p in polygon]
    return min(lats), max(lats), min(lons), max(lons)


def _find_edge_intersections(
    polygon: List[Dict[str, float]], lat_sweep: float
) -> List[float]:
    """Find all longitude intersections between a horizontal line at lat_sweep

    and the edges of the polygon.
    """
    n = len(polygon)
    intersections = []

    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]

        lat1, lon1 = p1["lat"], p1["lon"]
        lat2, lon2 = p2["lat"], p2["lon"]

        # Ignore horizontal edges
        if lat1 == lat2:
            continue

        # Check if the horizontal line crosses this edge (half-open interval to avoid double-counting)
        if min(lat1, lat2) <= lat_sweep < max(lat1, lat2):
            t = (lat_sweep - lat1) / (lat2 - lat1)
            lon_intersect = lon1 + t * (lon2 - lon1)
            intersections.append(lon_intersect)

    intersections.sort()
    return intersections


def generate_survey_path(
    polygon: List[Dict[str, float]],
    spacing_m: float = 25.0,
    altitude_m: float = config.DEFAULT_ALTITUDE,
) -> Dict:
    """Generate a zig-zag lawnmower survey path covering the given polygon.

    Args:
        polygon: List of dicts with 'lat' and 'lon' defining the boundary vertices.
        spacing_m: Distance in metres between parallel sweep lines.
        altitude_m: Survey flight altitude in metres.

    Returns:
        dict containing:
            waypoints: List of GCS waypoints with seq, lat, lon, alt, line_idx
            px4_waypoints: List of PX4 waypoints with seq, lat, lon, alt
            total_distance_m: Total path length in metres
            waypoint_count: Number of waypoints
            spacing_m: Configured spacing
            altitude_m: Configured altitude
            line_count: Number of survey sweep lines
    """
    if not polygon or len(polygon) < 3:
        raise ValueError("Affected area polygon must have at least 3 vertices.")

    if spacing_m <= 0:
        raise ValueError("Survey spacing must be greater than zero.")

    if altitude_m <= 0:
        raise ValueError("Survey altitude must be greater than zero.")

    min_lat, max_lat, min_lon, max_lon = _polygon_bbox(polygon)
    lat_span_m = (max_lat - min_lat) * _METRES_PER_DEG_LAT

    # Determine number of sweep lines based on polygon height and spacing
    if lat_span_m < spacing_m:
        n_lines = 1
        line_lats = [(min_lat + max_lat) / 2.0]
    else:
        n_lines = max(2, int(round(lat_span_m / spacing_m)))
        step_lat = (max_lat - min_lat) / n_lines
        # Symmetrically place lines inside the bounding box from North to South
        line_lats = [max_lat - (k + 0.5) * step_lat for k in range(n_lines)]

    waypoints = []
    reverse_direction = False
    seq = 0
    actual_line_count = 0

    mapper = coordinate_mapper.get_mapper()

    for line_idx, lat_sweep in enumerate(line_lats):
        intersections = _find_edge_intersections(polygon, lat_sweep)

        # We need pairs of intersections representing enter and exit of the polygon
        valid_segments = []
        for i in range(0, len(intersections) - 1, 2):
            lon_start = intersections[i]
            lon_end = intersections[i + 1]

            # Verify the midpoint is inside the polygon
            mid_lon = (lon_start + lon_end) / 2.0
            if point_in_polygon(lat_sweep, mid_lon, polygon):
                valid_segments.append((lon_start, lon_end))

        if not valid_segments:
            continue

        actual_line_count += 1

        # For typical convex/simple shapes, valid_segments has 1 pair
        for lon_start, lon_end in valid_segments:
            if not reverse_direction:
                # West to East
                p_start = (lat_sweep, lon_start)
                p_end = (lat_sweep, lon_end)
            else:
                # East to West
                p_start = (lat_sweep, lon_end)
                p_end = (lat_sweep, lon_start)

            waypoints.append({
                "seq": seq,
                "lat": round(p_start[0], 7),
                "lon": round(p_start[1], 7),
                "alt": altitude_m,
                "line_idx": line_idx,
            })
            seq += 1

            waypoints.append({
                "seq": seq,
                "lat": round(p_end[0], 7),
                "lon": round(p_end[1], 7),
                "alt": altitude_m,
                "line_idx": line_idx,
            })
            seq += 1

        # Alternate direction for next sweep line
        reverse_direction = not reverse_direction

    # If polygon was very narrow or jagged and no waypoints generated, fallback to centroid
    if not waypoints:
        center_lat = sum(p["lat"] for p in polygon) / len(polygon)
        center_lon = sum(p["lon"] for p in polygon) / len(polygon)
        waypoints = [{
            "seq": 0,
            "lat": round(center_lat, 7),
            "lon": round(center_lon, 7),
            "alt": altitude_m,
            "line_idx": 0,
        }]

    # Compute total distance along the zig-zag path
    total_distance_m = 0.0
    for i in range(len(waypoints) - 1):
        w1 = waypoints[i]
        w2 = waypoints[i + 1]
        total_distance_m += haversine_distance_m(w1["lat"], w1["lon"], w2["lat"], w2["lon"])

    # Precalculate PX4 coordinates using coordinate mapper
    px4_waypoints = []
    for wp in waypoints:
        px4_lat, px4_lon = mapper.gcs_to_px4(wp["lat"], wp["lon"])
        px4_waypoints.append({
            "seq": wp["seq"],
            "lat": round(px4_lat, 7),
            "lon": round(px4_lon, 7),
            "alt": wp["alt"],
            "line_idx": wp["line_idx"],
        })

    return {
        "waypoints": waypoints,
        "px4_waypoints": px4_waypoints,
        "total_distance_m": round(total_distance_m, 1),
        "waypoint_count": len(waypoints),
        "spacing_m": spacing_m,
        "altitude_m": altitude_m,
        "line_count": actual_line_count,
    }
