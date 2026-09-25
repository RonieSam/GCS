"""
Phase 4 — RF Model for Ground Communication Nodes.

Calculates simulated RSSI values using the log-distance path-loss model
with configurable RF range scaling (RFRangeScale = 0.25).

Model formula:
    d = sqrt((droneX - nodeX)^2 + (droneY - nodeY)^2)   [Horizontal distance ONLY]
    d_effective = max(d, ReferenceDistance) / RFRangeScale
    RSSI(d) = ReferenceRSSI - 10 * PathLossExponent * log10(d_effective / ReferenceDistance)

Default parameters match Simulink exactly:
    ReferenceRSSI     = -30 dBm
    PathLossExponent  = 2.2
    ReferenceDistance = 1.0 m
    RFRangeScale      = 0.25 (effective horizontal coverage ~1/4 range)
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

import config
from coverage import haversine_distance_m

logger = logging.getLogger("rf_model")

DEFAULT_REFERENCE_RSSI = -30.0   # dBm at 1 m
DEFAULT_PATH_LOSS_EXP = 2.2
DEFAULT_REF_DISTANCE = 1.0       # m
METRES_PER_DEG_LAT = 111_320.0


def latlon_to_xy_m(
    lat: float,
    lon: float,
    ref_lat: Optional[float] = None,
    ref_lon: Optional[float] = None,
) -> Tuple[float, float]:
    """Convert WGS84 lat/lon to local tangent-plane ENU horizontal metres (X=East, Y=North)."""
    if ref_lat is None:
        ref_lat = getattr(config, "GCS_REFERENCE_LAT", 13.0827)
    if ref_lon is None:
        ref_lon = getattr(config, "GCS_REFERENCE_LON", 80.2707)
    cos_lat = math.cos(math.radians(ref_lat))
    x_m = (lon - ref_lon) * METRES_PER_DEG_LAT * cos_lat
    y_m = (lat - ref_lat) * METRES_PER_DEG_LAT
    return x_m, y_m


def compute_distance_horizontal_m(
    drone_x: float,
    drone_y: float,
    node_x: float,
    node_y: float,
) -> float:
    """Calculate horizontal Euclidean distance between UAV and node in metres.
    
    Formula:
        d = sqrt((droneX - nodeX)^2 + (droneY - nodeY)^2)
    """
    return math.sqrt((drone_x - node_x) ** 2 + (drone_y - node_y) ** 2)


def compute_distance_3d_m(
    uav_lat: float,
    uav_lon: float,
    uav_alt_m: float,
    node_lat: float,
    node_lon: float,
    node_alt_m: float = 10.0,
) -> float:
    """Calculate 3D Euclidean distance between UAV and ground communication node in metres.
    Kept for backwards compatibility with legacy tests.
    """
    horizontal_dist = haversine_distance_m(uav_lat, uav_lon, node_lat, node_lon)
    vertical_dist = abs(uav_alt_m - node_alt_m)
    return math.sqrt(horizontal_dist ** 2 + vertical_dist ** 2)


def calculate_rssi(
    distance_m: float,
    reference_rssi: float = DEFAULT_REFERENCE_RSSI,
    path_loss_exponent: float = DEFAULT_PATH_LOSS_EXP,
    reference_distance_m: float = DEFAULT_REF_DISTANCE,
    rf_range_scale: Optional[float] = None,
) -> float:
    """Calculate simulated RSSI (dBm) for a given horizontal distance in metres.

    Phase 4: rf_range_scale scales the effective coverage range.
    At distance_m = R * rf_range_scale, the path loss matches that of distance R.
    When rf_range_scale = 0.25, the effective coverage distance is 1/4 of normal range.
    """
    if rf_range_scale is None:
        rf_range_scale = getattr(config, "RF_RANGE_SCALE", 0.25)
    scale = max(rf_range_scale, 1e-6)
    effective_dist = max(distance_m, reference_distance_m) / scale
    rssi = reference_rssi - (10.0 * path_loss_exponent * math.log10(effective_dist / reference_distance_m))
    return round(rssi, 2)


def calculate_node_rssi_vector(
    uav_lat: Optional[float] = None,
    uav_lon: Optional[float] = None,
    uav_alt_m: Optional[float] = None,
    deployed_nodes: List[Dict] = None,
    reference_rssi: float = DEFAULT_REFERENCE_RSSI,
    path_loss_exponent: float = DEFAULT_PATH_LOSS_EXP,
    reference_distance_m: float = DEFAULT_REF_DISTANCE,
    rf_range_scale: Optional[float] = None,
    uav_x: Optional[float] = None,
    uav_y: Optional[float] = None,
    ref_lat: Optional[float] = None,
    ref_lon: Optional[float] = None,
) -> Dict[str, float]:
    """Calculate simulated RSSI for each currently deployed communication node.

    Uses strictly horizontal distance:
        d = sqrt((droneX - nodeX)^2 + (droneY - nodeY)^2)
    Excludes altitude from RF distance calculation to avoid elevation distortion.

    Args:
        uav_lat: UAV latitude (WGS84, optional if uav_x/uav_y provided)
        uav_lon: UAV longitude (WGS84, optional if uav_x/uav_y provided)
        uav_alt_m: UAV altitude in metres (unused in horizontal distance model)
        deployed_nodes: List of dicts with node definitions ('id', 'lat'/'x', 'lon'/'y')
        reference_rssi: Reference RSSI at reference distance (default -30 dBm)
        path_loss_exponent: Path loss exponent n (default 2.2)
        reference_distance_m: Reference distance d0 (default 1.0 m)
        rf_range_scale: Effective range scale (default 0.25 for Phase 4)
        uav_x: UAV X in local tangent plane metres (optional)
        uav_y: UAV Y in local tangent plane metres (optional)
        ref_lat: Reference origin latitude for coordinate conversion
        ref_lon: Reference origin longitude for coordinate conversion

    Returns:
        Dict mapping node ID (e.g. 'COMM-001') to simulated RSSI in dBm.
    """
    if ref_lat is None:
        ref_lat = getattr(config, "GCS_REFERENCE_LAT", 13.0827)
    if ref_lon is None:
        ref_lon = getattr(config, "GCS_REFERENCE_LON", 80.2707)
    if rf_range_scale is None:
        rf_range_scale = getattr(config, "RF_RANGE_SCALE", 0.25)
    if deployed_nodes is None:
        deployed_nodes = []

    # Resolve UAV horizontal coordinates (East X, North Y in metres)
    if uav_x is None or uav_y is None:
        if uav_lat is not None and uav_lon is not None:
            ux, uy = latlon_to_xy_m(uav_lat, uav_lon, ref_lat, ref_lon)
        else:
            return {}
    else:
        ux, uy = float(uav_x), float(uav_y)

    rssi_dict = {}

    # Sort deterministically by node ID
    sorted_nodes = sorted(deployed_nodes, key=lambda n: str(n.get("id", "")))

    for idx, node in enumerate(sorted_nodes):
        nid = str(node.get("id") or f"NODE-{idx + 1:03d}")

        # Resolve Node horizontal coordinates (East X, North Y in metres)
        if "x" in node and "y" in node and node["x"] is not None and node["y"] is not None:
            nx = float(node["x"])
            ny = float(node["y"])
        else:
            n_lat = node.get("lat") if node.get("lat") is not None else node.get("latitude")
            n_lon = node.get("lon") if node.get("lon") is not None else node.get("longitude")
            if n_lat is None or n_lon is None:
                continue
            nx, ny = latlon_to_xy_m(float(n_lat), float(n_lon), ref_lat, ref_lon)

        # Pure horizontal Euclidean distance in metres
        dist_h = compute_distance_horizontal_m(ux, uy, nx, ny)

        # Calculate effective distance scaled by RFRangeScale (applied exactly once)
        scale = max(rf_range_scale, 1e-6)
        effective_dist = max(dist_h, reference_distance_m) / scale

        # Calculate log-distance path loss
        rssi = reference_rssi - (10.0 * path_loss_exponent * math.log10(effective_dist / reference_distance_m))
        rssi = round(rssi, 2)

        rssi_dict[nid] = rssi

        # Diagnostic output (per user spec)
        logger.info(
            f"{nid} UAV=({ux:.1f},{uy:.1f}) NODE=({nx:.1f},{ny:.1f}) "
            f"distance={dist_h:.2f}m effectiveDistance={effective_dist:.2f}m "
            f"P0={reference_rssi:.0f} n={path_loss_exponent:.1f} RSSI={rssi:.2f}dBm"
        )

    return rssi_dict
