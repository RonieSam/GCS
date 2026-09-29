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
from typing import Any, Dict, List, Optional, Tuple, Union

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
            "lat": lat,
            "lon": lon,
            "latitude": lat,
            "longitude": lon,
            "rssi": round(best_rssi, 2) if best_rssi is not None else None,
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
                "lat": lat,
                "lon": lon,
                "latitude": lat,
                "longitude": lon,
                "rssi": round(best_rssi, 2) if best_rssi is not None else None,
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

    cov_stats = calculate_coverage_statistics(heatmap_points, active_node_ids=active_node_ids)
    coverage_counts = cov_stats["coverage_counts"]
    cov_percentages = cov_stats["coverage_percentages"]

    return {
        "survey_samples": len(heatmap_points),
        "good_count": cov_stats["good_count"],
        "moderate_count": cov_stats["moderate_count"],
        "weak_count": cov_stats["weak_count"],
        "gap_count": cov_stats["gap_count"],
        "unmeasured_count": cov_stats["unmeasured_count"],
        "coverage_counts": coverage_counts,
        "coverage_percentages": cov_percentages,
        "good_percentage": cov_percentages["good_percentage"],
        "moderate_percentage": cov_percentages["moderate_percentage"],
        "weak_percentage": cov_percentages["weak_percentage"],
        "gap_percentage": cov_percentages["gap_percentage"],
        "good_pct": cov_percentages["good_pct"],
        "moderate_pct": cov_percentages["moderate_pct"],
        "weak_pct": cov_percentages["weak_pct"],
        "gap_pct": cov_percentages["gap_pct"],
        "gap_cluster_count": len(clusters),
        "gap_cluster_distance_m": round(gap_cluster_distance_m, 1),
        "rf_range_scale": rf_range_scale,
        "heatmap": heatmap_points,
        "samples": heatmap_points,  # Requirement 7 alias
        "gap_points": gap_point_list,
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Phase 6 — Re-Scan & Authoritative Coverage Statistics
# ---------------------------------------------------------------------------


def extract_actual_sample_rssi(
    sample: Dict,
    active_node_ids: Optional[set] = None,
) -> Optional[float]:
    """Extract authoritative numeric RSSI value from a survey sample.

    Supports:
      1. sample["best_rssi"] (precomputed best RSSI)
      2. sample["rssi"] as dict {node_id: rssi_val} (using active nodes if provided, or best across all nodes)
      3. sample["rssi"] as numeric float/int
      4. sample["rssis"] as dict or list
    Returns float or None.
    """
    if not isinstance(sample, dict):
        return None

    # 1. Direct best_rssi
    best_val = sample.get("best_rssi")
    if best_val is not None:
        try:
            v = float(best_val)
            if math.isfinite(v):
                return v
        except (TypeError, ValueError):
            pass

    # 2. rssi field
    rssi_field = sample.get("rssi")
    if isinstance(rssi_field, dict) and rssi_field:
        best_dict = compute_best_rssi(rssi_field, active_node_ids)
        if best_dict is not None and math.isfinite(best_dict):
            return best_dict
        if active_node_ids is not None:
            fallback = compute_best_rssi(rssi_field, None)
            if fallback is not None and math.isfinite(fallback):
                return fallback
    elif isinstance(rssi_field, (int, float)):
        try:
            v = float(rssi_field)
            if math.isfinite(v):
                return v
        except (TypeError, ValueError):
            pass

    # 3. rssis field
    rssis_field = sample.get("rssis")
    if isinstance(rssis_field, dict) and rssis_field:
        best_rssis = compute_best_rssi(rssis_field, active_node_ids)
        if best_rssis is not None and math.isfinite(best_rssis):
            return best_rssis
        if active_node_ids is not None:
            fallback = compute_best_rssi(rssis_field, None)
            if fallback is not None and math.isfinite(fallback):
                return fallback
    elif isinstance(rssis_field, list) and rssis_field:
        valid = []
        for x in rssis_field:
            try:
                vx = float(x)
                if math.isfinite(vx):
                    valid.append(vx)
            except (TypeError, ValueError):
                pass
        if valid:
            return max(valid)

    return None


def calculate_coverage_statistics(
    samples_or_result: Any,
    active_node_ids: Optional[set] = None,
    affected_area: Optional[List[Dict]] = None,
) -> Dict:
    """Authoritative single source of truth for coverage counts and percentages.

    Derived directly from real survey samples using the exact RF thresholds:
        GOOD:       RSSI > -60 dBm
        MODERATE:   -75 < RSSI <= -60 dBm
        WEAK:       -85 < RSSI <= -75 dBm
        GAP:        RSSI <= -85 dBm
        UNMEASURED: No valid RSSI measurement.

    Percentage denominator is MEASURED samples:
        measured = good + moderate + weak + gap
    If measured > 0:
        good_percentage     = round(good / measured * 100, 1)
        moderate_percentage = round(moderate / measured * 100, 1)
        weak_percentage     = round(weak / measured * 100, 1)
        gap_percentage      = round(gap / measured * 100, 1)
    Else:
        all four percentages = 0.0

    UNMEASURED is tracked and reported separately.
    """
    if isinstance(samples_or_result, dict):
        has_counts = any(
            int(samples_or_result.get(k, 0) or 0) > 0
            for k in ("good_count", "moderate_count", "weak_count", "gap_count", "good", "moderate", "weak", "gap")
        )
        samples = samples_or_result.get("samples") or samples_or_result.get("heatmap")
        if has_counts and (not samples or len(samples) < samples_or_result.get("survey_samples", 0)):
            good = int(samples_or_result.get("good_count", samples_or_result.get("good", 0)))
            moderate = int(samples_or_result.get("moderate_count", samples_or_result.get("moderate", 0)))
            weak = int(samples_or_result.get("weak_count", samples_or_result.get("weak", 0)))
            gap = int(samples_or_result.get("gap_count", samples_or_result.get("gap", 0)))
            unmeasured = int(samples_or_result.get("unmeasured_count", samples_or_result.get("unmeasured", 0)))
            measured = good + moderate + weak + gap
            total = samples_or_result.get("total_samples", samples_or_result.get("survey_samples", measured + unmeasured))
            if measured > 0:
                good_pct = round((good / measured) * 100.0, 1)
                mod_pct = round((moderate / measured) * 100.0, 1)
                weak_pct = round((weak / measured) * 100.0, 1)
                gap_pct = round((gap / measured) * 100.0, 1)
            else:
                good_pct = mod_pct = weak_pct = gap_pct = 0.0
            unmeasured_pct = round((unmeasured / total) * 100.0, 1) if total > 0 else 0.0
            cov_counts = {"good": good, "moderate": moderate, "weak": weak, "gap": gap, "unmeasured": unmeasured}
            cov_pcts = {
                "good_percentage": good_pct, "moderate_percentage": mod_pct,
                "weak_percentage": weak_pct, "gap_percentage": gap_pct,
                "good_pct": good_pct, "moderate_pct": mod_pct,
                "weak_pct": weak_pct, "gap_pct": gap_pct,
                "unmeasured_pct": unmeasured_pct,
                "measured_count": measured, "unmeasured_count": unmeasured,
            }
            return {
                "sample_count": total, "total_samples": total,
                "measured_count": measured, "unmeasured_count": unmeasured,
                "good_count": good, "moderate_count": moderate, "weak_count": weak, "gap_count": gap,
                "coverage_counts": cov_counts, "coverage_percentages": cov_pcts,
                "good_percentage": good_pct, "moderate_percentage": mod_pct,
                "weak_percentage": weak_pct, "gap_percentage": gap_pct,
                "good_pct": good_pct, "moderate_pct": mod_pct,
                "weak_pct": weak_pct, "gap_pct": gap_pct,
                "unmeasured_pct": unmeasured_pct,
            }
        if samples is None:
            samples = []
    elif isinstance(samples_or_result, list):
        samples = samples_or_result
    else:
        samples = []

    good = 0
    moderate = 0
    weak = 0
    gap = 0
    unmeasured = 0

    has_polygon = affected_area is not None and len(affected_area) >= 3

    for s in samples:
        if not isinstance(s, dict):
            continue

        lat = s.get("latitude") if s.get("latitude") is not None else s.get("lat")
        lon = s.get("longitude") if s.get("longitude") is not None else s.get("lon")

        # Constrain to affected area if defined
        if has_polygon and lat is not None and lon is not None:
            if not point_in_polygon(lat, lon, affected_area):
                continue

        rssi = extract_actual_sample_rssi(s, active_node_ids)
        if rssi is not None:
            if rssi > GOOD_THRESHOLD:
                good += 1
            elif rssi > MODERATE_THRESHOLD:
                moderate += 1
            elif rssi > WEAK_THRESHOLD:
                weak += 1
            else:
                gap += 1
        else:
            status = s.get("status")
            if status == STATUS_GOOD:
                good += 1
            elif status == STATUS_MODERATE:
                moderate += 1
            elif status == STATUS_WEAK:
                weak += 1
            elif status == STATUS_GAP:
                gap += 1
            else:
                unmeasured += 1

    measured = good + moderate + weak + gap
    total = measured + unmeasured

    if measured > 0:
        good_pct = round((good / measured) * 100.0, 1)
        mod_pct = round((moderate / measured) * 100.0, 1)
        weak_pct = round((weak / measured) * 100.0, 1)
        gap_pct = round((gap / measured) * 100.0, 1)
    else:
        good_pct = 0.0
        mod_pct = 0.0
        weak_pct = 0.0
        gap_pct = 0.0

    unmeasured_pct = round((unmeasured / total) * 100.0, 1) if total > 0 else 0.0

    coverage_counts = {
        "good": good,
        "moderate": moderate,
        "weak": weak,
        "gap": gap,
        "unmeasured": unmeasured,
    }

    coverage_percentages = {
        "good_percentage": good_pct,
        "moderate_percentage": mod_pct,
        "weak_percentage": weak_pct,
        "gap_percentage": gap_pct,
        "good_pct": good_pct,
        "moderate_pct": mod_pct,
        "weak_pct": weak_pct,
        "gap_pct": gap_pct,
        "unmeasured_pct": unmeasured_pct,
        "measured_count": measured,
        "unmeasured_count": unmeasured,
    }

    return {
        "sample_count": total,
        "total_samples": total,
        "measured_count": measured,
        "unmeasured_count": unmeasured,
        "good_count": good,
        "moderate_count": moderate,
        "weak_count": weak,
        "gap_count": gap,
        "coverage_counts": coverage_counts,
        "coverage_percentages": coverage_percentages,
        "good_percentage": good_pct,
        "moderate_percentage": mod_pct,
        "weak_percentage": weak_pct,
        "gap_percentage": gap_pct,
        "good_pct": good_pct,
        "moderate_pct": mod_pct,
        "weak_pct": weak_pct,
        "gap_pct": gap_pct,
        "unmeasured_pct": unmeasured_pct,
    }


def calculate_coverage_percentages(result_or_samples: Any) -> Dict:
    """Calculate exact coverage percentages from analysis result or samples list.

    Measured total:
        measured = good + moderate + weak + gap
    Percentages:
        good_percentage     = good / measured * 100
        moderate_percentage = moderate / measured * 100
        weak_percentage     = weak / measured * 100
        gap_percentage      = gap / measured * 100
    If measured == 0: all percentages = 0.0.
    """
    stats = calculate_coverage_statistics(result_or_samples)
    return stats["coverage_percentages"]


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
    gap_pct = percentages.get("gap_percentage", percentages.get("gap_pct", 0.0))

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
        "good_percentage": percentages.get("good_percentage", percentages.get("good_pct", 0.0)),
        "moderate_percentage": percentages.get("moderate_percentage", percentages.get("moderate_pct", 0.0)),
        "weak_percentage": percentages.get("weak_percentage", percentages.get("weak_pct", 0.0)),
        "gap_percentage": gap_pct,
        "good_pct": percentages.get("good_pct", 0.0),
        "moderate_pct": percentages.get("moderate_pct", 0.0),
        "weak_pct": percentages.get("weak_pct", 0.0),
        "gap_pct": gap_pct,
        "gap_count": gap_count,
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
