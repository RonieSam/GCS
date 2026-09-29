"""
Phase 5 — RF Survey Analyzer.

Implements the MATLAB CandidatePlacement algorithm in Python, operating
on the *real* RF survey samples collected by RFSurveyCollector during
an actual UAV RF scan.

Algorithm (identical to MATLAB CandidatePlacement.m / setupGCS.m):

    RF samples
        ↓
    bestRSSI = max valid RSSI among active nodes per sample
        ↓
    Coverage classification per sample (GOOD / MODERATE / WEAK / GAP)
        ↓
    Gap points = samples where bestRSSI <= GAP_THRESHOLD (-85 dBm)
        ↓
    Spatial clustering using single-link clustering with
        GapClusterDistance = 250 * RFRangeScale = 75 m  (at RFRangeScale=0.30)
        ↓
    Cluster centroid = candidate position (lat, lon)
        ↓
    Score per candidate:
        score = gapPointsInCluster * 10 + nearestNodeDistance_m * 0.1
        ↓
    Sort descending — Candidate 1 = best

Design guarantees:
  - Deterministic: same input → same output, always.
  - No randomness (no random.*, no uuid generation, no perturbation).
  - Candidate generation uses real samples only.
  - Heatmap data = real survey samples (not interpolated).
  - Candidates are never inserted into the node database.
"""

import math
from typing import Dict, List, Optional, Tuple

import config
from coverage import haversine_distance_m, point_in_polygon

# ---------------------------------------------------------------------------
# Coverage classification thresholds (must match MATLAB and frontend exactly)
# ---------------------------------------------------------------------------

GOOD_THRESHOLD     = -60.0   # dBm  RSSI > -60     → GOOD
MODERATE_THRESHOLD = -75.0   # dBm  -75 < RSSI ≤ -60 → MODERATE
WEAK_THRESHOLD     = -85.0   # dBm  -85 < RSSI ≤ -75 → WEAK
                              #      RSSI ≤ -85       → GAP

STATUS_GOOD     = "GOOD"
STATUS_MODERATE = "MODERATE"
STATUS_WEAK     = "WEAK"
STATUS_GAP      = "GAP"
STATUS_UNMEASURED = "UNMEASURED"

# ---------------------------------------------------------------------------
# Clustering constants (match MATLAB exactly)
# ---------------------------------------------------------------------------

# GapClusterDistance = 250 * RFRangeScale (from MATLAB setupGCS.m)
# At RFRangeScale = 0.30: GapClusterDistance = 75 m
_GAP_CLUSTER_DISTANCE_SCALE = 250.0   # metres before scaling


def _gap_cluster_distance_m() -> float:
    """Dynamic cluster distance: 250 * RFRangeScale (from config)."""
    scale = getattr(config, "RF_RANGE_SCALE", 0.30)
    return _GAP_CLUSTER_DISTANCE_SCALE * scale


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_rssi(best_rssi: Optional[float]) -> str:
    """Classify a bestRSSI value into coverage status string."""
    if best_rssi is None:
        return STATUS_UNMEASURED
    if best_rssi > GOOD_THRESHOLD:
        return STATUS_GOOD
    if best_rssi > MODERATE_THRESHOLD:
        return STATUS_MODERATE
    if best_rssi > WEAK_THRESHOLD:
        return STATUS_WEAK
    return STATUS_GAP


def compute_best_rssi(rssi_dict: dict, active_node_ids: Optional[set] = None) -> Optional[float]:
    """
    Compute bestRSSI as the strongest valid RSSI among active nodes.

    If active_node_ids is provided, only those IDs are considered.
    Returns None if no valid RSSI is available for this sample.

    Example:
        NODE-001 = -90, NODE-002 = -74, NODE-003 = -83
        → bestRSSI = -74 dBm
    """
    if not rssi_dict:
        return None

    valid_values = []
    for node_id, val in rssi_dict.items():
        if active_node_ids is not None and node_id not in active_node_ids:
            continue
        try:
            v = float(val)
            if math.isfinite(v):
                valid_values.append(v)
        except (TypeError, ValueError):
            continue

    return max(valid_values) if valid_values else None


