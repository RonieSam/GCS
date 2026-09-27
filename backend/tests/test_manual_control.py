"""
Tests for manual control endpoints:
  POST /api/vehicle/manual-control
  POST /api/vehicle/manual-velocity
  POST /api/vehicle/resume-mission

And for mavlink_commands.send_velocity_setpoint().
"""

import sys
import os
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Minimal stubs so we can import the backend modules without PX4/SQLite/etc.
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import pymavlink
    from pymavlink import mavutil
    _FakeMavlink = mavutil.mavlink
except ImportError:
    # Stub pymavlink only if the library is not installed
    mav_stub = types.ModuleType("pymavlink")
    mavutil_stub = types.ModuleType("pymavlink.mavutil")

    # Populate the MAVLink enum constants used by send_velocity_setpoint
    class _FakeMavlink:
        MAV_FRAME_LOCAL_NED = 1
        POSITION_TARGET_TYPEMASK_X_IGNORE  = 0x0001
        POSITION_TARGET_TYPEMASK_Y_IGNORE  = 0x0002
        POSITION_TARGET_TYPEMASK_Z_IGNORE  = 0x0004
        POSITION_TARGET_TYPEMASK_AX_IGNORE = 0x0040
        POSITION_TARGET_TYPEMASK_AY_IGNORE = 0x0080
        POSITION_TARGET_TYPEMASK_AZ_IGNORE = 0x0100
        POSITION_TARGET_TYPEMASK_YAW_IGNORE = 0x0400
        MAV_RESULT_ACCEPTED = 0
        MAV_CMD_DO_SET_MODE = 176
        MAV_CMD_COMPONENT_ARM_DISARM = 400
        MAV_DATA_STREAM_ALL = 0
        enums = {"MAV_RESULT": {}}

    mavutil_stub.mavlink = _FakeMavlink()
    mavutil_stub.mavlink_connection = MagicMock()
    mav_stub.mavutil = mavutil_stub
    sys.modules.setdefault("pymavlink", mav_stub)
    sys.modules.setdefault("pymavlink.mavutil", mavutil_stub)


# ---------------------------------------------------------------------------
# Test: mavlink_commands.send_velocity_setpoint
# ---------------------------------------------------------------------------

import mavlink_commands


class TestSendVelocitySetpoint(unittest.TestCase):

    def _make_conn(self):
        conn = MagicMock()
        conn.target_system = 1
        conn.target_component = 0
        return conn

    def test_calls_set_position_target_local_ned(self):
        conn = self._make_conn()
        mavlink_commands.send_velocity_setpoint(conn, vx=1.0, vy=2.0, vz=0.5, yaw_rate=0.1)
        self.assertTrue(conn.mav.set_position_target_local_ned_send.called)

    def test_argument_positions(self):
        """Check that vx/vy/vz/yaw_rate land in the correct positions."""
        conn = self._make_conn()
        mavlink_commands.send_velocity_setpoint(conn, vx=1.5, vy=-2.0, vz=0.3, yaw_rate=-0.2)
        args = conn.mav.set_position_target_local_ned_send.call_args[0]
        # args[0]  = time_boot_ms
        # args[1]  = target_system
        # args[2]  = target_component
        # args[3]  = coordinate_frame (MAV_FRAME_LOCAL_NED)
        # args[4]  = type_mask
        # args[5]  = x (ignored)
        # args[6]  = y (ignored)
        # args[7]  = z (ignored)
        # args[8]  = vx
        # args[9]  = vy
        # args[10] = vz
        # args[11] = afx  (ignored)
        # args[12] = afy  (ignored)
        # args[13] = afz  (ignored)
        # args[14] = yaw  (ignored)
        # args[15] = yaw_rate
        self.assertAlmostEqual(args[8],  1.5,  places=5)   # vx
        self.assertAlmostEqual(args[9], -2.0,  places=5)   # vy
        self.assertAlmostEqual(args[10], 0.3,  places=5)   # vz
        self.assertAlmostEqual(args[15], -0.2, places=5)   # yaw_rate

    def test_frame_is_local_ned(self):
        conn = self._make_conn()
        mavlink_commands.send_velocity_setpoint(conn, vx=0, vy=0, vz=0, yaw_rate=0)
        args = conn.mav.set_position_target_local_ned_send.call_args[0]
        self.assertEqual(args[3], _FakeMavlink.MAV_FRAME_LOCAL_NED)

    def test_type_mask_ignores_position_and_yaw(self):
        """Type mask must have position-ignore bits set and NOT have velocity bits set."""
        conn = self._make_conn()
        mavlink_commands.send_velocity_setpoint(conn, vx=0, vy=0, vz=0, yaw_rate=0)
        args = conn.mav.set_position_target_local_ned_send.call_args[0]
        type_mask = args[4]

        # Position ignore bits (0,1,2) must be set
        self.assertTrue(type_mask & _FakeMavlink.POSITION_TARGET_TYPEMASK_X_IGNORE)
        self.assertTrue(type_mask & _FakeMavlink.POSITION_TARGET_TYPEMASK_Y_IGNORE)
        self.assertTrue(type_mask & _FakeMavlink.POSITION_TARGET_TYPEMASK_Z_IGNORE)
        # Velocity bits (3,4,5) must NOT be set (we want velocity control)
        self.assertFalse(type_mask & 0x0008)  # vx
        self.assertFalse(type_mask & 0x0010)  # vy
        self.assertFalse(type_mask & 0x0020)  # vz
        # Yaw position bit must be set (ignored)
        self.assertTrue(type_mask & _FakeMavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE)
        # Yaw-rate bit (12) must NOT be set (we want yaw_rate control)
        self.assertFalse(type_mask & 0x0800)


