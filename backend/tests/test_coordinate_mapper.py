"""
Phase 9A unit tests — coordinate_mapper.py

Tests:
  1. Reference point maps to reference point (identity).
  2. 100 m north displacement is preserved across the mapping.
  3. 100 m east  displacement is preserved across the mapping.
  4. Combined north + east displacement is preserved.
  5. GCS → PX4 → GCS round-trip returns the original coordinate.
  6. PX4 → GCS → PX4 round-trip returns the original coordinate.
  7. Large absolute difference between GCS and PX4 does not corrupt
     local displacement (the whole point of the module).
  8. SIMULATION_MODE = False makes gcs_to_px4 / px4_to_gcs identity
     functions.

Tolerance: 1 m for all distance assertions (well within the local
tangent-plane approximation's accuracy for distances < 10 km).

Run from backend/:
    python -m pytest tests/test_coordinate_mapper.py -v
    # or
    python -m unittest tests.test_coordinate_mapper -v
"""

import math
import os
import sys
import unittest
from unittest import mock

# Make sure the parent directory (backend/) is on sys.path so we can
# import coordinate_mapper and config without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    """Approximate surface distance between two WGS84 points (metres)."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _make_mapper(
    gcs_ref_lat=13.0827, gcs_ref_lon=80.2707,
    px4_ref_lat=37.4122, px4_ref_lon=-122.0016,
    simulation_mode=True,
):
    """Build an isolated CoordinateMapper with chosen references.

    Patches config so SIMULATION_MODE matches the requested value without
    touching the real config module permanently.
    """
    # Import inside helper so sys.path is already set up.
    import config
    import coordinate_mapper

    mapper = coordinate_mapper.CoordinateMapper(
        gcs_ref_lat=gcs_ref_lat,
        gcs_ref_lon=gcs_ref_lon,
        px4_ref_lat=px4_ref_lat,
        px4_ref_lon=px4_ref_lon,
    )
    return mapper, simulation_mode


# ---------------------------------------------------------------------------
# Test 1 — reference point → reference point
# ---------------------------------------------------------------------------

class TestReferencePointIdentity(unittest.TestCase):
    """The GCS reference must map exactly to the PX4 reference."""

    def test_gcs_reference_maps_to_px4_reference(self):
        mapper, _ = _make_mapper()
        # GCS reference → PX4
        px4_lat, px4_lon = mapper.gcs_to_px4(13.0827, 80.2707)
        self.assertAlmostEqual(px4_lat, 37.4122, places=6)
        self.assertAlmostEqual(px4_lon, -122.0016, places=6)

    def test_px4_reference_maps_to_gcs_reference(self):
        mapper, _ = _make_mapper()
        # PX4 reference → GCS
        gcs_lat, gcs_lon = mapper.px4_to_gcs(37.4122, -122.0016)
        self.assertAlmostEqual(gcs_lat, 13.0827, places=6)
        self.assertAlmostEqual(gcs_lon, 80.2707, places=6)


# ---------------------------------------------------------------------------
# Test 2 — 100 m north displacement
# ---------------------------------------------------------------------------

class TestNorthDisplacement(unittest.TestCase):

    def setUp(self):
        self.mapper, _ = _make_mapper()
        self.METRES_PER_DEG = 111_320.0
        # GCS point 100 m north of the GCS reference.
        self.gcs_ref_lat = 13.0827
        self.gcs_ref_lon = 80.2707
        self.target_lat = self.gcs_ref_lat + 100.0 / self.METRES_PER_DEG
        self.target_lon = self.gcs_ref_lon   # due north — no east offset

    def test_100m_north_displacement_preserved(self):
        px4_lat, px4_lon = self.mapper.gcs_to_px4(self.target_lat, self.target_lon)
        # PX4 reference is 37.4122, -122.0016
        # The PX4 target should be ≈100 m north of the PX4 reference.
        dist = _haversine_m(37.4122, -122.0016, px4_lat, px4_lon)
        self.assertAlmostEqual(dist, 100.0, delta=1.0,
            msg=f"Expected ~100 m north displacement in PX4 space, got {dist:.2f} m")

    def test_no_east_component_for_pure_north(self):
        north_m, east_m = self.mapper.gcs_to_displacement(self.target_lat, self.target_lon)
        self.assertAlmostEqual(east_m, 0.0, delta=0.1,
            msg="Pure north displacement should have zero east component")
        self.assertAlmostEqual(north_m, 100.0, delta=1.0)


# ---------------------------------------------------------------------------
# Test 3 — 100 m east displacement
# ---------------------------------------------------------------------------