# ---------------------------------------------------------------------------
# Spatial single-link clustering (exact MATLAB port)
# ---------------------------------------------------------------------------

def _cluster_gap_points_single_link(
    gap_points: List[Dict],
    gap_cluster_distance_m: float,
) -> List[List[Dict]]:
    """
    Single-link spatial clustering.

    Two gap points belong to the same cluster if their Haversine distance
    is <= gap_cluster_distance_m.

    This is the exact algorithm from MATLAB CandidatePlacement.m stepImpl():
        for i = 1:gapCount
            if regionId(i) ~= 0, continue, end
            regionId(i) = nextRegion;
            changed = true;
            while changed
                changed = false;
                for j = 1:gapCount
                    if regionId(j) ~= 0, continue, end
                    inRegion = find(regionId == nextRegion);
                    d = hypot(gapX(inRegion) - gapX(j), gapY(inRegion) - gapY(j));
                    if any(d <= GapClusterDistance)
                        regionId(j) = nextRegion;
                        changed = true;
                    end
                end
            end
            nextRegion = nextRegion + 1;
        end

    Returns list of clusters (each a list of point dicts with 'lat', 'lon').
    Deterministic: processes points in the order they are given.
    """
    if not gap_points:
        return []

    n = len(gap_points)
    region_id = [0] * n   # 0 = unassigned

    next_region = 1
    for i in range(n):
        if region_id[i] != 0:
            continue

        region_id[i] = next_region
        changed = True
        while changed:
            changed = False
            for j in range(n):
                if region_id[j] != 0:
                    continue
                # Find all points already in this region
                in_region_indices = [k for k in range(n) if region_id[k] == next_region]
                # Check if point j is within cluster distance of ANY region member
                for k in in_region_indices:
                    d = haversine_distance_m(
                        gap_points[k]["lat"], gap_points[k]["lon"],
                        gap_points[j]["lat"], gap_points[j]["lon"],
                    )
                    if d <= gap_cluster_distance_m:
                        region_id[j] = next_region
                        changed = True
                        break

        next_region += 1

    num_regions = next_region - 1
    clusters: List[List[Dict]] = [[] for _ in range(num_regions)]
    for i in range(n):
        region = region_id[i]
        if 1 <= region <= num_regions:
            clusters[region - 1].append(gap_points[i])

    # Return non-empty clusters only
    return [c for c in clusters if c]


# ---------------------------------------------------------------------------
# Candidate generation (full pipeline)
# ---------------------------------------------------------------------------