# ---------------------------------------------------------------------------
# Test: FastAPI endpoints
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient


class TestManualControlEndpoints(unittest.TestCase):

    def setUp(self):
        import main as _main
        self.main = _main

        self.mock_mav = MagicMock()
        self.mock_mav.is_connected.return_value = True
        self.mock_mav.link_state = "CONNECTED"
        self.mock_mav.get_vehicle_state.return_value = {
            "connected": True, "armed": True, "mode": "MISSION",
            "latitude": 13.0, "longitude": 80.0, "altitude": 10.0,
            "relative_altitude": 10.0, "ground_speed": 5.0, "heading": 0.0,
            "battery": 80.0, "gps_fix": "3D_FIX", "satellites": 12,
            "last_heartbeat": 0.0, "mission_current": 1, "mission_item_reached": 1,
        }
        self.mock_mav.get_mission_upload_state.return_value = {
            "status": "UPLOADED", "mission_id": 1, "items": 3, "error": None,
        }
        self.mock_mav.send_command.return_value = {"success": True}
        self._orig_mav = _main.mav_manager
        _main.mav_manager = self.mock_mav
        self.client = TestClient(_main.app)

    def tearDown(self):
        self.main.mav_manager = self._orig_mav

    # ---- /api/vehicle/manual-control ----

    def test_manual_control_success(self):
        resp = self.client.post("/api/vehicle/manual-control")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["mode"], "POSCTL")
        self.mock_mav.send_command.assert_called_with("set_mode", mode="POSCTL")

    def test_manual_control_not_connected(self):
        self.mock_mav.is_connected.return_value = False
        resp = self.client.post("/api/vehicle/manual-control")
        self.assertEqual(resp.status_code, 503)

    def test_manual_control_sets_session_state(self):
        self.client.post("/api/vehicle/manual-control")
        self.assertEqual(self.main.session_state["mission_state"], "MANUAL")

    def test_manual_control_command_rejected(self):
        self.mock_mav.send_command.side_effect = mavlink_commands.CommandRejected("set_mode(POSCTL)", 99)
        resp = self.client.post("/api/vehicle/manual-control")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertIn("error", body)

    def test_manual_control_command_timeout(self):
        self.mock_mav.send_command.side_effect = mavlink_commands.CommandTimeout("set_mode(POSCTL)")
        resp = self.client.post("/api/vehicle/manual-control")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])

    # ---- /api/vehicle/manual-velocity ----

    def test_manual_velocity_success(self):
        resp = self.client.post(
            "/api/vehicle/manual-velocity",
            json={"vx": 1.0, "vy": 0.5, "vz": -0.3, "yaw_rate": 0.1},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.mock_mav.send_command.assert_called_with(
            "send_velocity", vx=1.0, vy=0.5, vz=-0.3, yaw_rate=0.1
        )

    def test_manual_velocity_clamped(self):
        resp = self.client.post(
            "/api/vehicle/manual-velocity",
            json={"vx": 99.0, "vy": -99.0, "vz": 99.0, "yaw_rate": 99.0},
        )
        self.assertEqual(resp.status_code, 200)
        call_kwargs = self.mock_mav.send_command.call_args[1]
        self.assertLessEqual(call_kwargs["vx"], 10.0)
        self.assertGreaterEqual(call_kwargs["vy"], -10.0)
        self.assertLessEqual(call_kwargs["yaw_rate"], 1.5)

    def test_manual_velocity_not_connected_returns_200(self):
        self.mock_mav.is_connected.return_value = False
        resp = self.client.post(
            "/api/vehicle/manual-velocity",
            json={"vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])

    def test_manual_velocity_invalid_body(self):
        resp = self.client.post("/api/vehicle/manual-velocity", json={"vx": "nope"})
        self.assertEqual(resp.status_code, 422)

    # ---- /api/vehicle/resume-mission ----

    def test_resume_mission_success(self):
        resp = self.client.post("/api/vehicle/resume-mission")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["mode"], "MISSION")
        self.mock_mav.send_command.assert_called_with("set_mode", mode="MISSION")

    def test_resume_mission_not_connected(self):
        self.mock_mav.is_connected.return_value = False
        resp = self.client.post("/api/vehicle/resume-mission")
        self.assertEqual(resp.status_code, 503)

    def test_resume_mission_sets_session_state(self):
        self.main.session_state["mission_state"] = "MANUAL"
        self.client.post("/api/vehicle/resume-mission")
        self.assertEqual(self.main.session_state["mission_state"], "EXECUTING")

    def test_resume_mission_command_rejected(self):
        self.mock_mav.send_command.side_effect = mavlink_commands.CommandRejected("set_mode(MISSION)", 99)
        resp = self.client.post("/api/vehicle/resume-mission")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["success"])

    def test_resume_mission_command_timeout(self):
        self.mock_mav.send_command.side_effect = mavlink_commands.CommandTimeout("set_mode(MISSION)")
        resp = self.client.post("/api/vehicle/resume-mission")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["success"])


if __name__ == "__main__":
    unittest.main()
