"""
Phase 6 tests for mavlink_commands.py.

Uses a Mock in place of a real pymavlink connection — these tests check
that the right MAVLink call is made with the right arguments, not that a
real vehicle responds (that needs SITL, which is a manual/integration
concern, not a unit test one).

Run from backend/:
    python3 -m unittest tests.test_mavlink_commands -v
"""

import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mavlink_commands as cmds
from pymavlink import mavutil


def fake_connection(mode_mapping=None):
    conn = Mock()
    conn.target_system = 1
    conn.target_component = 1
    conn.mode_mapping.return_value = mode_mapping
    return conn


class TestRequestDataStreams(unittest.TestCase):
    def test_requests_all_streams_at_given_rate(self):
        conn = fake_connection()
        cmds.request_data_streams(conn, rate_hz=4)
        conn.mav.request_data_stream_send.assert_called_once_with(
            1, 1, mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1
        )


class TestArmDisarm(unittest.TestCase):
    def test_arm_sends_component_arm_disarm_with_param1_one(self):
        conn = fake_connection()
        cmds.arm(conn)
        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0
        )

    def test_disarm_sends_param1_zero(self):
        conn = fake_connection()
        cmds.disarm(conn)
        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0
        )

class TestSetMode(unittest.TestCase):
    def _conn_with_ack(self, mode_mapping, result=0):
        conn = fake_connection(mode_mapping=mode_mapping)
        ack = Mock()
        ack.command = mavutil.mavlink.MAV_CMD_DO_SET_MODE
        ack.result = result  # 0 = MAV_RESULT_ACCEPTED
        conn.recv_match.return_value = ack
        return conn, ack

    def test_known_mode_sends_do_set_mode_and_returns_ack_on_accept(self):
        conn, ack = self._conn_with_ack({"POSCTL": (81, 3, 0)})
        result = cmds.set_mode(conn, "posctl")
        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0, 81, 3, 0, 0, 0, 0, 0
        )
        self.assertIs(result, ack)

    def test_rejected_ack_raises_command_rejected(self):
        conn, _ = self._conn_with_ack({"POSCTL": (81, 3, 0)}, result=4)  # MAV_RESULT_DENIED
        with self.assertRaises(cmds.CommandRejected):
            cmds.set_mode(conn, "POSCTL")

    def test_no_ack_raises_command_timeout(self):
        conn = fake_connection(mode_mapping={"POSCTL": (81, 3, 0)})
        conn.recv_match.return_value = None
        with self.assertRaises(cmds.CommandTimeout):
            cmds.set_mode(conn, "POSCTL", timeout_s=0.01)

    def test_unknown_mode_raises_without_sending(self):
        conn = fake_connection(mode_mapping={"POSCTL": (81, 3, 0)})
        with self.assertRaises(ValueError):
            cmds.set_mode(conn, "NOT_A_REAL_MODE")
        conn.mav.command_long_send.assert_not_called()

    def test_no_mode_mapping_yet_raises(self):
        conn = fake_connection(mode_mapping=None)
        with self.assertRaises(ValueError):
            cmds.set_mode(conn, "POSCTL")

    def test_non_tuple_mapping_entry_raises_runtime_error(self):
        # Guards against an ArduPilot-style int mapping being fed in here.
        conn = fake_connection(mode_mapping={"GUIDED": 4})
        with self.assertRaises(RuntimeError):
            cmds.set_mode(conn, "GUIDED")

if __name__ == "__main__":
    unittest.main()
