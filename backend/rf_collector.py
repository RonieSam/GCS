"""
Phase 3 — RF Survey Data Collector & State Manager.

Collects UAV GPS telemetry and calculates RSSI for all deployed communication nodes
during an active RF Scan.

Scan States:
    IDLE           - No survey active; no samples accumulated.
    SCAN_READY     - RF scan generated & uploaded; ready to execute.
    SCANNING       - Actively flying survey path; accumulating GPS + RSSI samples.
    RETURNING      - Survey path finished; UAV flying back to original start position.
    SCAN_COMPLETE  - UAV returned and landed at original scan start coordinates.
    FAILED         - Scan aborted or failed.

Survey Samples Format:
    {
        "sample_id": int,
        "timestamp": float,
        "latitude": float,        # GCS / planning space
        "longitude": float,       # GCS / planning space
        "altitude": float,        # metres
        "px4_latitude": float,    # raw PX4 space
        "px4_longitude": float,   # raw PX4 space
        "rssi": {
            "COMM-001": -68.4,
            "COMM-002": -81.2,
            ...
        },
        "best_rssi": float,
        "current_waypoint": int
    }
"""

import copy
import logging
import math
import threading
import time
from typing import Dict, List, Optional, Tuple

import config
import coordinate_mapper
from rf_model import calculate_node_rssi_vector

logger = logging.getLogger("rf_collector")

# Scan states
SCAN_STATE_IDLE = "IDLE"
SCAN_STATE_READY = "SCAN_READY"
SCAN_STATE_SCANNING = "SCANNING"
SCAN_STATE_RETURNING = "RETURNING"
SCAN_STATE_COMPLETE = "SCAN_COMPLETE"
SCAN_STATE_FAILED = "FAILED"


