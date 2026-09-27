"""
Phase 8 — MAVLink mission upload protocol.

This module implements the MAVLink mission upload handshake and provides
helpers for building PX4-compatible mission items.

CRITICAL THREADING CONTRACT:
    upload_mission() calls conn.recv_match() directly.  It MUST only be
    invoked from the single thread that owns the pymavlink connection
    (MAVLinkManager._process_command_queue).  Never call it from a FastAPI
    request handler or any other thread.

Protocol flow (GCS → PX4):
    MISSION_CLEAR_ALL
         ↓
    MISSION_COUNT  (n items)
         ↓
    PX4 sends MISSION_REQUEST or MISSION_REQUEST_INT for each item
         ↓
    GCS sends the requested MISSION_ITEM or MISSION_ITEM_INT
         ↓
    PX4 sends MISSION_ACK
         ↓
    GCS returns success / raises on non-zero result
"""

import time

from pymavlink import mavutil

import config


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MissionUploadError(Exception):
    """Base class for all mission upload failures."""


class MissionTimeout(MissionUploadError):
    """PX4 did not respond within the configured timeout."""

    def __init__(self, phase, timeout_s):
        self.phase = phase
        super().__init__(
            f"Mission upload timed out waiting for {phase} "
            f"(no response within {timeout_s}s)"
        )


class MissionRejected(MissionUploadError):
    """PX4 sent MISSION_ACK with a non-zero (failure) result."""

    def __init__(self, result_code):
        self.result_code = result_code
        self.result_name = mav_mission_ack_name(result_code)
        super().__init__(
            f"PX4 rejected mission: {self.result_name} (code {result_code})"
        )


class InvalidMission(MissionUploadError):
    """The mission data itself is invalid before we even send it."""


# ---------------------------------------------------------------------------
# MAV_MISSION_RESULT name helper
# ---------------------------------------------------------------------------


def mav_mission_ack_name(result_code):
    """Return a human-readable string for a MAV_MISSION_RESULT enum value.

    Uses the installed pymavlink dialect; falls back gracefully if the
    enum entry is absent (e.g. a future PX4 version adds a new code).
    """
    entry = mavutil.mavlink.enums.get("MAV_MISSION_RESULT", {}).get(result_code)
    if entry is not None:
        return entry.name
    return f"MAV_MISSION_RESULT_UNKNOWN({result_code})"


# ---------------------------------------------------------------------------
# Mission item construction
# ---------------------------------------------------------------------------

# MAVLink coordinate frame — relative to home altitude.
# PX4 SITL supports MAV_FRAME_GLOBAL_RELATIVE_ALT (int value 3).
_FRAME_GLOBAL_RELATIVE_ALT = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT

# MAV_CMD values used in our simple three-item mission.
_CMD_TAKEOFF   = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
_CMD_WAYPOINT  = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
_CMD_LAND      = mavutil.mavlink.MAV_CMD_NAV_LAND


def build_survey_mission_items(
    px4_waypoints,
    home_lat,
    home_lon,
    return_lat=None,
    return_lon=None,
    return_alt_m=None,
):
    """Build a PX4 MAVLink mission for an RF scan survey path ending at the final survey point.

    Phase 4: RF survey mission sequence is:
      TAKEOFF -> SURVEY WAYPOINTS -> FINAL SURVEY WAYPOINT -> SCAN COMPLETE.
      There is NO return to scan-start, NO return home, NO automatic landing, and NO RTL.
      The UAV holds/hovers at the final survey waypoint.

    Constructs a mission with:
      Item 0    — TAKEOFF from home to survey altitude.
      Items 1…N — NAV_WAYPOINT for each survey waypoint (PX4 coordinates).

    Args:
        px4_waypoints (list[dict]): Survey waypoints already converted to PX4
                                    coordinates (seq, lat, lon, alt, line_idx).
        home_lat (float): PX4 home/takeoff latitude.
        home_lon (float): PX4 home/takeoff longitude.
        return_lat: Unused in Phase 4 (kept for signature compatibility).
        return_lon: Unused in Phase 4 (kept for signature compatibility).
        return_alt_m: Unused in Phase 4 (kept for signature compatibility).

    Returns:
        list[dict]: Mission items ready for upload_mission().

    Raises:
        InvalidMission: If px4_waypoints is empty or coordinates invalid.
    """
    if not px4_waypoints:
        raise InvalidMission("Cannot build a survey mission with zero waypoints.")

    alt = px4_waypoints[0]["alt"]
    if alt <= 0:
        raise InvalidMission(f"Survey altitude must be positive (got {alt}m).")

    for wp in px4_waypoints:
        if not (-90 <= wp["lat"] <= 90):
            raise InvalidMission(f"Survey waypoint latitude {wp['lat']} out of range.")
        if not (-180 <= wp["lon"] <= 180):
            raise InvalidMission(f"Survey waypoint longitude {wp['lon']} out of range.")

    common = dict(
        frame        = _FRAME_GLOBAL_RELATIVE_ALT,
        autocontinue = 1,
        param1       = 0.0,
        param2       = 0.0,
        param3       = 0.0,
        param4       = 0.0,
    )

    items = []

    # Item 0: TAKEOFF from PX4 home to survey altitude.
    items.append({
        **common,
        "seq"     : 0,
        "command" : _CMD_TAKEOFF,
        "current" : 1,
        "param1"  : 0.0,
        "lat"     : home_lat,
        "lon"     : home_lon,
        "alt"     : alt,
    })

    # Items 1…N: Survey NAV_WAYPOINT items. Ends at final survey waypoint.
    for i, wp in enumerate(px4_waypoints):
        items.append({
            **common,
            "seq"     : i + 1,
            "command" : _CMD_WAYPOINT,
            "current" : 0,
            "param1"  : 0.0,   # hold time (s)
            "param2"  : 2.0,   # acceptance radius (m)
            "lat"     : wp["lat"],
            "lon"     : wp["lon"],
            "alt"     : wp["alt"],
        })

    # Re-sequence to guarantee contiguous indices after building.
    for idx, item in enumerate(items):
        item["seq"] = idx

    return items


