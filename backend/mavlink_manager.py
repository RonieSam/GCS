"""
Phase 6 — MAVLink connection manager.

Maintains the MAVLink connection, receives telemetry, and executes
vehicle commands from the FastAPI backend.
"""

import queue
import threading
import time

from pymavlink import mavutil

import mavlink_commands
import mavlink_mission
import mavlink_telemetry
from safety_manager import SafetyStateMachine
import coordinate_mapper as _coord_mapper  # Phase 9A — simulation coordinate sync


_POLL_INTERVAL_S = 0.1

# Phase 9A — track whether we have already snapped the PX4 reference from a
# HOME_POSITION message.  GLOBAL_POSITION_INT is used as an early fallback only
# until HOME_POSITION arrives, after which we stop updating from position fixes.
_px4_reference_set_from_home = False


def _self_update_px4_reference(msg, state):
    """Update the coordinate mapper's PX4 reference from live MAVLink messages.

    Called from _drain_incoming() while the manager lock is held.  Must not
    perform any I/O or blocking operations.

    Priority:
      1. HOME_POSITION — most authoritative; once seen we stop overriding.
      2. First GLOBAL_POSITION_INT with a valid fix — early-arrival fallback
         (SITL emits these before HOME_POSITION on first boot).

    Args:
        msg:   The incoming MAVLink message (already processed by
               mavlink_telemetry.update_from_message).
        state: The current vehicle state dict (used to check GPS validity).
    """
    import config as _config
    if not _config.SIMULATION_MODE:
        return

    global _px4_reference_set_from_home
    msg_type = msg.get_type()

    if msg_type == "HOME_POSITION":
        # lat/lon are integers in 1e7 degrees.
        lat = msg.latitude  / 1e7
        lon = msg.longitude / 1e7
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            _coord_mapper.get_mapper().update_px4_reference(lat, lon)
            _px4_reference_set_from_home = True

    elif msg_type == "GLOBAL_POSITION_INT" and not _px4_reference_set_from_home:
        # Use the first valid GPS fix as a temporary reference until
        # HOME_POSITION arrives.
        lat = state.get("latitude")
        lon = state.get("longitude")
        if lat is not None and lon is not None:
            _coord_mapper.get_mapper().update_px4_reference(lat, lon)