class TestEastDisplacement(unittest.TestCase):

    def setUp(self):
        self.mapper, _ = _make_mapper()
        self.METRES_PER_DEG = 111_320.0
        gcs_ref_lat = 13.0827
        gcs_ref_lon = 80.2707
        cos_lat = math.cos(math.radians(gcs_ref_lat))
        self.target_lat = gcs_ref_lat
        self.target_lon = gcs_ref_lon + 100.0 / (self.METRES_PER_DEG * cos_lat)

    def test_100m_east_displacement_preserved(self):
        px4_lat, px4_lon = self.mapper.gcs_to_px4(self.target_lat, self.target_lon)
        dist = _haversine_m(37.4122, -122.0016, px4_lat, px4_lon)
        self.assertAlmostEqual(dist, 100.0, delta=1.0,
            msg=f"Expected ~100 m east displacement in PX4 space, got {dist:.2f} m")

    def test_no_north_component_for_pure_east(self):
        north_m, east_m = self.mapper.gcs_to_displacement(self.target_lat, self.target_lon)
        self.assertAlmostEqual(north_m, 0.0, delta=0.1,
            msg="Pure east displacement should have zero north component")
        self.assertAlmostEqual(east_m, 100.0, delta=1.0)


# ---------------------------------------------------------------------------
# Test 4 — combined north + east displacement
# ---------------------------------------------------------------------------

class TestCombinedDisplacement(unittest.TestCase):

    def setUp(self):
        self.mapper, _ = _make_mapper()
        MPD = 111_320.0
        gcs_ref_lat = 13.0827
        gcs_ref_lon = 80.2707
        cos_lat = math.cos(math.radians(gcs_ref_lat))
        # 200 m north, 150 m east
        self.target_lat = gcs_ref_lat + 200.0 / MPD
        self.target_lon = gcs_ref_lon + 150.0 / (MPD * cos_lat)
        self.expected_dist = math.sqrt(200.0 ** 2 + 150.0 ** 2)  # 250 m

    def test_combined_displacement_magnitude_preserved(self):
        px4_lat, px4_lon = self.mapper.gcs_to_px4(self.target_lat, self.target_lon)
        dist = _haversine_m(37.4122, -122.0016, px4_lat, px4_lon)
        self.assertAlmostEqual(dist, self.expected_dist, delta=2.0,
            msg=f"Expected ~{self.expected_dist:.1f} m combined offset, got {dist:.2f} m")


# ---------------------------------------------------------------------------
# Test 5 — GCS → PX4 → GCS round-trip
# ---------------------------------------------------------------------------

class TestGcsToPx4ToGcsRoundtrip(unittest.TestCase):

    def _roundtrip(self, gcs_lat, gcs_lon):
        mapper, _ = _make_mapper()
        px4_lat, px4_lon = mapper.gcs_to_px4(gcs_lat, gcs_lon)
        back_lat, back_lon = mapper.px4_to_gcs(px4_lat, px4_lon)
        return back_lat, back_lon

    def test_roundtrip_at_reference(self):
        back_lat, back_lon = self._roundtrip(13.0827, 80.2707)
        self.assertAlmostEqual(back_lat, 13.0827, places=6)
        self.assertAlmostEqual(back_lon, 80.2707, places=6)

    def test_roundtrip_100m_north(self):
        MPD = 111_320.0
        target_lat = 13.0827 + 100.0 / MPD
        back_lat, back_lon = self._roundtrip(target_lat, 80.2707)
        dist = _haversine_m(target_lat, 80.2707, back_lat, back_lon)
        self.assertAlmostEqual(dist, 0.0, delta=1.0,
            msg=f"GCS→PX4→GCS round-trip error: {dist:.4f} m")

    def test_roundtrip_300m_offset(self):
        MPD = 111_320.0
        cos_lat = math.cos(math.radians(13.0827))
        target_lat = 13.0827 + 300.0 / MPD
        target_lon = 80.2707 + 200.0 / (MPD * cos_lat)
        back_lat, back_lon = self._roundtrip(target_lat, target_lon)
        dist = _haversine_m(target_lat, target_lon, back_lat, back_lon)
        self.assertAlmostEqual(dist, 0.0, delta=1.0,
            msg=f"GCS→PX4→GCS 300 m round-trip error: {dist:.4f} m")


# ---------------------------------------------------------------------------
# Test 6 — PX4 → GCS → PX4 round-trip
# ---------------------------------------------------------------------------

class TestPx4ToGcsToPx4Roundtrip(unittest.TestCase):

    def _roundtrip(self, px4_lat, px4_lon):
        mapper, _ = _make_mapper()
        gcs_lat, gcs_lon = mapper.px4_to_gcs(px4_lat, px4_lon)
        back_lat, back_lon = mapper.gcs_to_px4(gcs_lat, gcs_lon)
        return back_lat, back_lon

    def test_roundtrip_at_px4_reference(self):
        back_lat, back_lon = self._roundtrip(37.4122, -122.0016)
        self.assertAlmostEqual(back_lat, 37.4122, places=6)
        self.assertAlmostEqual(back_lon, -122.0016, places=6)

    def test_roundtrip_500m_offset(self):
        MPD = 111_320.0
        cos_lat = math.cos(math.radians(37.4122))
        target_lat = 37.4122 + 500.0 / MPD
        target_lon = -122.0016 + 300.0 / (MPD * cos_lat)
        back_lat, back_lon = self._roundtrip(target_lat, target_lon)
        dist = _haversine_m(target_lat, target_lon, back_lat, back_lon)
        self.assertAlmostEqual(dist, 0.0, delta=1.0,
            msg=f"PX4→GCS→PX4 round-trip error: {dist:.4f} m")


