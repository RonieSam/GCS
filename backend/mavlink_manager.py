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
import mavlink_telemetry
from safety_manager import SafetyStateMachine


_POLL_INTERVAL_S = 0.1


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
                else:
                    raise ValueError(
                        f"Unknown queued command {name!r}"
                    )

            except Exception as e:
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