def build_mission_items(target_lat, target_lon, target_alt_m, home_lat, home_lon):
    """Build a minimal two-item MAVLink mission targeting one waypoint.

    Returns a list of dicts, each containing all fields needed to send
    either a MISSION_ITEM or MISSION_ITEM_INT message.  The caller
    (upload_mission) decides which message type to use depending on what
    PX4 requests.

    Item 0 — TAKEOFF from home position to target altitude.
    Item 1 — FLY TO target lat/lon at target altitude.
    Item 2 — LAND at target lat/lon at ground level.

    Args:
        target_lat  (float): Target latitude in decimal degrees.
        target_lon  (float): Target longitude in decimal degrees.
        target_alt_m (float): Target altitude in metres, relative to home.
        home_lat    (float): Home latitude in decimal degrees.
        home_lon    (float): Home longitude in decimal degrees.

    Returns:
        list[dict]: Mission items ready for upload_mission().

    Raises:
        InvalidMission: If coordinates or altitude are out of valid range.
    """
    if not (-90 <= target_lat <= 90):
        raise InvalidMission(f"Latitude {target_lat} out of range [-90, 90]")
    if not (-180 <= target_lon <= 180):
        raise InvalidMission(f"Longitude {target_lon} out of range [-180, 180]")
    if target_alt_m <= 0:
        raise InvalidMission(f"Altitude must be positive (got {target_alt_m}m)")

    # Both items share these fields.
    common = dict(
        frame        = _FRAME_GLOBAL_RELATIVE_ALT,
        autocontinue = 1,
        param1       = 0.0,
        param2       = 0.0,
        param3       = 0.0,
        param4       = 0.0,
    )

    return [
        # Item 0: TAKEOFF — use actual PX4 home coordinates, not 0,0.
        {
            **common,
            "seq"     : 0,
            "command" : _CMD_TAKEOFF,
            "current" : 1,          # first item to execute
            "param1"  : 0.0,        # min pitch (deg) — 0 = don't care
            "lat"     : home_lat,
            "lon"     : home_lon,
            "alt"     : target_alt_m,
        },
        # Item 1: WAYPOINT — fly to target coordinates at safe flight altitude.
        {
            **common,
            "seq"     : 1,
            "command" : _CMD_WAYPOINT,
            "current" : 0,
            "param1"  : 0.0,        # hold time (s)
            "param2"  : 2.0,        # acceptance radius (m)
            "lat"     : target_lat,
            "lon"     : target_lon,
            "alt"     : target_alt_m,
        },
        # Item 2: LAND — land at target coordinates.
        {
            **common,
            "seq"     : 2,
            "command" : _CMD_LAND,
            "current" : 0,
            "param1"  : 0.0,        # abort altitude
            "param2"  : 0.0,        # land mode
            "lat"     : target_lat,
            "lon"     : target_lon,
            "alt"     : 0.0,        # relative to home (ground level)
        },
    ]


# ---------------------------------------------------------------------------
# Upload protocol
# ---------------------------------------------------------------------------

# Messages we handle during the upload loop.
_UPLOAD_MSGS = {"MISSION_REQUEST", "MISSION_REQUEST_INT", "MISSION_ACK"}


