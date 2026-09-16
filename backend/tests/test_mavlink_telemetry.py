"""
Phase 6 tests for mavlink_telemetry.py.

Uses plain fake message objects (get_type() + the fields the parser
reads) rather than real pymavlink-encoded messages — the parser only
ever touches named attributes, so this is enough to test the field
mapping without a real connection or SITL.

Run from backend/:
    python3 -m unittest tests.test_mavlink_telemetry -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mavlink_telemetry as telem


class FakeMsg:
    def __init__(self, msg_type, **fields):
        self._type = msg_type
        for k, v in fields.items():
            setattr(self, k, v)

    def get_type(self):
        return self._type


class FakeConnNoModeMapping:
    """Simulates a connection that hasn't learned the vehicle's mode
    mapping yet (e.g. right after the very first heartbeat)."""

    def mode_mapping(self):
        return None


class FakeConnWithModeMapping:
    def mode_mapping(self):
        return {"STABILIZE": 0, "GUIDED": 4, "RTL": 6}


class TestNewVehicleState(unittest.TestCase):
    def test_all_fields_start_unknown(self):
        state = telem.new_vehicle_state()
        self.assertFalse(state["connected"])
        self.assertFalse(state["armed"])
        for field in (
            "mode",
            "latitude",
            "longitude",
            "altitude",
            "relative_altitude",
            "ground_speed",
            "heading",
            "battery",
            "gps_fix",
            "satellites",
            "last_heartbeat",
        ):
            self.assertIsNone(state[field])

    def test_returns_independent_copies(self):
        a = telem.new_vehicle_state()
        b = telem.new_vehicle_state()
        a["armed"] = True
        self.assertFalse(b["armed"])


class TestHeartbeat(unittest.TestCase):
    def test_armed_bit_decoded(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg("HEARTBEAT", base_mode=128 | 1, custom_mode=4)  # armed + custom_mode bit
        telem.update_from_message(state, msg, FakeConnWithModeMapping())
        self.assertTrue(state["armed"])
        self.assertEqual(state["mode"], "GUIDED")

    def test_disarmed(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg("HEARTBEAT", base_mode=1, custom_mode=6)
        telem.update_from_message(state, msg, FakeConnWithModeMapping())
        self.assertFalse(state["armed"])
        self.assertEqual(state["mode"], "RTL")

    def test_sets_last_heartbeat_timestamp(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg("HEARTBEAT", base_mode=0, custom_mode=0)
        telem.update_from_message(state, msg, FakeConnWithModeMapping())
        self.assertIsNotNone(state["last_heartbeat"])

    def test_falls_back_to_numeric_mode_without_mapping(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg("HEARTBEAT", base_mode=0, custom_mode=4)
        telem.update_from_message(state, msg, FakeConnNoModeMapping())
        self.assertEqual(state["mode"], "4")

    def test_works_without_a_connection_object(self):
        # mav_connection is optional (unit tests / callers that don't need
        # a human-readable mode name).
        state = telem.new_vehicle_state()
        msg = FakeMsg("HEARTBEAT", base_mode=0, custom_mode=4)
        telem.update_from_message(state, msg, mav_connection=None)
        self.assertEqual(state["mode"], "4")


class TestPosition(unittest.TestCase):
    def test_global_position_int(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=130827000,
            lon=802707000,
            alt=45000,
            relative_alt=15000,
            hdg=9000,
        )
        telem.update_from_message(state, msg)
        self.assertAlmostEqual(state["latitude"], 13.0827)
        self.assertAlmostEqual(state["longitude"], 80.2707)
        self.assertAlmostEqual(state["altitude"], 45.0)
        self.assertAlmostEqual(state["relative_altitude"], 15.0)
        self.assertAlmostEqual(state["heading"], 90.0)

    def test_heading_unknown_sentinel(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=0, lon=0, alt=0, relative_alt=0, hdg=65535,
        )
        telem.update_from_message(state, msg)
        self.assertIsNone(state["heading"])


class TestVfrHud(unittest.TestCase):
    def test_ground_speed_and_heading_fallback(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg("VFR_HUD", groundspeed=3.5, heading=270, throttle=50, alt=15, climb=0, airspeed=3.0)
        telem.update_from_message(state, msg)
        self.assertEqual(state["ground_speed"], 3.5)
        self.assertEqual(state["heading"], 270.0)

    def test_does_not_override_more_precise_gps_heading(self):
        state = telem.new_vehicle_state()
        state["heading"] = 91.23  # already set from GLOBAL_POSITION_INT
        msg = FakeMsg("VFR_HUD", groundspeed=3.5, heading=270, throttle=50, alt=15, climb=0, airspeed=3.0)
        telem.update_from_message(state, msg)
        self.assertEqual(state["heading"], 91.23)


class TestSysStatus(unittest.TestCase):
    def test_battery_percentage(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg(
            "SYS_STATUS",
            onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
            onboard_control_sensors_health=0, load=0, voltage_battery=12000,
            current_battery=0, battery_remaining=77, drop_rate_comm=0,
            errors_comm=0, errors_count1=0, errors_count2=0, errors_count3=0, errors_count4=0,
        )
        telem.update_from_message(state, msg)
        self.assertEqual(state["battery"], 77)

    def test_unknown_battery_sentinel(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg(
            "SYS_STATUS",
            onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
            onboard_control_sensors_health=0, load=0, voltage_battery=12000,
            current_battery=0, battery_remaining=-1, drop_rate_comm=0,
            errors_comm=0, errors_count1=0, errors_count2=0, errors_count3=0, errors_count4=0,
        )
        telem.update_from_message(state, msg)
        self.assertIsNone(state["battery"])


class TestGpsRawInt(unittest.TestCase):
    def test_fix_type_and_satellites(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg(
            "GPS_RAW_INT",
            time_usec=0, fix_type=3, lat=0, lon=0, alt=0, eph=0, epv=0, vel=0, cog=0,
            satellites_visible=11, alt_ellipsoid=0, h_acc=0, v_acc=0, vel_acc=0, hdg_acc=0, yaw=0,
        )
        telem.update_from_message(state, msg)
        self.assertEqual(state["gps_fix"], "FIX_3D")
        self.assertEqual(state["satellites"], 11)

    def test_unknown_satellite_count_sentinel(self):
        state = telem.new_vehicle_state()
        msg = FakeMsg(
            "GPS_RAW_INT",
            time_usec=0, fix_type=0, lat=0, lon=0, alt=0, eph=0, epv=0, vel=0, cog=0,
            satellites_visible=255, alt_ellipsoid=0, h_acc=0, v_acc=0, vel_acc=0, hdg_acc=0, yaw=0,
        )
        telem.update_from_message(state, msg)
        self.assertEqual(state["gps_fix"], "NO_GPS")
        self.assertIsNone(state["satellites"])


if __name__ == "__main__":
    unittest.main()
