"""
Phase 8 unit tests — MAVLink mission upload protocol.

All pymavlink calls are mocked. These tests verify:
  - build_mission_items() produces valid MAVLink-compatible items
  - upload_mission() handles MISSION_REQUEST_INT → send → MISSION_ACK accepted
  - upload_mission() handles MISSION_REQUEST (non-INT)  → send → MISSION_ACK accepted
  - upload_mission() raises MissionTimeout when no response arrives
  - upload_mission() raises MissionRejected when PX4 sends a failure ACK
  - upload_mission() raises InvalidMission on bad coordinates / altitude
  - mav_mission_ack_name() resolves known codes to readable strings

Run from backend/:
    python3 -m unittest tests.test_mission_upload -v
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, Mock, call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mavlink_mission as mm
from pymavlink import mavutil


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn():
    """Return a minimal Mock that looks like a pymavlink connection."""
    conn = Mock()
    conn.target_system = 1
    conn.target_component = 1
    conn.mav = Mock()
    return conn


def _msg(type_name, **attrs):
    """Build a minimal fake MAVLink message."""
    msg = Mock()
    msg.get_type.return_value = type_name
    for k, v in attrs.items():
        setattr(msg, k, v)
    return msg


# ---------------------------------------------------------------------------
# build_mission_items
# ---------------------------------------------------------------------------


class TestBuildMissionItems(unittest.TestCase):

    def test_returns_two_items(self):
        items = mm.build_mission_items(13.0827, 80.2707, 15.0)
        self.assertEqual(len(items), 2)

    def test_item0_is_takeoff(self):
        items = mm.build_mission_items(13.0827, 80.2707, 15.0)
        takeoff = items[0]
        self.assertEqual(takeoff["seq"], 0)
        self.assertEqual(takeoff["command"], mavutil.mavlink.MAV_CMD_NAV_TAKEOFF)
        self.assertEqual(takeoff["current"], 1)
        self.assertEqual(takeoff["autocontinue"], 1)
        self.assertEqual(takeoff["alt"], 15.0)

    def test_item1_is_waypoint_with_target_coords(self):
        lat, lon, alt = 13.0827, 80.2707, 20.0
        items = mm.build_mission_items(lat, lon, alt)
        wp = items[1]
        self.assertEqual(wp["seq"], 1)
        self.assertEqual(wp["command"], mavutil.mavlink.MAV_CMD_NAV_WAYPOINT)
        self.assertEqual(wp["current"], 0)
        self.assertAlmostEqual(wp["lat"], lat, places=6)
        self.assertAlmostEqual(wp["lon"], lon, places=6)
        self.assertEqual(wp["alt"], alt)

    def test_frame_is_global_relative_alt(self):
        items = mm.build_mission_items(0.0, 0.0, 10.0)
        for item in items:
            self.assertEqual(
                item["frame"],
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            )

    def test_invalid_latitude_raises(self):
        with self.assertRaises(mm.InvalidMission):
            mm.build_mission_items(91.0, 0.0, 10.0)

    def test_invalid_longitude_raises(self):
        with self.assertRaises(mm.InvalidMission):
            mm.build_mission_items(0.0, 181.0, 10.0)

    def test_zero_altitude_raises(self):
        with self.assertRaises(mm.InvalidMission):
            mm.build_mission_items(0.0, 0.0, 0.0)

    def test_negative_altitude_raises(self):
        with self.assertRaises(mm.InvalidMission):
            mm.build_mission_items(0.0, 0.0, -5.0)

    def test_southern_hemisphere_coordinates(self):
        # Negative lat/lon must be valid.
        items = mm.build_mission_items(-33.8688, 151.2093, 50.0)
        self.assertEqual(len(items), 2)


# ---------------------------------------------------------------------------
# mav_mission_ack_name
# ---------------------------------------------------------------------------


class TestMavMissionAckName(unittest.TestCase):

    def test_zero_is_accepted(self):
        name = mm.mav_mission_ack_name(0)
        # pymavlink uses MAV_MISSION_ACCEPTED for code 0
        self.assertIn("ACCEPTED", name)

    def test_unknown_code_includes_code_number(self):
        name = mm.mav_mission_ack_name(9999)
        self.assertIn("9999", name)


# ---------------------------------------------------------------------------
# upload_mission — success paths
# ---------------------------------------------------------------------------


class TestUploadMissionSuccess(unittest.TestCase):

    def _make_items(self):
        return mm.build_mission_items(13.0827, 80.2707, 15.0)

    def test_success_via_mission_request_int(self):
        """PX4 requests each item with MISSION_REQUEST_INT → upload succeeds."""
        conn = _make_conn()
        items = self._make_items()
        n = len(items)

        # Simulate: PX4 requests item 0, then item 1, then sends MISSION_ACK=accepted
        req0 = _msg("MISSION_REQUEST_INT", seq=0)
        req1 = _msg("MISSION_REQUEST_INT", seq=1)
        ack  = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_ACCEPTED)

        conn.recv_match.side_effect = [req0, req1, ack]

        result = mm.upload_mission(conn, items, timeout_s=5)
        self.assertEqual(result, n)

        # Verify MISSION_CLEAR_ALL and MISSION_COUNT were sent.
        conn.mav.mission_clear_all_send.assert_called_once_with(1, 1)
        conn.mav.mission_count_send.assert_called_once_with(1, 1, n)

        # Verify two MISSION_ITEM_INT sends (one per item).
        self.assertEqual(conn.mav.mission_item_int_send.call_count, n)

    def test_success_via_mission_request_non_int(self):
        """PX4 requests each item with MISSION_REQUEST (float) → upload succeeds."""
        conn = _make_conn()
        items = self._make_items()

        req0 = _msg("MISSION_REQUEST", seq=0)
        req1 = _msg("MISSION_REQUEST", seq=1)
        ack  = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_ACCEPTED)

        conn.recv_match.side_effect = [req0, req1, ack]

        result = mm.upload_mission(conn, items, timeout_s=5)
        self.assertEqual(result, len(items))
        self.assertEqual(conn.mav.mission_item_send.call_count, len(items))
        # INT variant should NOT have been called.
        conn.mav.mission_item_int_send.assert_not_called()

    def test_px4_requests_items_out_of_order(self):
        """Protocol: PX4 may request item 1 before item 0 — respond correctly."""
        conn = _make_conn()
        items = self._make_items()

        req1 = _msg("MISSION_REQUEST_INT", seq=1)
        req0 = _msg("MISSION_REQUEST_INT", seq=0)
        ack  = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_ACCEPTED)

        conn.recv_match.side_effect = [req1, req0, ack]

        result = mm.upload_mission(conn, items, timeout_s=5)
        self.assertEqual(result, len(items))

        # First call should have sent item 1, second item 0.
        calls = conn.mav.mission_item_int_send.call_args_list
        self.assertEqual(len(calls), 2)
        # call args: (ts, tc, seq, frame, cmd, current, autocontinue, ...)
        # seq is the 3rd positional arg (index 2)
        sent_seqs = [c[0][2] for c in calls]
        self.assertEqual(sent_seqs[0], 1)
        self.assertEqual(sent_seqs[1], 0)

    def test_mixed_request_types(self):
        """PX4 may send MISSION_REQUEST for one item and MISSION_REQUEST_INT for another."""
        conn = _make_conn()
        items = self._make_items()

        req0_int   = _msg("MISSION_REQUEST_INT", seq=0)
        req1_float = _msg("MISSION_REQUEST",     seq=1)
        ack        = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_ACCEPTED)

        conn.recv_match.side_effect = [req0_int, req1_float, ack]

        result = mm.upload_mission(conn, items, timeout_s=5)
        self.assertEqual(result, len(items))
        self.assertEqual(conn.mav.mission_item_int_send.call_count, 1)
        self.assertEqual(conn.mav.mission_item_send.call_count, 1)


# ---------------------------------------------------------------------------
# upload_mission — failure paths
# ---------------------------------------------------------------------------


class TestUploadMissionFailure(unittest.TestCase):

    def _make_items(self):
        return mm.build_mission_items(13.0827, 80.2707, 15.0)

    def test_timeout_when_no_response(self):
        """recv_match always returns None → MissionTimeout raised."""
        conn = _make_conn()
        conn.recv_match.return_value = None

        with self.assertRaises(mm.MissionTimeout):
            mm.upload_mission(conn, self._make_items(), timeout_s=0.05)

    def test_rejected_on_mission_ack_failure(self):
        """PX4 sends MISSION_ACK with non-zero result → MissionRejected."""
        conn = _make_conn()
        items = self._make_items()

        req0 = _msg("MISSION_REQUEST_INT", seq=0)
        req1 = _msg("MISSION_REQUEST_INT", seq=1)
        # MAV_MISSION_NO_SPACE = 1 is a commonly tested failure code.
        ack  = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_NO_SPACE)

        conn.recv_match.side_effect = [req0, req1, ack]

        with self.assertRaises(mm.MissionRejected) as ctx:
            mm.upload_mission(conn, items, timeout_s=5)
        self.assertEqual(ctx.exception.result_code, mavutil.mavlink.MAV_MISSION_NO_SPACE)

    def test_rejected_ack_contains_result_name(self):
        """MissionRejected.result_name should contain a meaningful string."""
        conn = _make_conn()
        items = self._make_items()

        req0 = _msg("MISSION_REQUEST_INT", seq=0)
        req1 = _msg("MISSION_REQUEST_INT", seq=1)
        ack  = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_ERROR)

        conn.recv_match.side_effect = [req0, req1, ack]

        with self.assertRaises(mm.MissionRejected) as ctx:
            mm.upload_mission(conn, items, timeout_s=5)
        self.assertIsInstance(ctx.exception.result_name, str)
        self.assertTrue(len(ctx.exception.result_name) > 0)

    def test_invalid_sequence_request_raises(self):
        """PX4 requests an out-of-range seq → MissionUploadError."""
        conn = _make_conn()
        items = self._make_items()

        bad_req = _msg("MISSION_REQUEST_INT", seq=99)
        conn.recv_match.side_effect = [bad_req]

        with self.assertRaises(mm.MissionUploadError):
            mm.upload_mission(conn, items, timeout_s=5)

    def test_empty_items_raises_invalid_mission(self):
        conn = _make_conn()
        with self.assertRaises(mm.InvalidMission):
            mm.upload_mission(conn, [], timeout_s=5)

    def test_integer_coordinates_for_mission_item_int(self):
        """MISSION_ITEM_INT must use int(lat * 1e7) and int(lon * 1e7)."""
        lat, lon = 13.12345, 80.54321
        conn = _make_conn()
        items = mm.build_mission_items(lat, lon, 15.0)

        # Only request item 1 (the waypoint with real coords), skip item 0.
        req1 = _msg("MISSION_REQUEST_INT", seq=1)
        ack  = _msg("MISSION_ACK", type=mavutil.mavlink.MAV_MISSION_ACCEPTED)
        req0 = _msg("MISSION_REQUEST_INT", seq=0)
        conn.recv_match.side_effect = [req0, req1, ack]

        mm.upload_mission(conn, items, timeout_s=5)

        # Find the call that sent item 1 (the waypoint).
        calls = conn.mav.mission_item_int_send.call_args_list
        # Second call is item 1.
        wp_call = calls[1][0]  # positional args tuple
        sent_lat_int = wp_call[11]
        sent_lon_int = wp_call[12]

        self.assertEqual(sent_lat_int, int(round(lat * 1e7)))
        self.assertEqual(sent_lon_int, int(round(lon * 1e7)))


# ---------------------------------------------------------------------------
# build_mission_items edge cases
# ---------------------------------------------------------------------------


class TestBuildMissionItemsEdgeCases(unittest.TestCase):

    def test_boundary_latitudes(self):
        """Exactly ±90 lat should be valid."""
        mm.build_mission_items(90.0, 0.0, 10.0)
        mm.build_mission_items(-90.0, 0.0, 10.0)

    def test_boundary_longitudes(self):
        """Exactly ±180 lon should be valid."""
        mm.build_mission_items(0.0, 180.0, 10.0)
        mm.build_mission_items(0.0, -180.0, 10.0)

    def test_very_small_positive_altitude(self):
        """Any positive altitude (even 0.001 m) is valid."""
        items = mm.build_mission_items(0.0, 0.0, 0.001)
        self.assertEqual(len(items), 2)


if __name__ == "__main__":
    unittest.main()