def analyze_rf_survey(
    samples: List[Dict],
    deployed_nodes: List[Dict],
    affected_area: Optional[List[Dict]] = None,
) -> Dict:
    """
    Full Phase 5 RF analysis pipeline operating on real survey samples.

    Parameters
    ----------
    samples : list of sample dicts from RFSurveyCollector
        Each sample must have: latitude, longitude, rssi (dict)
        May optionally have: best_rssi (float)
    deployed_nodes : list of node dicts from the database
        Each must have: id, lat, lon
    affected_area : optional list of polygon vertex dicts [{'lat': ..., 'lon': ...}]
        If provided, samples outside the polygon are excluded from the heatmap
        and candidate generation (Phase 5 Requirement 15).

    Returns
    -------
    dict with keys:
        survey_samples      : int
        good_count          : int
        moderate_count      : int
        weak_count          : int
        gap_count           : int
        unmeasured_count    : int
        gap_cluster_count   : int
        gap_cluster_distance_m : float
        rf_range_scale      : float
        heatmap             : list of {latitude, longitude, best_rssi, status}
        samples             : alias for heatmap (Requirement 7)
        gap_points          : list of {latitude, longitude, best_rssi}
        candidates          : list of {rank, latitude, longitude, local_x, local_y,
                                       gap_points, nearest_node_distance_m, score}
    """
    active_node_ids = {str(n.get("id", "")) for n in deployed_nodes}
    rf_range_scale = getattr(config, "RF_RANGE_SCALE", 0.30)
    gap_cluster_distance_m = _gap_cluster_distance_m()

    # Reference origin for local_x, local_y (metres)
    ref_lat = getattr(config, "GCS_REFERENCE_LAT", 13.0827)
    ref_lon = getattr(config, "GCS_REFERENCE_LON", 80.2707)
    cos_ref = math.cos(math.radians(ref_lat))
    metres_per_deg = 111320.0

    # --- Step 1: Classify each sample ---
    heatmap_points = []
    gap_point_list = []

    good_count = 0
    moderate_count = 0
    weak_count = 0
    gap_count = 0
    unmeasured_count = 0

    has_polygon = affected_area is not None and len(affected_area) >= 3

    for s in samples:
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is None or lon is None:
            continue

        # Requirement 15: Keep heatmap and analysis constrained to affected area
        if has_polygon and not point_in_polygon(lat, lon, affected_area):
            continue

        rssi_dict = s.get("rssi") or {}

        # Recompute bestRSSI from active nodes (handles node deletions/pruning)
        best_rssi = compute_best_rssi(rssi_dict, active_node_ids)
        if best_rssi is None and "best_rssi" in s and s["best_rssi"] is not None:
            # Fallback to pre-computed value if rssi dict is empty
            try:
                best_rssi = float(s["best_rssi"])
                if not math.isfinite(best_rssi):
                    best_rssi = None
            except (TypeError, ValueError):
                best_rssi = None

        status = classify_rssi(best_rssi)

        heatmap_points.append({
            "latitude": lat,
            "longitude": lon,
            "best_rssi": round(best_rssi, 2) if best_rssi is not None else None,
            "status": status,
        })

        if status == STATUS_GOOD:
            good_count += 1
        elif status == STATUS_MODERATE:
            moderate_count += 1
        elif status == STATUS_WEAK:
            weak_count += 1
        elif status == STATUS_GAP:
            gap_count += 1
            gap_point_list.append({
                "latitude": lat,
                "longitude": lon,
                "best_rssi": round(best_rssi, 2) if best_rssi is not None else None,
            })
        else:  # UNMEASURED
            unmeasured_count += 1

    # --- Step 2: Cluster gap points ---
    gap_dicts_for_clustering = [
        {"lat": p["latitude"], "lon": p["longitude"]}
        for p in gap_point_list
    ]
    clusters = _cluster_gap_points_single_link(gap_dicts_for_clustering, gap_cluster_distance_m)

    # --- Step 3: Compute centroid and score per cluster ---
    raw_candidates = []

    for cluster in clusters:
        n_pts = len(cluster)
        if n_pts == 0:
            continue

        # Centroid
        centroid_lat = sum(p["lat"] for p in cluster) / n_pts
        centroid_lon = sum(p["lon"] for p in cluster) / n_pts

        # Nearest node distance (in metres via Haversine)
        if deployed_nodes:
            nearest_dist = min(
                haversine_distance_m(centroid_lat, centroid_lon, float(n.get("lat", 0)), float(n.get("lon", 0)))
                for n in deployed_nodes
            )
        else:
            nearest_dist = 0.0

        score = n_pts * 10.0 + nearest_dist * 0.1

        # Local ENU coordinates (metres) for debugging / inspection (Requirement 22)
        local_x = (centroid_lon - ref_lon) * metres_per_deg * cos_ref
        local_y = (centroid_lat - ref_lat) * metres_per_deg

        raw_candidates.append({
            "latitude": centroid_lat,
            "longitude": centroid_lon,
            "local_x": round(local_x, 2),
            "local_y": round(local_y, 2),
            "gap_points": n_pts,
            "nearest_node_distance_m": round(nearest_dist, 1),
            "score": round(score, 2),
        })

    # --- Step 4: Rank descending by score ---
    raw_candidates.sort(key=lambda c: c["score"], reverse=True)

    candidates = []
    for rank, c in enumerate(raw_candidates, start=1):
        # Validate coordinates (Requirement 22: no null/NaN/undefined coordinates)
        lat = c["latitude"]
        lon = c["longitude"]
        if lat is None or lon is None or not math.isfinite(lat) or not math.isfinite(lon):
            continue

        candidates.append({
            "rank": rank,
            "latitude": round(lat, 7),
            "longitude": round(lon, 7),
            "local_x": c["local_x"],
            "local_y": c["local_y"],
            "gap_points": c["gap_points"],
            "nearest_node_distance_m": c["nearest_node_distance_m"],
            "score": c["score"],
        })

    return {
        "survey_samples": len(heatmap_points),
        "good_count": good_count,
        "moderate_count": moderate_count,
        "weak_count": weak_count,
        "gap_count": gap_count,
        "unmeasured_count": unmeasured_count,
        "gap_cluster_count": len(clusters),
        "gap_cluster_distance_m": round(gap_cluster_distance_m, 1),
        "rf_range_scale": rf_range_scale,
        "heatmap": heatmap_points,
        "samples": heatmap_points,  # Requirement 7 alias
        "gap_points": gap_point_list,
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Phase 6 — Re-Scan & Before/After Verification
# ---------------------------------------------------------------------------


def calculate_coverage_percentages(result: Dict) -> Dict:
    """Calculate exact coverage percentages from analysis counts."""
    total = result.get("survey_samples", 0)
    if total <= 0:
        return {
            "good_pct": 0.0,
            "moderate_pct": 0.0,
            "weak_pct": 0.0,
            "gap_pct": 0.0,
            "unmeasured_pct": 0.0,
        }
    return {
        "good_pct": round((result.get("good_count", 0) / total) * 100.0, 1),
        "moderate_pct": round((result.get("moderate_count", 0) / total) * 100.0, 1),
        "weak_pct": round((result.get("weak_count", 0) / total) * 100.0, 1),
        "gap_pct": round((result.get("gap_count", 0) / total) * 100.0, 1),
        "unmeasured_pct": round((result.get("unmeasured_count", 0) / total) * 100.0, 1),
    }


def package_analysis_snapshot(
    analysis_result: Dict,
    deployed_nodes: List[Dict],
    affected_area: Optional[List[Dict]] = None,
) -> Dict:
    """
    Phase 6 Requirement 2 & 7: Package an immutable snapshot of an RF survey.
    Preserves:
      - survey sample count
      - active node count
      - node positions
      - coverage counts
      - coverage percentages
      - gap count
      - gap percentage
      - gap clusters
      - gap points
      - candidates
      - heatmap data
      - affected area polygon
    """
    percentages = calculate_coverage_percentages(analysis_result)
    node_positions = [
        {
            "id": str(n.get("id", "")),
            "lat": float(n.get("lat", 0.0)),
            "lon": float(n.get("lon", 0.0)),
        }
        for n in deployed_nodes
    ]
    total_samples = analysis_result.get("survey_samples", 0)
    gap_count = analysis_result.get("gap_count", 0)
    gap_pct = percentages["gap_pct"]

    return {
        "survey_sample_count": total_samples,
        "survey_samples": total_samples,
        "active_node_count": len(deployed_nodes),
        "node_positions": node_positions,
        "coverage_counts": {
            "good": analysis_result.get("good_count", 0),
            "moderate": analysis_result.get("moderate_count", 0),
            "weak": analysis_result.get("weak_count", 0),
            "gap": gap_count,
            "unmeasured": analysis_result.get("unmeasured_count", 0),
        },
        "coverage_percentages": percentages,
        "gap_count": gap_count,
        "gap_percentage": gap_pct,
        "gap_cluster_count": analysis_result.get("gap_cluster_count", 0),
        "gap_points": list(analysis_result.get("gap_points", [])),
        "candidates": list(analysis_result.get("candidates", [])),
        "heatmap": list(analysis_result.get("heatmap", [])),
        "samples": list(analysis_result.get("heatmap", [])),
        "affected_area": [dict(p) for p in affected_area] if affected_area else None,
    }


def are_polygons_equivalent(
    poly1: Optional[List[Dict]],
    poly2: Optional[List[Dict]],
    tol: float = 1e-4,
) -> bool:
    """Requirement 9: Verify that two affected areas are identical within tolerance."""
    if poly1 is None and poly2 is None:
        return True
    if poly1 is None or poly2 is None:
        return False
    if len(poly1) != len(poly2):
        return False
    for p1, p2 in zip(poly1, poly2):
        lat1 = p1.get("lat") or p1.get("latitude", 0.0)
        lon1 = p1.get("lon") or p1.get("longitude", 0.0)
        lat2 = p2.get("lat") or p2.get("latitude", 0.0)
        lon2 = p2.get("lon") or p2.get("longitude", 0.0)
        if abs(lat1 - lat2) > tol or abs(lon1 - lon2) > tol:
            return False
    return True


def compare_before_after(before_data: Optional[Dict], after_data: Optional[Dict]) -> Dict:
    """
    Phase 6 Requirement 8 & 9: Compute objective before-vs-after comparison.
    Never hardcodes improvement values — calculates exact differences.
    """
    if not before_data or not after_data:
        return {
            "comparable": False,
            "invalidation_reason": "Both BEFORE and AFTER survey datasets are required for comparison.",
            "before": before_data,
            "after": after_data,
            "changes": {},
            "remaining_gaps": None,
            "remaining_gap_clusters": None,
        }

    # Requirement 9: Comparability check on affected area
    if not are_polygons_equivalent(before_data.get("affected_area"), after_data.get("affected_area")):
        return {
            "comparable": False,
            "invalidation_reason": "Affected area changed between BEFORE and AFTER surveys. Comparison is invalid.",
            "before": before_data,
            "after": after_data,
            "changes": {},
            "remaining_gaps": after_data.get("gap_count"),
            "remaining_gap_clusters": after_data.get("gap_cluster_count"),
        }

    before_counts = before_data.get("coverage_counts", {})
    after_counts  = after_data.get("coverage_counts", {})
    before_pcts   = before_data.get("coverage_percentages", {})
    after_pcts    = after_data.get("coverage_percentages", {})

    b_nodes = before_data.get("active_node_count", 0)
    a_nodes = after_data.get("active_node_count", 0)

    b_gaps = before_data.get("gap_count", 0)
    a_gaps = after_data.get("gap_count", 0)

    b_clusters = before_data.get("gap_cluster_count", 0)
    a_clusters = after_data.get("gap_cluster_count", 0)

    changes = {
        "node_count_change": a_nodes - b_nodes,
        "good_change_percentage_points": round(after_pcts.get("good_pct", 0.0) - before_pcts.get("good_pct", 0.0), 1),
        "moderate_change_percentage_points": round(after_pcts.get("moderate_pct", 0.0) - before_pcts.get("moderate_pct", 0.0), 1),
        "weak_change_percentage_points": round(after_pcts.get("weak_pct", 0.0) - before_pcts.get("weak_pct", 0.0), 1),
        "gap_change_percentage_points": round(after_pcts.get("gap_pct", 0.0) - before_pcts.get("gap_pct", 0.0), 1),
        "gap_point_change": a_gaps - b_gaps,
        "gap_cluster_change": a_clusters - b_clusters,
    }

    return {
        "comparable": True,
        "invalidation_reason": None,
        "before": {
            "survey_samples": before_data.get("survey_sample_count", 0),
            "active_node_count": b_nodes,
            "coverage_counts": before_counts,
            "coverage_percentages": before_pcts,
            "gap_count": b_gaps,
            "gap_cluster_count": b_clusters,
            "node_positions": before_data.get("node_positions", []),
        },
        "after": {
            "survey_samples": after_data.get("survey_sample_count", 0),
            "active_node_count": a_nodes,
            "coverage_counts": after_counts,
            "coverage_percentages": after_pcts,
            "gap_count": a_gaps,
            "gap_cluster_count": a_clusters,
            "node_positions": after_data.get("node_positions", []),
        },
        "changes": changes,
        "remaining_gaps": a_gaps,
        "remaining_gap_clusters": a_clusters,
    }
