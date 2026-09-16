"""
Phase 6 — basic vehicle commands.
...
"""

import time

from pymavlink import mavutil

_ACK_TIMEOUT_S = 3


class CommandRejected(Exception):
    """PX4 explicitly NACKed the command (COMMAND_ACK.result != MAV_RESULT_ACCEPTED)."""
    def __init__(self, command_name, result_code):
        self.command_name = command_name
        self.result_code = result_code
        self.result_name = result_name(result_code)
        super().__init__(
            f"{command_name} rejected by PX4: {self.result_name} ({result_code})"
        )


class CommandTimeout(Exception):
    """No COMMAND_ACK arrived for the command within the timeout."""
    def __init__(self, command_name, timeout_s=_ACK_TIMEOUT_S):
        self.command_name = command_name
        super().__init__(
            f"No COMMAND_ACK received for {command_name} within {timeout_s}s "
            "(PX4 may not be running, or may be ignoring the command)"
        )


def result_name(result_code):
    """MAV_RESULT int -> readable name, e.g. 4 -> 'MAV_RESULT_DENIED'."""
    entry = mavutil.mavlink.enums.get("MAV_RESULT", {}).get(result_code)
    return entry.name if entry else f"MAV_RESULT_UNKNOWN({result_code})"


def request_data_streams(mav_connection, rate_hz):
    mav_connection.mav.request_data_stream_send(
        mav_connection.target_system,
        mav_connection.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL,
        rate_hz,
        1,
    )


def arm(mav_connection, timeout_s=_ACK_TIMEOUT_S):
    _send_arm_disarm_and_wait(mav_connection, True, timeout_s)


def disarm(mav_connection, timeout_s=_ACK_TIMEOUT_S):
    _send_arm_disarm_and_wait(mav_connection, False, timeout_s)


def _send_arm_disarm_and_wait(mav_connection, arm, timeout_s):
    cmd = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
    action_name = "arm" if arm else "disarm"
    mav_connection.mav.command_long_send(
        mav_connection.target_system,
        mav_connection.target_component,
        cmd,
        0,
        1 if arm else 0,
        0, 0, 0, 0, 0, 0,
    )

    deadline = time.time() + timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise CommandTimeout(f"{action_name}", timeout_s)
        msg = mav_connection.recv_match(
            type="COMMAND_ACK", blocking=True, timeout=remaining
        )
        if msg is None:
            raise CommandTimeout(f"{action_name}", timeout_s)
        if msg.command != cmd:
            continue

        if msg.result != mavutil.mavlink.MAV_RESULT_ACCEPTED:
            raise CommandRejected(f"{action_name}", msg.result)
        return msg


def set_mode(mav_connection, mode_name, timeout_s=_ACK_TIMEOUT_S):
    """Switch PX4 flight mode and confirm PX4 actually accepted it.

    PX4's mode_mapping() returns (base_mode, px4_main_mode, px4_sub_mode)
    tuples — not a single custom_mode int like ArduPilot's mapping. We
    send those three values via COMMAND_LONG/MAV_CMD_DO_SET_MODE (common.xml,
    present in every dialect, no need for the PX4-only
    MAV_CMD_DO_SET_STANDARD_MODE that this pymavlink build lacks) because
    that command path is acknowledged with a COMMAND_ACK. The older
    SET_MODE message (id 11) is fire-and-forget and can never tell you
    whether PX4 accepted the change — which is exactly how the bug
    presented.

    IMPORTANT: this function calls recv_match() on mav_connection. It
    must only ever be invoked from the single thread that owns that
    connection (see mavlink_manager._process_command_queue) — never from
    a request-handling thread directly, or it will race the background
    telemetry reader for incoming packets.
    """
    mode_name = mode_name.upper()

    mapping = mav_connection.mode_mapping()
    if not mapping or mode_name not in mapping:
        known = sorted(mapping) if mapping else []
        raise ValueError(f"Unknown mode {mode_name!r}. Known modes: {known}")

    entry = mapping[mode_name]
    if not (isinstance(entry, tuple) and len(entry) == 3):
        raise RuntimeError(
            f"mode_mapping()[{mode_name!r}] = {entry!r}, expected a PX4 "
            "(base_mode, main_mode, sub_mode) 3-tuple. This connection may "
            "not actually be talking to PX4."
        )
    base_mode, px4_main_mode, px4_sub_mode = entry

    mav_connection.mav.command_long_send(
        mav_connection.target_system,
        mav_connection.target_component,
        mavutil.mavlink.MAV_CMD_DO_SET_MODE,
        0,  # confirmation
        base_mode,
        px4_main_mode,
        px4_sub_mode,
        0, 0, 0, 0,
    )

    deadline = time.time() + timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise CommandTimeout(f"set_mode({mode_name})", timeout_s)
        msg = mav_connection.recv_match(
            type="COMMAND_ACK", blocking=True, timeout=remaining
        )
        if msg is None:
            raise CommandTimeout(f"set_mode({mode_name})", timeout_s)
        if msg.command != mavutil.mavlink.MAV_CMD_DO_SET_MODE:
            continue  # an ACK for some other in-flight command; keep waiting

        if msg.result != mavutil.mavlink.MAV_RESULT_ACCEPTED:
            raise CommandRejected(f"set_mode({mode_name})", msg.result)
        return msg  # the accepted COMMAND_ACK
