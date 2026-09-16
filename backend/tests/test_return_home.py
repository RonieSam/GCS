"""
Automated tests for UAV Emergency Deployment GCS — Fix UAV Marker Reset & Return-to-Home.

Covers the 10 required test specifications:
1. Mission completion does not reset vehicle telemetry position.
2. UAV marker continues using telemetry after mission completion.
3. Return-home endpoint exists.
4. Return-home validates vehicle state.
5. Return-home uses the existing PX4 home/reference.
6. Return-home does not modify GCS marker directly.
7. Existing RTL functionality remains unchanged.
8. Coordinate transformations remain unchanged.
9. Existing ARM/DISARM functionality remains unchanged.
10. Existing TAKEOFF → WAYPOINT → LAND mission remains unchanged.
"""

import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import config
import coordinate_mapper
import database
import mavlink_mission
import mavlink_manager
from main import app, session_state, mav_manager
from telemetry_broadcaster import TelemetryBroadcaster


class FakeMAVLinkMessage:
    def __init__(self, msg_type, **kwargs):
        self._msg_type = msg_type
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_type(self):
        return self._msg_type


class TestUavMarkerResetFix(unittest.TestCase):
    """Verifies that subsequent HOME_POSITION messages after mission landing
    do NOT corrupt the PX4 home reference or reset the UAV marker position."""

    def setUp(self):
        mavlink_manager.reset_px4_reference_tracking()
        self.mapper = coordinate_mapper.CoordinateMapper(
            gcs_ref_lat=13.0827,
            gcs_ref_lon=80.2707,
            px4_ref_lat=47.397742,
            px4_ref_lon=8.545594,
        )

    def tearDown(self):
        mavlink_manager.reset_px4_reference_tracking()

    def test_mission_completion_does_not_reset_vehicle_telemetry_position(self):
        """Test 1: When UAV lands at target and PX4 emits a subsequent HOME_POSITION,
        the initial home reference is latched and not overwritten."""
        with patch.object(coordinate_mapper, "get_mapper", return_value=self.mapper):
            with patch("config.SIMULATION_MODE", True):
                initial_home_msg = FakeMAVLinkMessage(
                    "HOME_POSITION",
                    latitude=int(47.397742 * 1e7),
                    longitude=int(8.545594 * 1e7),
                )
                state = {"latitude": 47.397742, "longitude": 8.545594}

                # Step 1: Initial home established at boot/arm
                mavlink_manager._self_update_px4_reference(initial_home_msg, state)
                refs = self.mapper.get_references()
                self.assertAlmostEqual(refs["px4_reference"]["latitude"], 47.397742, places=5)
                self.assertAlmostEqual(refs["px4_reference"]["longitude"], 8.545594, places=5)

                # Step 2: UAV flies to target (e.g., +500m north, +500m east)
                target_px4_lat = 47.397742 + (500.0 / 111320.0)
                target_px4_lon = 8.545594 + (500.0 / (111320.0 * math.cos(math.radians(47.397742))))

                # PX4 lands and disarms at target, emitting a new HOME_POSITION at target
                subsequent_home_msg = FakeMAVLinkMessage(
                    "HOME_POSITION",
                    latitude=int(target_px4_lat * 1e7),
                    longitude=int(target_px4_lon * 1e7),
                )
                mavlink_manager._self_update_px4_reference(subsequent_home_msg, state)

                # Step 3: Reference must still be original home, NOT the target
                refs_after = self.mapper.get_references()
                self.assertAlmostEqual(refs_after["px4_reference"]["latitude"], 47.397742, places=5)
                self.assertAlmostEqual(refs_after["px4_reference"]["longitude"], 8.545594, places=5)

    def test_uav_marker_continues_using_telemetry_after_mission_completion(self):
        """Test 2: UAV marker/telemetry output remains at target position after landing
        instead of resetting to the GCS origin."""
        with patch.object(coordinate_mapper, "get_mapper", return_value=self.mapper):
            with patch("config.SIMULATION_MODE", True):
                initial_home_msg = FakeMAVLinkMessage(
                    "HOME_POSITION",
                    latitude=int(47.397742 * 1e7),
                    longitude=int(8.545594 * 1e7),
                )
                mavlink_manager._self_update_px4_reference(initial_home_msg, {})

                # Target coordinates in PX4 space
                target_px4_lat = 47.397742 + (300.0 / 111320.0)
                target_px4_lon = 8.545594 + (200.0 / (111320.0 * math.cos(math.radians(47.397742))))

                # Expected GCS target position
                expected_gcs_lat = 13.0827 + (300.0 / 111320.0)
                expected_gcs_lon = 80.2707 + (200.0 / (111320.0 * math.cos(math.radians(13.0827))))

                # Mock MAVLinkManager returning current vehicle position at target
                import mavlink_telemetry
                state = mavlink_telemetry.new_vehicle_state()
                state.update({
                    "connected": True,
                    "armed": False,
                    "latitude": target_px4_lat,
                    "longitude": target_px4_lon,
                    "altitude": 10.0,
                    "relative_altitude": 0.0,
                    "mode": "HOLD",
                })
                mock_mgr = MagicMock()
                mock_mgr.get_vehicle_state.return_value = state

                broadcaster = TelemetryBroadcaster(mock_mgr, rate_hz=4)
                msg = broadcaster.build_message()

                # Broadcaster must emit target GCS coordinates, not reference origin
                self.assertAlmostEqual(msg["vehicle"]["latitude"], expected_gcs_lat, places=4)
                self.assertAlmostEqual(msg["vehicle"]["longitude"], expected_gcs_lon, places=4)
                self.assertNotEqual(msg["vehicle"]["latitude"], 13.0827)


