"""
Phase 6 — vehicle state model and MAVLink message parsing.

This module owns two things:

1. The shape of `vehicle_state` — the single source of truth described in
   the Phase 6 plan (section 14). Everything the rest of the backend knows
   about the live vehicle comes from this dict.
2. Turning individual incoming pymavlink messages into updates to that
   dict. It does not touch the connection itself (mavlink_manager.py does
   that) and does not decide connection health (safety_manager.py does
   that) — this module is pure "message in, state fields out".

Kept separate from mavlink_manager.py so the parsing logic (which fields
come from which message type) can be unit-tested with plain synthetic
message objects, no real socket/connection required.
"""

import time


def new_vehicle_state():
    """A fresh, all-unknown vehicle state — used at startup and whenever
    the connection drops, so stale values from a previous link are never
    mistaken for current ones."""
    return {
        "connected": False,
        "armed": False,
        "mode": None,
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "relative_altitude": None,
        "ground_speed": None,
        "heading": None,
        "battery": None,
        "gps_fix": None,
        "satellites": None,
        "last_heartbeat": None,
        # Phase 8 — active mission progress (None when no mission is executing)
        "mission_current": None,       # sequence number of current waypoint
        "mission_item_reached": None,  # sequence number of last reached waypoint
    }


# ArduPilot copter/plane/rover all report GPS fix as an integer enum from
# GPS_RAW_INT.fix_type. Mapped here so the API/GCS can show a word instead
# of a magic number.
_GPS_FIX_TYPES = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "FIX_2D",
    3: "FIX_3D",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
    7: "STATIC",
    8: "PPP",
}

# base_mode is a bitmask; this is the one bit Phase 6 cares about (armed vs
# not). See MAVLink common.xml MAV_MODE_FLAG_SAFETY_ARMED = 128.
_MAV_MODE_FLAG_SAFETY_ARMED = 128


def _decode_mode(msg, mav_connection=None):
    """Decode HEARTBEAT custom_mode into a readable flight mode."""
    if mav_connection is not None:
        try:
            mapping = mav_connection.mode_mapping()
            if mapping:
                inv_map = {v: k for k, v in mapping.items()}
                if msg.custom_mode in inv_map:
                    return inv_map[msg.custom_mode]
        except Exception:
            pass

    custom_mode = int(msg.custom_mode)

    # PX4 custom_mode is a 32-bit value:
    #   main_mode  = bits 16-23
    #   sub_mode   = bits 24-31
    main_mode = (custom_mode >> 16) & 0xFF
    sub_mode = (custom_mode >> 24) & 0xFF

    px4_modes = {
        1: "MANUAL",
        2: "ALTCTL",
        3: "POSCTL",
        4: {
            1: "AUTO_READY",
            2: "AUTO_TAKEOFF",
            3: "AUTO_LOITER",
            4: "AUTO_MISSION",
            5: "AUTO_RTL",
            6: "AUTO_LAND",
            7: "AUTO_RESERVED",
            8: "AUTO_RTGS",
            9: "AUTO_FOLLOW_TARGET",
            10: "AUTO_PRECLAND",
        },
        5: "ACRO",
        6: "OFFBOARD",
        7: "STABILIZED",
        8: "RATTITUDE",
    }

    mode = px4_modes.get(main_mode)

    if isinstance(mode, dict):
        return mode.get(sub_mode, f"AUTO_UNKNOWN({sub_mode})")

    if mode:
        return mode

    if main_mode == 0 and sub_mode == 0 and custom_mode != 0:
        return str(custom_mode)

    return f"UNKNOWN({main_mode},{sub_mode})"

def update_from_message(state, msg, mav_connection=None):
    """Update `state` in place from one incoming MAVLink message.

    `mav_connection` is optional and only used to resolve HEARTBEAT's
    custom_mode into a human-readable mode name — pass None (e.g. from a
    test) to just get the raw numeric mode string instead.

    Returns `state` for convenience.
    """
    msg_type = msg.get_type()

    if msg_type == "HEARTBEAT":
        state["armed"] = bool(msg.base_mode & _MAV_MODE_FLAG_SAFETY_ARMED)
        state["mode"] = _decode_mode(msg, mav_connection)
        state["last_heartbeat"] = time.time()

    elif msg_type == "GLOBAL_POSITION_INT":
        state["latitude"] = msg.lat / 1e7
        state["longitude"] = msg.lon / 1e7
        state["altitude"] = msg.alt / 1000.0  # AMSL, mm -> m
        state["relative_altitude"] = msg.relative_alt / 1000.0  # mm -> m
        state["heading"] = msg.hdg / 100.0 if msg.hdg != 65535 else None

    elif msg_type == "VFR_HUD":
        state["ground_speed"] = msg.groundspeed
        # VFR_HUD's heading is a plain integer degrees; prefer it as a
        # fallback only, GLOBAL_POSITION_INT's hdg is more precise.
        if state.get("heading") is None:
            state["heading"] = float(msg.heading)

    elif msg_type == "SYS_STATUS":
        # battery_remaining is a percentage, -1 when the autopilot doesn't
        # know (no battery monitor configured).
        state["battery"] = msg.battery_remaining if msg.battery_remaining >= 0 else None

    elif msg_type == "GPS_RAW_INT":
        state["gps_fix"] = _GPS_FIX_TYPES.get(msg.fix_type, f"UNKNOWN({msg.fix_type})")
        state["satellites"] = msg.satellites_visible if msg.satellites_visible != 255 else None

    elif msg_type == "MISSION_CURRENT":
        # PX4 broadcasts this whenever the active mission waypoint changes.
        # seq is the 0-based index of the waypoint currently being executed.
        state["mission_current"] = int(msg.seq)

    elif msg_type == "MISSION_ITEM_REACHED":
        # PX4 sends this each time it successfully reaches a waypoint.
        state["mission_item_reached"] = int(msg.seq)

    return state
