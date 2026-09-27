"""
Phase 6 tests for mavlink_manager.MAVLinkManager.

mavutil.mavlink_connection() is patched to return a small fake connection
object instead of opening a real socket — these tests check the
manager's own logic (state transitions, vehicle_state updates, command
dispatch), not pymavlink's UDP handling or a real SITL, which is what the
manual "first milestone" checklist in the Phase 6 plan is for.

Run from backend/:
    python3 -m unittest tests.test_mavlink_manager -v
"""

import os
import sys
import time
import unittest
from unittest.mock import Mock, patch

from pymavlink import mavutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mavlink_manager import MAVLinkManager
from safety_manager import CONNECTED, DISCONNECTED


class FakeHeartbeat:
    def __init__(self, base_mode=128, custom_mode=4):
        self.base_mode = base_mode
        self.custom_mode = custom_mode

    def get_type(self):
        return "HEARTBEAT"


class FakeConn:
    """Stands in for a pymavlink connection. recv_match(type="HEARTBEAT",
    ...) is what MAVLinkManager._wait_heartbeat_interruptible actually
    calls during connect — not wait_heartbeat() — so that's what this
    fakes."""

    def __init__(self, heartbeat=None):
        self.target_system = 1
        self.target_component = 1
        self._heartbeat = heartbeat
        self._delivered = False
        self.closed = False
        self.sent = []

    def mode_mapping(self):
        return {"STABILIZE": 0, "GUIDED": 4}

    def recv_match(self, type=None, blocking=True, timeout=None):
        if type == "HEARTBEAT" and not self._delivered:
            self._delivered = True
            return self._heartbeat
        if type == "COMMAND_ACK":
            ack = Mock()
            ack.command = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
            ack.result = 0
            return ack
        return None

    def close(self):
        self.closed = True

    @property
    def mav(self):
        return self

    def request_data_stream_send(self, *a, **k):
        self.sent.append(("request_data_stream_send", a, k))

    def command_long_send(self, *a, **k):
        self.sent.append(("command_long_send", a, k))

    def set_mode_send(self, *a, **k):
        self.sent.append(("set_mode_send", a, k))


class TestConnect(unittest.TestCase):
    def test_successful_connect_updates_state_and_link(self):
        conn = FakeConn(heartbeat=FakeHeartbeat(base_mode=128 | 1, custom_mode=4))
        with patch("mavlink_manager.mavutil.mavlink_connection", return_value=conn):
            manager = MAVLinkManager("fake://", connect_timeout_s=0.2)
            ok = manager.connect()

        self.assertTrue(ok)
        self.assertTrue(manager.is_connected())
        self.assertEqual(manager.link_state, CONNECTED)

        state = manager.get_vehicle_state()
        self.assertTrue(state["connected"])
        self.assertTrue(state["armed"])
        self.assertEqual(state["mode"], "GUIDED")
        # request_data_streams should have been called once connected.
        self.assertTrue(any(call[0] == "request_data_stream_send" for call in conn.sent))

    def test_no_heartbeat_leaves_disconnected(self):
        conn = FakeConn(heartbeat=None)  # never delivers a heartbeat
        with patch("mavlink_manager.mavutil.mavlink_connection", return_value=conn):
            manager = MAVLinkManager("fake://", connect_timeout_s=0.1)
            ok = manager.connect()

        self.assertFalse(ok)
        self.assertFalse(manager.is_connected())
        self.assertEqual(manager.link_state, DISCONNECTED)
        self.assertTrue(conn.closed)

    def test_connection_open_failure_leaves_disconnected(self):
        with patch("mavlink_manager.mavutil.mavlink_connection", side_effect=OSError("no socket")):
            manager = MAVLinkManager("fake://", connect_timeout_s=0.1)
            ok = manager.connect()

        self.assertFalse(ok)
        self.assertFalse(manager.is_connected())


class TestSendCommand(unittest.TestCase):
    def test_raises_when_not_connected(self):
        manager = MAVLinkManager("fake://")
        with self.assertRaises(RuntimeError):
            manager.send_command("arm")

    def test_arm_dispatches_to_connection(self):
        conn = FakeConn(heartbeat=FakeHeartbeat())
        with patch("mavlink_manager.mavutil.mavlink_connection", return_value=conn):
            manager = MAVLinkManager("fake://", connect_timeout_s=0.1)
            manager.connect()
            manager.send_command("arm")

        self.assertTrue(any(call[0] == "command_long_send" for call in conn.sent))

    def test_unknown_command_raises(self):
        conn = FakeConn(heartbeat=FakeHeartbeat())
        with patch("mavlink_manager.mavutil.mavlink_connection", return_value=conn):
            manager = MAVLinkManager("fake://", connect_timeout_s=0.1)
            manager.connect()
            with self.assertRaises(ValueError):
                manager.send_command("takeoff")


class TestBackgroundLifecycle(unittest.TestCase):
    def test_start_then_stop_background_is_clean(self):
        conn = FakeConn(heartbeat=FakeHeartbeat())
        with patch("mavlink_manager.mavutil.mavlink_connection", return_value=conn):
            manager = MAVLinkManager("fake://", connect_timeout_s=0.2, reconnect_interval_s=0.1)
            manager.start_background()

            deadline = time.time() + 2
            while time.time() < deadline and not manager.is_connected():
                time.sleep(0.02)

            self.assertTrue(manager.is_connected())
            manager.stop_background()

        self.assertFalse(manager.is_connected())
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
