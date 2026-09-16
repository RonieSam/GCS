"""
Phase 9A — Coordinate transformation between GCS planning space and
PX4/Gazebo simulation geographic space.

PROBLEM
-------
The GCS map operates in one geographic region (e.g. Chennai, India) while
PX4/Gazebo SITL operates in another (e.g. Zurich default, or Baylands).
If raw GCS WGS84 coordinates are sent to PX4 as mission targets, PX4 will
attempt to fly to a location thousands of kilometres away.

SOLUTION
--------
A local tangent-plane (ENU — East-North-Up) approximation is used to
express every GCS target as a *relative displacement* from the GCS
reference origin, and then that same displacement is re-applied around
the PX4/Gazebo reference origin.

    GCS target lat/lon
        ↓  gcs_to_displacement()
    (north_m, east_m)  — metres from GCS reference
        ↓  displacement_to_px4()
    PX4 target lat/lon  — same offset from PX4/Gazebo home

The inverse path (PX4 telemetry → GCS display coordinates) is provided by
px4_to_gcs().

APPROXIMATION
-------------
The local tangent-plane approximation is valid to sub-metre accuracy for
distances up to a few tens of kilometres from the reference point, which
far exceeds any realistic UAV mission radius.

    north_m ≈ (lat - lat₀) × 111_320
    east_m  ≈ (lon - lon₀) × 111_320 × cos(lat₀_rad)

    inverse:
    lat = lat₀ + north_m / 111_320
    lon = lon₀ + east_m  / (111_320 × cos(lat₀_rad))

SIMULATION_MODE FLAG
--------------------
When config.SIMULATION_MODE is False, gcs_to_px4() and px4_to_gcs() are
identity functions so the module imposes zero overhead on real-hardware
flights.  Setting SIMULATION_MODE = False in config.py is the *only* change
needed to switch from simulation to production mode.

THREAD SAFETY
-------------
update_px4_reference() is called from the MAVLinkManager background thread.
The mapper uses a threading.Lock to protect the mutable PX4 reference
coordinates so reads from the asyncio event loop (telemetry broadcast) are
always consistent.
"""

import math
import threading
from typing import Tuple

import config


# Metres per degree of latitude — constant to better than 0.1% globally.
_METRES_PER_DEG_LAT = 111_320.0