class MAVLinkManager:

    def __init__(
        self,
        connection_string,
        connect_timeout_s=10,
        heartbeat_lost_s=5,
        reconnect_interval_s=3,
        stream_rate_hz=4,
    ):
        self.connection_string = connection_string
        self._connect_timeout_s = connect_timeout_s
        self._heartbeat_lost_s = heartbeat_lost_s
        self._reconnect_interval_s = reconnect_interval_s
        self._stream_rate_hz = stream_rate_hz

        self._conn = None
        self._safety = SafetyStateMachine(heartbeat_lost_s)
        self._state = mavlink_telemetry.new_vehicle_state()
        self._lock = threading.Lock()

        # Commands that require waiting for a MAVLink response are executed
        # by the same thread that owns and reads the MAVLink connection.
        self._command_queue = queue.Queue()

        # Phase 8 — mission upload state, protected by _lock.
        # status values: NOT_GENERATED | GENERATED | UPLOADING | UPLOADED | FAILED
        self._mission_upload_state = {
            "status": "NOT_GENERATED",
            "mission_id": None,
            "items": 0,
            "error": None,
        }

        self._thread = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_background(self):
        """Start the background connection/read thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
        )
        self._thread.start()

    def stop_background(self):
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=2)

        self.disconnect()

    def connect(self):
        """Perform one synchronous connection attempt."""
        self._attempt_connect()
        return self._conn is not None

    def disconnect(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass

        self._conn = None

        with self._lock:
            self._safety.disconnect()
            self._state = mavlink_telemetry.new_vehicle_state()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_connected(self):
        return self._safety.is_connected()

    @property
    def link_state(self):
        return self._safety.state

    def wait_heartbeat(self, timeout=None):
        if self._conn is None:
            return None

        return self._conn.wait_heartbeat(
            timeout=(
                timeout
                if timeout is not None
                else self._connect_timeout_s
            )
        )

    def get_vehicle_state(self):
        with self._lock:
            return dict(self._state)

    def get_mission_upload_state(self):
        """Return a copy of the current mission upload state.

        Thread-safe snapshot; does not touch the MAVLink connection.
        """
        with self._lock:
            return dict(self._mission_upload_state)

    def set_mission_upload_state(self, **kwargs):
        """Update specific fields in the mission upload state.

        Intended for use by main.py before queuing an upload so the UI
        can show UPLOADING before the background thread starts.
        """
        with self._lock:
            self._mission_upload_state.update(kwargs)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def send_command(self, name, **kwargs):
        """
        Send a vehicle command.

        Commands that require an ACK are executed through the command
        queue so only the MAVLink connection-owning thread reads ACKs.
        """

        if self._conn is None or not self.is_connected():
            raise RuntimeError(
                "Cannot send command: no active MAVLink connection."
            )

        if name == "arm":
            mavlink_commands.arm(self._conn)
            return {"success": True, "command": "arm"}

        elif name == "disarm":
            mavlink_commands.disarm(self._conn)
            return {"success": True, "command": "disarm"}

        elif name == "set_mode":
            return self._send_set_mode_and_wait(
                kwargs["mode"]
            )

        elif name == "upload_mission":
            return self._send_upload_mission_and_wait(
                kwargs["items"],
                mission_id=kwargs.get("mission_id"),
                timeout_s=kwargs.get("timeout_s"),
            )

        else:
            raise ValueError(f"Unknown command {name!r}")

    def _send_set_mode_and_wait(self, mode_name, timeout_s=3):
        """
        Queue a mode-change request and wait for PX4's COMMAND_ACK.
        """

        result_box = {}
        done = threading.Event()

        self._command_queue.put(
            (
                "set_mode",
                {
                    "mode": mode_name,
                    "timeout_s": timeout_s,
                },
                result_box,
                done,
            )
        )

        if not done.wait(timeout_s + 1):
            raise mavlink_commands.CommandTimeout(
                f"set_mode({mode_name})",
                timeout_s,
            )

        if "error" in result_box:
            raise result_box["error"]

        return result_box["result"]

    def _send_upload_mission_and_wait(self, items, mission_id=None, timeout_s=None):
        """
        Queue a mission upload and block until PX4 confirms or times out.

        Args:
            items      : list of mission item dicts from mavlink_mission.build_mission_items()
            mission_id : optional SQLite mission id for state tracking
            timeout_s  : forwarded to mavlink_mission.upload_mission()

        Returns:
            dict with {"items": n} on success.

        Raises:
            mavlink_mission.MissionTimeout
            mavlink_mission.MissionRejected
            mavlink_mission.MissionUploadError
        """
        import config as _config
        wait_timeout = (timeout_s or _config.MISSION_UPLOAD_TIMEOUT_S) + 2

        result_box = {}
        done = threading.Event()

        self._command_queue.put(
            (
                "upload_mission",
                {
                    "items": items,
                    "mission_id": mission_id,
                    "timeout_s": timeout_s,
                },
                result_box,
                done,
            )
        )

        if not done.wait(wait_timeout):
            raise mavlink_mission.MissionTimeout(
                "MISSION upload (queue processing)",
                wait_timeout,
            )

        if "error" in result_box:
            raise result_box["error"]

        return result_box["result"]

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run_loop(self):
        while not self._stop_event.is_set():

            if self._conn is None:
                self._attempt_connect()

                if self._conn is None:
                    self._stop_event.wait(
                        self._reconnect_interval_s
                    )
                    continue

            self._process_command_queue()
            self._drain_incoming()

            with self._lock:
                self._safety.check_timeout()
                self._state["connected"] = (
                    self._safety.is_connected()
                )

            self._stop_event.wait(_POLL_INTERVAL_S)

    def _process_command_queue(self):
        """
        Execute queued commands on the MAVLink connection-owning thread.
        """

        while True:
            try:
                (
                    name,
                    kwargs,
                    result_box,
                    done,
                ) = self._command_queue.get_nowait()

            except queue.Empty:
                return

            try:
                if self._conn is None:
                    raise RuntimeError(
                        "Cannot send command: no active MAVLink connection."
                    )

                if name == "set_mode":
                    result_box["result"] = (
                        mavlink_commands.set_mode(
                            self._conn,
                            kwargs["mode"],
                            timeout_s=kwargs.get(
                                "timeout_s",
                                3,
                            ),
                        )
                    )

                elif name == "upload_mission":
                    # Update state to UPLOADING so the API can reflect this
                    # while the blocking upload_mission() call is in flight.
                    mid = kwargs.get("mission_id")
                    with self._lock:
                        self._mission_upload_state.update(
                            status="UPLOADING",
                            mission_id=mid,
                            items=0,
                            error=None,
                        )

                    n = mavlink_mission.upload_mission(
                        self._conn,
                        kwargs["items"],
                        timeout_s=kwargs.get("timeout_s"),
                    )

                    with self._lock:
                        self._mission_upload_state.update(
                            status="UPLOADED",
                            items=n,
                            error=None,
                        )

                    result_box["result"] = {"items": n}

                else:
                    raise ValueError(
                        f"Unknown queued command {name!r}"
                    )

            except Exception as e:
                # Capture upload failures into upload state as well as result_box.
                if name == "upload_mission":
                    with self._lock:
                        self._mission_upload_state.update(
                            status="FAILED",
                            error=str(e),
                        )
                result_box["error"] = e

            finally:
                done.set()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _attempt_connect(self):
        with self._lock:
            self._safety.connecting()

        try:
            conn = mavutil.mavlink_connection(
                self.connection_string
            )

        except Exception:
            with self._lock:
                self._safety.disconnect()

            self._conn = None
            return

        heartbeat = self._wait_heartbeat_interruptible(
            conn,
            self._connect_timeout_s,
        )

        if heartbeat is None:
            try:
                conn.close()
            except Exception:
                pass

            with self._lock:
                self._safety.disconnect()

            self._conn = None
            return

        with self._lock:
            mavlink_telemetry.update_from_message(
                self._state,
                heartbeat,
                conn,
            )
            self._safety.heartbeat_received()
            self._state["connected"] = True

        try:
            mavlink_commands.request_data_streams(
                conn,
                self._stream_rate_hz,
            )
        except Exception:
            pass

        self._conn = conn

    def _wait_heartbeat_interruptible(
        self,
        conn,
        timeout_s,
        step_s=1.0,
    ):
        deadline = time.time() + timeout_s

        while time.time() < deadline:

            if self._stop_event.is_set():
                return None

            msg = conn.recv_match(
                type="HEARTBEAT",
                blocking=True,
                timeout=step_s,
            )

            if msg is not None:
                return msg

        return None

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _drain_incoming(self):
        """
        Process every MAVLink message currently buffered.
        """

        while True:
            try:
                msg = self._conn.recv_match(
                    blocking=False
                )

            except Exception:
                self._conn = None

                with self._lock:
                    self._safety.disconnect()

                return

            if msg is None:
                return

            if msg.get_type() == "BAD_DATA":
                continue

            with self._lock:
                mavlink_telemetry.update_from_message(
                    self._state,
                    msg,
                    self._conn,
                )

                if msg.get_type() == "HEARTBEAT":
                    self._safety.heartbeat_received()

                # Phase 9A — keep the PX4 reference coordinate up-to-date
                # so the coordinate mapper reflects the vehicle's actual home
                # rather than the static fallback in config.py.
                #
                # HOME_POSITION is the authoritative PX4 home (set once on
                # arming / SITL startup). GLOBAL_POSITION_INT on the very first
                # valid fix is used as an early-arrival fallback in case
                # HOME_POSITION arrives late or is delayed by SITL startup.
                _self_update_px4_reference(msg, self._state)