class RFSurveyCollector:
    """Thread-safe collector for RF survey samples during an active RF scan."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = SCAN_STATE_IDLE
        self._samples: List[Dict] = []
        self._scan_start_position: Optional[Dict] = None  # {lat, lon, alt, px4_lat, px4_lon}
        self._affected_area: Optional[List[Dict]] = None
        self._deployed_nodes: List[Dict] = []
        self._survey_waypoint_count: int = 0
        self._total_mission_items: int = 0
        self._last_sample_time: float = 0.0
        self._min_sample_interval_s: float = 0.25  # up to 4 Hz collection
        self._last_uav_pos: Optional[Tuple[float, float]] = None
        self._subscribers = set()  # optional callbacks / websocket queues

    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def get_state(self) -> str:
        with self._lock:
            return self._state

    def set_state(self, new_state: str) -> None:
        with self._lock:
            old = self._state
            self._state = new_state
            logger.info(f"RF Collector state transition: {old} -> {new_state}")

    def prepare_scan(
        self,
        start_position: Dict,
        affected_area: Optional[List[Dict]],
        deployed_nodes: List[Dict],
        survey_waypoint_count: int,
        total_mission_items: int,
    ) -> None:
        """Called when RF scan is generated/uploaded and ready."""
        with self._lock:
            self._samples.clear()
            self._scan_start_position = dict(start_position)
            self._affected_area = list(affected_area) if affected_area else None
            self._deployed_nodes = [dict(n) for n in deployed_nodes]
            self._survey_waypoint_count = survey_waypoint_count
            self._total_mission_items = total_mission_items
            self._state = SCAN_STATE_READY
            self._last_sample_time = 0.0
            self._last_uav_pos = None
            logger.info(
                f"RF Collector prepared: start_pos={start_position}, "
                f"nodes={len(deployed_nodes)}, survey_wps={survey_waypoint_count}"
            )

    def update_deployed_nodes(self, deployed_nodes: List[Dict]) -> None:
        """Dynamically update active deployed nodes list.
        
        Synchronizes the collector node set with the database single source of truth.
        Prunes any stale deleted-node RSSI keys from existing accumulated samples.
        """
        with self._lock:
            self._deployed_nodes = [dict(n) for n in deployed_nodes]
            active_ids = {n.get("id") for n in self._deployed_nodes}

            # Invalidate/prune stale deleted nodes from existing survey samples
            for sample in self._samples:
                if "rssi" in sample and isinstance(sample["rssi"], dict):
                    pruned = {k: v for k, v in sample["rssi"].items() if k in active_ids}
                    sample["rssi"] = pruned
                    sample["best_rssi"] = round(max(pruned.values()), 2) if pruned else None

            logger.info(
                f"RF Collector deployed nodes updated: {len(self._deployed_nodes)} nodes. "
                f"Active node IDs: {active_ids}"
            )

    def start_scan(self) -> None:
        """Called when mission execution begins."""
        with self._lock:
            self._state = SCAN_STATE_SCANNING
            self._last_sample_time = 0.0
            logger.info("RF Collector: SCANNING started.")

    def finish_survey_segment(self) -> None:
        """Called when the final survey waypoint is reached.
        In Phase 4, scan completes directly without return-to-start leg.
        """
        self.complete_scan()

    def complete_scan(self) -> None:
        """Called when UAV completes the final survey waypoint."""
        with self._lock:
            self._state = SCAN_STATE_COMPLETE
            logger.info(
                f"RF Collector: SCAN_COMPLETE with {len(self._samples)} total survey samples."
            )

    def fail_scan(self, reason: str = "") -> None:
        with self._lock:
            self._state = SCAN_STATE_FAILED
            logger.warning(f"RF Collector: FAILED ({reason})")

    def reset(self) -> None:
        with self._lock:
            self._state = SCAN_STATE_IDLE
            self._samples.clear()
            self._scan_start_position = None
            logger.info("RF Collector reset to IDLE.")

    # ------------------------------------------------------------------
    # Telemetry ingestion & RSSI computation
    # ------------------------------------------------------------------

    def ingest_telemetry(self, vehicle_state: Dict) -> Optional[Dict]:
        """Ingest live vehicle telemetry.

        If in SCANNING state, computes RSSI for all currently deployed nodes and stores a sample.
        When the final survey waypoint is reached, transitions directly to SCAN_COMPLETE
        and stops RSSI collection.
        """
        with self._lock:
            current_state = self._state
            survey_wps = self._survey_waypoint_count

        m_reached = vehicle_state.get("mission_item_reached")
        m_current = vehicle_state.get("mission_current")

        # Check for survey completion:
        # Survey waypoints occupy items 1 .. survey_wps.
        # Once item survey_wps is reached, survey is complete.
        if current_state == SCAN_STATE_SCANNING and survey_wps > 0:
            if (m_reached is not None and m_reached >= survey_wps) or \
               (m_current is not None and m_current > survey_wps):
                self.complete_scan()
                current_state = SCAN_STATE_COMPLETE

        # ONLY accumulate survey samples while in SCANNING state.
        # Do not accumulate when IDLE, SCAN_READY, SCAN_COMPLETE, or FAILED.
        if current_state != SCAN_STATE_SCANNING:
            return None

        raw_lat = vehicle_state.get("latitude")
        raw_lon = vehicle_state.get("longitude")
        alt = vehicle_state.get("altitude", 0.0)

        if raw_lat is None or raw_lon is None:
            return None

        now = time.time()
        with self._lock:
            if now - self._last_sample_time < self._min_sample_interval_s:
                return None
            self._last_sample_time = now
            nodes = list(self._deployed_nodes)

        # Coordinate resolution: ensure coordinates are correctly in GCS space
        # without double-conversion regardless of whether raw PX4 or remapped GCS
        # coordinates are supplied in vehicle_state.
        mapper = coordinate_mapper.get_mapper()
        raw_lat_f = float(raw_lat)
        raw_lon_f = float(raw_lon)

        if not config.SIMULATION_MODE:
            gcs_lat, gcs_lon = raw_lat_f, raw_lon_f
            px4_lat, px4_lon = raw_lat_f, raw_lon_f
        else:
            refs = mapper.get_references()
            px4_ref = refs.get("px4_reference", {})
            gcs_ref = refs.get("gcs_reference", {})
            p_lat = px4_ref.get("latitude", config.PX4_REFERENCE_LAT)
            p_lon = px4_ref.get("longitude", config.PX4_REFERENCE_LON)
            g_lat = gcs_ref.get("latitude", config.GCS_REFERENCE_LAT)
            g_lon = gcs_ref.get("longitude", config.GCS_REFERENCE_LON)

            dist_to_gcs = math.hypot(raw_lat_f - g_lat, raw_lon_f - g_lon)
            dist_to_px4 = math.hypot(raw_lat_f - p_lat, raw_lon_f - p_lon)

            if dist_to_gcs < dist_to_px4:
                # Already in GCS coordinate space
                gcs_lat, gcs_lon = raw_lat_f, raw_lon_f
                px4_lat, px4_lon = mapper.gcs_to_px4(gcs_lat, gcs_lon)
            else:
                # In PX4 simulation coordinate space
                px4_lat, px4_lon = raw_lat_f, raw_lon_f
                gcs_lat, gcs_lon = mapper.px4_to_gcs(px4_lat, px4_lon)

        # Calculate simulated RSSI for each currently deployed communication node
        # Uses strictly horizontal distance without altitude contamination
        rssi_dict = calculate_node_rssi_vector(
            uav_lat=gcs_lat,
            uav_lon=gcs_lon,
            uav_alt_m=alt,
            deployed_nodes=nodes,
        )

        best_rssi = round(max(rssi_dict.values()), 2) if rssi_dict else None

        sample = {
            "sample_id": 0,  # assigned below under lock
            "timestamp": round(now, 3),
            "latitude": round(gcs_lat, 7),
            "longitude": round(gcs_lon, 7),
            "altitude": round(alt, 2),
            "px4_latitude": round(px4_lat, 7),
            "px4_longitude": round(px4_lon, 7),
            "rssi": rssi_dict,
            "best_rssi": best_rssi,
            "current_waypoint": m_current if m_current is not None else 0,
        }

        with self._lock:
            sample["sample_id"] = len(self._samples) + 1
            self._samples.append(sample)

        # Notify any streaming listeners / queues
        self._notify_subscribers(sample)
        return sample

    # ------------------------------------------------------------------
    # Data Retrieval
    # ------------------------------------------------------------------

    def get_survey_data(self) -> Dict:
        """Return the complete accumulated survey dataset and metadata."""
        with self._lock:
            samples_copy = [dict(s) for s in self._samples]
            nodes_copy = [dict(n) for n in self._deployed_nodes]
            area_copy = [dict(p) for p in self._affected_area] if self._affected_area else None
            start_pos_copy = dict(self._scan_start_position) if self._scan_start_position else None
            state_copy = self._state

        return {
            "state": state_copy,
            "sample_count": len(samples_copy),
            "scan_start_position": start_pos_copy,
            "affected_area": area_copy,
            "deployed_nodes": nodes_copy,
            "samples": samples_copy,
        }

    def get_scan_start_position(self) -> Optional[Dict]:
        with self._lock:
            return dict(self._scan_start_position) if self._scan_start_position else None

    # ------------------------------------------------------------------
    # Subscribers (for real-time streaming)
    # ------------------------------------------------------------------

    def subscribe(self, callback):
        with self._lock:
            self._subscribers.add(callback)

    def unsubscribe(self, callback):
        with self._lock:
            self._subscribers.discard(callback)

    def _notify_subscribers(self, sample: Dict):
        for cb in list(self._subscribers):
            try:
                cb(sample)
            except Exception as e:
                logger.error(f"Error in RF survey subscriber callback: {e}")


# Global singleton instance
_collector_instance: Optional[RFSurveyCollector] = None


def get_rf_collector() -> RFSurveyCollector:
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = RFSurveyCollector()
    return _collector_instance