class CoordinateMapper:
    """Bidirectional coordinate mapper between GCS and PX4/Gazebo spaces.

    Args:
        gcs_ref_lat: GCS map reference latitude (°N).
        gcs_ref_lon: GCS map reference longitude (°E).
        px4_ref_lat: PX4/Gazebo home latitude (°N)  [static fallback].
        px4_ref_lon: PX4/Gazebo home longitude (°E) [static fallback].
    """

    def __init__(
        self,
        gcs_ref_lat: float,
        gcs_ref_lon: float,
        px4_ref_lat: float,
        px4_ref_lon: float,
    ) -> None:
        self._gcs_ref_lat = gcs_ref_lat
        self._gcs_ref_lon = gcs_ref_lon

        # PX4 reference is mutable — overwritten when HOME_POSITION arrives.
        self._lock = threading.Lock()
        self._px4_ref_lat = px4_ref_lat
        self._px4_ref_lon = px4_ref_lon

        # Cached scale factors.  Recomputed whenever references change.
        self._gcs_cos_lat = math.cos(math.radians(gcs_ref_lat))
        self._px4_cos_lat = math.cos(math.radians(px4_ref_lat))

    # ------------------------------------------------------------------
    # Dynamic reference update (called from MAVLinkManager background thread)
    # ------------------------------------------------------------------

    def update_px4_reference(self, lat: float, lon: float) -> None:
        """Override the PX4 reference with the vehicle's actual home position.

        Safe to call from any thread.  Subsequent gcs_to_px4() and
        px4_to_gcs() calls will immediately use the new reference.
        """
        with self._lock:
            self._px4_ref_lat = lat
            self._px4_ref_lon = lon
            self._px4_cos_lat = math.cos(math.radians(lat))

    # ------------------------------------------------------------------
    # GCS → displacement
    # ------------------------------------------------------------------

    def gcs_to_displacement(self, lat: float, lon: float) -> Tuple[float, float]:
        """Convert a GCS WGS84 coordinate to a local ENU displacement.

        The displacement is measured from the GCS reference origin
        (config.GCS_REFERENCE_LAT, config.GCS_REFERENCE_LON).

        Args:
            lat: Target latitude in decimal degrees.
            lon: Target longitude in decimal degrees.

        Returns:
            (north_m, east_m): Displacement in metres.
        """
        north_m = (lat - self._gcs_ref_lat) * _METRES_PER_DEG_LAT
        east_m  = (lon - self._gcs_ref_lon) * _METRES_PER_DEG_LAT * self._gcs_cos_lat
        return north_m, east_m

    # ------------------------------------------------------------------
    # Displacement → PX4
    # ------------------------------------------------------------------

    def displacement_to_px4(self, north_m: float, east_m: float) -> Tuple[float, float]:
        """Convert a local ENU displacement to a PX4/Gazebo WGS84 coordinate.

        The displacement is applied around the current PX4 reference origin.

        Args:
            north_m: Northward offset in metres.
            east_m:  Eastward offset in metres.

        Returns:
            (px4_lat, px4_lon): Target coordinates in PX4/Gazebo space.
        """
        with self._lock:
            ref_lat = self._px4_ref_lat
            cos_lat = self._px4_cos_lat
            ref_lon = self._px4_ref_lon

        px4_lat = ref_lat + north_m / _METRES_PER_DEG_LAT
        px4_lon = ref_lon + east_m  / (_METRES_PER_DEG_LAT * cos_lat)
        return px4_lat, px4_lon

    # ------------------------------------------------------------------
    # Compound transforms
    # ------------------------------------------------------------------

    def gcs_to_px4(self, lat: float, lon: float) -> Tuple[float, float]:
        """Transform a GCS WGS84 coordinate into PX4/Gazebo WGS84.

        When config.SIMULATION_MODE is False this is an identity function.

        Args:
            lat: GCS latitude in decimal degrees.
            lon: GCS longitude in decimal degrees.

        Returns:
            (px4_lat, px4_lon): Translated coordinate for the PX4 mission.
        """
        if not config.SIMULATION_MODE:
            return lat, lon

        north_m, east_m = self.gcs_to_displacement(lat, lon)
        return self.displacement_to_px4(north_m, east_m)

    def px4_to_gcs(self, px4_lat: float, px4_lon: float) -> Tuple[float, float]:
        """Transform a PX4/Gazebo WGS84 coordinate back into GCS coordinates.

        Used to display live telemetry on the GCS map.
        When config.SIMULATION_MODE is False this is an identity function.

        Args:
            px4_lat: PX4 latitude in decimal degrees.
            px4_lon: PX4 longitude in decimal degrees.

        Returns:
            (gcs_lat, gcs_lon): Coordinate for display on the GCS map.
        """
        if not config.SIMULATION_MODE:
            return px4_lat, px4_lon

        # 1. Express PX4 position as displacement from the PX4 reference.
        with self._lock:
            ref_lat = self._px4_ref_lat
            cos_lat = self._px4_cos_lat
            ref_lon = self._px4_ref_lon

        north_m = (px4_lat - ref_lat) * _METRES_PER_DEG_LAT
        east_m  = (px4_lon - ref_lon) * _METRES_PER_DEG_LAT * cos_lat

        # 2. Apply that same displacement around the GCS reference.
        gcs_lat = self._gcs_ref_lat + north_m / _METRES_PER_DEG_LAT
        gcs_lon = (
            self._gcs_ref_lon
            + east_m / (_METRES_PER_DEG_LAT * self._gcs_cos_lat)
        )
        return gcs_lat, gcs_lon

    # ------------------------------------------------------------------
    # Introspection (for the /api/coordinates/reference endpoint)
    # ------------------------------------------------------------------

    def get_references(self) -> dict:
        """Return a snapshot of both reference coordinates."""
        with self._lock:
            px4_lat = self._px4_ref_lat
            px4_lon = self._px4_ref_lon
        return {
            "gcs_reference": {
                "latitude": self._gcs_ref_lat,
                "longitude": self._gcs_ref_lon,
            },
            "px4_reference": {
                "latitude": px4_lat,
                "longitude": px4_lon,
            },
        }


# ---------------------------------------------------------------------------
# Module-level singleton — built once from config at import time.
# update_px4_reference() can be called on it at any time to refine the PX4
# reference from a live HOME_POSITION message without re-constructing.
# ---------------------------------------------------------------------------

_mapper: CoordinateMapper | None = None
_mapper_lock = threading.Lock()


def get_mapper() -> CoordinateMapper:
    """Return the module-level CoordinateMapper singleton.

    Thread-safe.  The singleton is constructed lazily on first call so
    that tests can import this module before config values are available.
    """
    global _mapper
    if _mapper is None:
        with _mapper_lock:
            if _mapper is None:
                _mapper = CoordinateMapper(
                    gcs_ref_lat=config.GCS_REFERENCE_LAT,
                    gcs_ref_lon=config.GCS_REFERENCE_LON,
                    px4_ref_lat=config.PX4_REFERENCE_LAT,
                    px4_ref_lon=config.PX4_REFERENCE_LON,
                )
    return _mapper