def upload_mission(conn, items, timeout_s=None):
    """Upload a mission to PX4 using the MAVLink mission protocol.

    THIS FUNCTION CALLS conn.recv_match().  It must only be called from
    the thread that owns the pymavlink connection.

    Args:
        conn:      A live pymavlink connection (mavutil.mavlink_connection).
        items:     List of mission item dicts from build_mission_items().
        timeout_s: Total handshake timeout in seconds.  Defaults to
                   config.MISSION_UPLOAD_TIMEOUT_S.

    Returns:
        int: Number of items accepted by PX4.

    Raises:
        InvalidMission:    items is empty or malformed.
        MissionTimeout:    PX4 did not respond in time.
        MissionRejected:   PX4 sent MISSION_ACK with a failure code.
        MissionUploadError: Other protocol error.
    """
    if not items:
        raise InvalidMission("Cannot upload an empty mission.")

    if timeout_s is None:
        timeout_s = config.MISSION_UPLOAD_TIMEOUT_S

    n = len(items)
    target_system    = conn.target_system
    target_component = conn.target_component
    deadline         = time.time() + timeout_s

    # ------------------------------------------------------------------ #
    # Step 1 — clear any existing mission stored on PX4                  #
    # ------------------------------------------------------------------ #
    # PX4 may respond to MISSION_CLEAR_ALL with MISSION_ACK. We MUST
    # consume that ACK before starting the upload, otherwise the ACK can
    # be mistaken for the final ACK for MISSION_COUNT.
    conn.mav.mission_clear_all_send(target_system, target_component)

    clear_remaining = deadline - time.time()
    if clear_remaining <= 0:
        raise MissionTimeout("MISSION_CLEAR_ALL ACK", timeout_s)

    clear_ack = conn.recv_match(
        type=["MISSION_ACK"],
        blocking=True,
        timeout=min(clear_remaining, config.MISSION_ITEM_TIMEOUT_S),
    )

    if clear_ack is not None:
        clear_result = clear_ack.type
        if clear_result != mavutil.mavlink.MAV_MISSION_ACCEPTED:
            raise MissionRejected(clear_result)

    # ------------------------------------------------------------------ #
    # Step 2 — tell PX4 how many items we're about to upload             #
    # ------------------------------------------------------------------ #
    conn.mav.mission_count_send(target_system, target_component, n)

    # ------------------------------------------------------------------ #
    # Step 3 — respond to each MISSION_REQUEST / MISSION_REQUEST_INT,   #
    # then wait for MISSION_ACK                                           #
    # ------------------------------------------------------------------ #
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise MissionTimeout("MISSION_REQUEST or MISSION_ACK", timeout_s)

        msg = conn.recv_match(
            type=list(_UPLOAD_MSGS),
            blocking=True,
            timeout=min(remaining, config.MISSION_ITEM_TIMEOUT_S),
        )

        if msg is None:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise MissionTimeout("MISSION_REQUEST or MISSION_ACK", timeout_s)
            # Timed out on this iteration but overall deadline not yet reached.
            # Resend MISSION_COUNT to prod PX4 (some PX4 versions drop the first).
            conn.mav.mission_count_send(target_system, target_component, n)
            continue

        msg_type = msg.get_type()

        if msg_type in ("MISSION_REQUEST", "MISSION_REQUEST_INT"):
            seq = msg.seq
            if seq < 0 or seq >= n:
                raise MissionUploadError(
                    f"PX4 requested item {seq}, but mission only has {n} items."
                )
            _send_mission_item(conn, items[seq], msg_type == "MISSION_REQUEST_INT")

        elif msg_type == "MISSION_ACK":
            result = msg.type  # MAV_MISSION_RESULT integer
            if result == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                return n   # success
            raise MissionRejected(result)

        # Any other message type: ignore and keep waiting.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _send_mission_item(conn, item, use_int):
    """Send one mission item in response to a MISSION_REQUEST[_INT].

    Args:
        conn:     pymavlink connection (owning thread only).
        item:     dict from build_mission_items().
        use_int:  True → MISSION_ITEM_INT (lat/lon as 1e7 integers).
                  False → MISSION_ITEM (lat/lon as floats).
    """
    ts = conn.target_system
    tc = conn.target_component

    if use_int:
        # MISSION_ITEM_INT uses integer lat/lon (degrees × 1e7).
        conn.mav.mission_item_int_send(
            ts, tc,
            item["seq"],
            item["frame"],
            item["command"],
            item["current"],
            item["autocontinue"],
            item["param1"],
            item["param2"],
            item["param3"],
            item["param4"],
            int(round(item["lat"] * 1e7)),
            int(round(item["lon"] * 1e7)),
            float(item["alt"]),
        )
    else:
        # MISSION_ITEM uses floating-point lat/lon.
        conn.mav.mission_item_send(
            ts, tc,
            item["seq"],
            item["frame"],
            item["command"],
            item["current"],
            item["autocontinue"],
            item["param1"],
            item["param2"],
            item["param3"],
            item["param4"],
            float(item["lat"]),
            float(item["lon"]),
            float(item["alt"]),
        )