# ---------------------------------------------------------------------------
# Test 7 — large absolute offset does not corrupt local displacement
# ---------------------------------------------------------------------------

class TestLargeAbsoluteOffsetDoesNotCorruptDisplacement(unittest.TestCase):
    """The GCS and PX4 reference points are thousands of km apart (Chennai
    vs. California).  The mapped displacement must still be sub-metre
    accurate at 500 m mission radius."""

    def test_displacement_accurate_despite_large_absolute_difference(self):
        # GCS reference: Chennai (~80°E).
        # PX4 reference: California (~-122°E).
        # Absolute longitude difference: ~202°.  The mapper must handle this.
        mapper = _make_mapper(
            gcs_ref_lat=13.0827, gcs_ref_lon=80.2707,
            px4_ref_lat=37.4122, px4_ref_lon=-122.0016,
        )[0]

        MPD = 111_320.0
        cos_gcs = math.cos(math.radians(13.0827))
        # Select a GCS point 500 m north + 300 m east of GCS reference.
        gcs_target_lat = 13.0827 + 500.0 / MPD
        gcs_target_lon = 80.2707 + 300.0 / (MPD * cos_gcs)

        px4_lat, px4_lon = mapper.gcs_to_px4(gcs_target_lat, gcs_target_lon)
        dist_from_px4_ref = _haversine_m(37.4122, -122.0016, px4_lat, px4_lon)

        expected = math.sqrt(500.0 ** 2 + 300.0 ** 2)  # ≈ 583 m
        self.assertAlmostEqual(dist_from_px4_ref, expected, delta=2.0,
            msg=(
                f"With a large absolute GCS/PX4 offset, the displacement "
                f"should still be ~{expected:.1f} m, got {dist_from_px4_ref:.2f} m"
            ))


# ---------------------------------------------------------------------------
# Test 8 — SIMULATION_MODE = False → identity transform
# ---------------------------------------------------------------------------

class TestSimulationModeFalseIsIdentity(unittest.TestCase):

    def test_gcs_to_px4_is_identity_when_simulation_mode_false(self):
        import config
        import coordinate_mapper

        mapper = coordinate_mapper.CoordinateMapper(
            gcs_ref_lat=13.0827,
            gcs_ref_lon=80.2707,
            px4_ref_lat=37.4122,
            px4_ref_lon=-122.0016,
        )

        with mock.patch.object(config, "SIMULATION_MODE", False):
            px4_lat, px4_lon = mapper.gcs_to_px4(13.1000, 80.3000)

        self.assertEqual(px4_lat, 13.1000)
        self.assertEqual(px4_lon, 80.3000)

    def test_px4_to_gcs_is_identity_when_simulation_mode_false(self):
        import config
        import coordinate_mapper

        mapper = coordinate_mapper.CoordinateMapper(
            gcs_ref_lat=13.0827,
            gcs_ref_lon=80.2707,
            px4_ref_lat=37.4122,
            px4_ref_lon=-122.0016,
        )

        with mock.patch.object(config, "SIMULATION_MODE", False):
            gcs_lat, gcs_lon = mapper.px4_to_gcs(37.500, -121.900)

        self.assertEqual(gcs_lat, 37.500)
        self.assertEqual(gcs_lon, -121.900)


# ---------------------------------------------------------------------------
# Test 9 — update_px4_reference changes the mapping live
# ---------------------------------------------------------------------------

class TestUpdatePx4Reference(unittest.TestCase):

    def test_update_reference_changes_output(self):
        import coordinate_mapper
        mapper = coordinate_mapper.CoordinateMapper(
            gcs_ref_lat=13.0827,
            gcs_ref_lon=80.2707,
            px4_ref_lat=37.4122,
            px4_ref_lon=-122.0016,
        )
        # Translate the GCS reference — should give PX4 reference before update.
        lat1, lon1 = mapper.gcs_to_px4(13.0827, 80.2707)
        self.assertAlmostEqual(lat1, 37.4122, places=5)
        self.assertAlmostEqual(lon1, -122.0016, places=5)

        # Move the PX4 reference by 1 km north.
        new_px4_lat = 37.4122 + 1000.0 / 111_320.0
        mapper.update_px4_reference(new_px4_lat, -122.0016)

        lat2, lon2 = mapper.gcs_to_px4(13.0827, 80.2707)
        self.assertAlmostEqual(lat2, new_px4_lat, places=5)
        self.assertAlmostEqual(lon2, -122.0016, places=5)


if __name__ == "__main__":
    unittest.main()
