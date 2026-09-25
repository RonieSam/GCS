"""
Phase 3 — RF Model for Simulated Ground Communication Nodes.

Calculates simulated RSSI values using the same log-distance path-loss model
as Simulink's `functions/RFModel.m`.

Model formula:
    RSSI(d) = ReferenceRSSI - 10 * PathLossExponent * log10(max(d, ReferenceDistance) / ReferenceDistance)

Default parameters match Simulink exactly:
    ReferenceRSSI     = -30 dBm
    PathLossExponent  = 2.2
    ReferenceDistance = 1.0 m
"""

import math
from typing import Dict, List, Optional, Tuple

from config import DEFAULT_ALTITUDE
from coverage import haversine_distance_m

DEFAULT_REFERENCE_RSSI = -30.0   # dBm at 1 m
DEFAULT_PATH_LOSS_EXP = 2.2
DEFAULT_REF_DISTANCE = 1.0       # m


def compute_distance_3d_m(
    uav_lat: float,
    uav_lon: float,
    uav_alt_m: float,
    node_lat: float,
    node_lon: float,
    node_alt_m: float = 10.0,
) -> float:
    """Calculate 3D Euclidean distance between UAV and ground communication node in metres."""
    horizontal_dist = haversine_distance_m(uav_lat, uav_lon, node_lat, node_lon)
    vertical_dist = abs(uav_alt_m - node_alt_m)
    return math.sqrt(horizontal_dist ** 2 + vertical_dist ** 2)


def calculate_rssi(
    distance_m: float,
    reference_rssi: float = DEFAULT_REFERENCE_RSSI,
    path_loss_exponent: float = DEFAULT_PATH_LOSS_EXP,
    reference_distance_m: float = DEFAULT_REF_DISTANCE,
) -> float:
    """Calculate simulated RSSI (dBm) for a given 3D distance in metres."""
    d = max(distance_m, reference_distance_m)
    rssi = reference_rssi - (10.0 * path_loss_exponent * math.log10(d / reference_distance_m))
    return round(rssi, 2)


def calculate_node_rssi_vector(
    uav_lat: float,
    uav_lon: float,
    uav_alt_m: float,
    deployed_nodes: List[Dict],
    reference_rssi: float = DEFAULT_REFERENCE_RSSI,
    path_loss_exponent: float = DEFAULT_PATH_LOSS_EXP,
) -> Dict[str, float]:
    """Calculate RSSI for all deployed communication nodes.

    Args:
        uav_lat: UAV latitude (WGS84)
        uav_lon: UAV longitude (WGS84)
        uav_alt_m: UAV altitude in metres
        deployed_nodes: List of dicts with 'id', 'lat', 'lon', optional 'alt'
        reference_rssi: Reference RSSI at 1m (default -30 dBm)
        path_loss_exponent: Path loss exponent (default 2.2)

    Returns:
        Dict mapping node ID (e.g. 'COMM-001') to simulated RSSI in dBm.
    """
    rssi_dict = {}
    for node in deployed_nodes:
        nid = node.get("id", f"NODE-{len(rssi_dict)+1}")
        n_lat = node.get("lat")
        n_lon = node.get("lon")
        n_alt = node.get("alt", 10.0)  # ground nodes default 10m height

        if n_lat is None or n_lon is None:
            continue

        dist_3d = compute_distance_3d_m(
            uav_lat, uav_lon, uav_alt_m,
            n_lat, n_lon, n_alt
        )
        rssi_dict[nid] = calculate_rssi(
            dist_3d,
            reference_rssi=reference_rssi,
            path_loss_exponent=path_loss_exponent,
        )

    return rssi_dict