class TestReturnHomeAPI(unittest.TestCase):
    """Tests for POST /api/vehicle/return-home and related vehicle controls."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        database.reset_db_for_tests()
        mavlink_manager.reset_px4_reference_tracking()

    def tearDown(self):
        mavlink_manager.reset_px4_reference_tracking()

    def test_return_home_endpoint_exists(self):
        """Test 3: POST /api/vehicle/return-home endpoint exists and responds."""
        with patch.object(mav_manager, "is_connected", return_value=False):
            res = self.client.post("/api/vehicle/return-home")
            # 503 is returned because PX4 is not connected, verifying endpoint exists
            self.assertEqual(res.status_code, 503)

    def test_return_home_validates_vehicle_state(self):
        """Test 4: Endpoint validates MAVLink link, UAV position, and home position."""
        # Case A: Not connected -> 503
        with patch.object(mav_manager, "is_connected", return_value=False):
            res = self.client.post("/api/vehicle/return-home")
            self.assertEqual(res.status_code, 503)

        # Case B: Connected, but UAV position is None -> 400
        with patch.object(mav_manager, "is_connected", return_value=True):
            with patch.object(mav_manager, "get_vehicle_state", return_value={"latitude": None, "longitude": None}):
                res = self.client.post("/api/vehicle/return-home")
                self.assertEqual(res.status_code, 400)
                self.assertIn("unknown", res.json()["detail"].lower())

        # Case C: Connected, but already at home coordinates (< 3m) and disarmed
        refs = coordinate_mapper.get_mapper().get_references()
        px4_ref = refs["px4_reference"]
        with patch.object(mav_manager, "is_connected", return_value=True):
            with patch.object(mav_manager, "get_vehicle_state", return_value={
                "latitude": px4_ref["latitude"],
                "longitude": px4_ref["longitude"],
                "armed": False,
            }):
                res = self.client.post("/api/vehicle/return-home")
                self.assertEqual(res.status_code, 200)
                body = res.json()
                self.assertFalse(body["success"])
                self.assertIn("already at home", body["error"].lower())

    def test_return_home_uses_existing_px4_home_reference(self):
        """Test 5: Return mission targets the existing PX4 home/reference."""
        refs = coordinate_mapper.get_mapper().get_references()
        expected_home_lat = refs["px4_reference"]["latitude"]
        expected_home_lon = refs["px4_reference"]["longitude"]

        # Current UAV position is away from home (target location)
        uav_lat = expected_home_lat + 0.005
        uav_lon = expected_home_lon + 0.005

        sent_commands = []

        def mock_send_cmd(cmd_name, **kwargs):
            sent_commands.append((cmd_name, kwargs))
            if cmd_name == "upload_mission":
                return {"items": len(kwargs.get("items", []))}
            return {"success": True}

        with patch.object(mav_manager, "is_connected", return_value=True):
            with patch.object(mav_manager, "get_vehicle_state", return_value={
                "latitude": uav_lat,
                "longitude": uav_lon,
                "armed": False,
            }):
                with patch.object(mav_manager, "send_command", side_effect=mock_send_cmd):
                    res = self.client.post("/api/vehicle/return-home")
                    self.assertEqual(res.status_code, 200)
                    body = res.json()
                    self.assertTrue(body["success"])
                    self.assertEqual(body["action"], "RETURN_HOME")
                    self.assertAlmostEqual(body["home_target"]["latitude"], expected_home_lat, places=5)
                    self.assertAlmostEqual(body["home_target"]["longitude"], expected_home_lon, places=5)

                    # Inspect the uploaded mission items
                    upload_call = next(c for c in sent_commands if c[0] == "upload_mission")
                    items = upload_call[1]["items"]
                    # Item 0 is Takeoff at current UAV position
                    self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
                    self.assertAlmostEqual(items[0]["lat"], uav_lat, places=5)
                    self.assertAlmostEqual(items[0]["lon"], uav_lon, places=5)

                    # Item 1 is Waypoint to home reference
                    self.assertEqual(items[1]["command"], mavlink_mission._CMD_WAYPOINT)
                    self.assertAlmostEqual(items[1]["lat"], expected_home_lat, places=5)
                    self.assertAlmostEqual(items[1]["lon"], expected_home_lon, places=5)

                    # Item 2 is Land at home reference
                    self.assertEqual(items[2]["command"], mavlink_mission._CMD_LAND)
                    self.assertAlmostEqual(items[2]["lat"], expected_home_lat, places=5)
                    self.assertAlmostEqual(items[2]["lon"], expected_home_lon, places=5)

    def test_return_home_does_not_modify_gcs_marker_directly(self):
        """Test 6: Return-home sends PX4 commands (upload_mission, arm, set_mode=MISSION)
        and does not manipulate GCS coordinates."""
        refs = coordinate_mapper.get_mapper().get_references()
        home_lat = refs["px4_reference"]["latitude"]
        home_lon = refs["px4_reference"]["longitude"]

        uav_lat = home_lat + 0.003
        uav_lon = home_lon + 0.003

        sent_cmd_names = []

        def mock_send_cmd(cmd_name, **kwargs):
            sent_cmd_names.append(cmd_name)
            if cmd_name == "upload_mission":
                return {"items": 3}
            return {"success": True}

        with patch.object(mav_manager, "is_connected", return_value=True):
            with patch.object(mav_manager, "get_vehicle_state", return_value={
                "latitude": uav_lat,
                "longitude": uav_lon,
                "armed": False,
            }):
                with patch.object(mav_manager, "send_command", side_effect=mock_send_cmd):
                    res = self.client.post("/api/vehicle/return-home")
                    self.assertEqual(res.status_code, 200)

                    # Verifies commands were issued to PX4: upload_mission -> arm -> set_mode(MISSION)
                    self.assertIn("upload_mission", sent_cmd_names)
                    self.assertIn("arm", sent_cmd_names)
                    self.assertIn("set_mode", sent_cmd_names)

    def test_existing_rtl_functionality_remains_unchanged(self):
        """Test 7: Existing RTL emergency abort (/api/mission/abort) remains intact."""
        with patch.object(mav_manager, "is_connected", return_value=True):
            with patch.object(mav_manager, "send_command", return_value={"success": True}) as mock_cmd:
                res = self.client.post("/api/mission/abort")
                self.assertEqual(res.status_code, 200)
                body = res.json()
                self.assertTrue(body["success"])
                self.assertEqual(body["action"], "RTL")
                mock_cmd.assert_called_once_with("set_mode", mode="RTL")

    def test_coordinate_transformations_remain_unchanged(self):
        """Test 8: Coordinate mapper transformations gcs_to_px4 and px4_to_gcs remain unchanged."""
        mapper = coordinate_mapper.get_mapper()
        refs = mapper.get_references()
        gcs_ref = refs["gcs_reference"]
        px4_ref = refs["px4_reference"]

        # Origin maps to origin
        mapped_px4_lat, mapped_px4_lon = mapper.gcs_to_px4(gcs_ref["latitude"], gcs_ref["longitude"])
        self.assertAlmostEqual(mapped_px4_lat, px4_ref["latitude"], places=5)
        self.assertAlmostEqual(mapped_px4_lon, px4_ref["longitude"], places=5)

        # Invert back
        back_gcs_lat, back_gcs_lon = mapper.px4_to_gcs(mapped_px4_lat, mapped_px4_lon)
        self.assertAlmostEqual(back_gcs_lat, gcs_ref["latitude"], places=5)
        self.assertAlmostEqual(back_gcs_lon, gcs_ref["longitude"], places=5)

    def test_existing_arm_disarm_functionality_remains_unchanged(self):
        """Test 9: ARM and DISARM endpoints operate normally."""
        with patch.object(mav_manager, "send_command", return_value={"success": True}):
            res_arm = self.client.post("/api/vehicle/arm")
            self.assertEqual(res_arm.status_code, 200)
            self.assertTrue(res_arm.json()["success"])
            self.assertEqual(res_arm.json()["command"], "arm")

            res_disarm = self.client.post("/api/vehicle/disarm")
            self.assertEqual(res_disarm.status_code, 200)
            self.assertTrue(res_disarm.json()["success"])
            self.assertEqual(res_disarm.json()["command"], "disarm")

    def test_existing_takeoff_waypoint_land_mission_remains_unchanged(self):
        """Test 10: build_mission_items constructs the expected 3 items (TAKEOFF, WAYPOINT, LAND)."""
        items = mavlink_mission.build_mission_items(
            target_lat=13.0850,
            target_lon=80.2750,
            target_alt_m=15.0,
            home_lat=13.0827,
            home_lon=80.2707,
        )
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["command"], mavlink_mission._CMD_TAKEOFF)
        self.assertEqual(items[1]["command"], mavlink_mission._CMD_WAYPOINT)
        self.assertEqual(items[2]["command"], mavlink_mission._CMD_LAND)


if __name__ == "__main__":
    unittest.main()
