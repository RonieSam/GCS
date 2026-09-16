"""
Phase 6 — connection-health state machine.

Scope check against the Phase 6 plan: this is deliberately *not* a flight
safety system (no failsafe RTL triggering, no geofence, no battery-abort
logic) — those belong to later phases once the GCS can actually command
the vehicle. All this does is answer one question honestly: is the link
to ArduPilot currently good enough to trust?

That question needs a state machine (not just a bool) so a single missed
heartbeat, a link the manager hasn't tried yet, and a link that connected
then went silent, all get reported differently.
"""

import time

DISCONNECTED = "DISCONNECTED"
CONNECTING = "CONNECTING"
CONNECTED = "CONNECTED"
HEARTBEAT_LOST = "HEARTBEAT_LOST"

_VALID_STATES = {DISCONNECTED, CONNECTING, CONNECTED, HEARTBEAT_LOST}


class SafetyStateMachine:
    """Tracks link health from HEARTBEAT timing alone.

    Transitions:
        DISCONNECTED   --connect attempt starts-->  CONNECTING
        CONNECTING     --first heartbeat received--> CONNECTED
        CONNECTING     --gave up / socket error-->   DISCONNECTED
        CONNECTED      --heartbeat_timeout_s elapses--> HEARTBEAT_LOST
        CONNECTED      --heartbeat received-->       CONNECTED (stays)
        HEARTBEAT_LOST --heartbeat received-->       CONNECTED (recovered)
        HEARTBEAT_LOST --disconnect() called-->      DISCONNECTED
        (any state)    --disconnect() called-->      DISCONNECTED
    """

    def __init__(self, heartbeat_timeout_s):
        self._state = DISCONNECTED
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._last_heartbeat = None

    @property
    def state(self):
        return self._state

    def is_connected(self):
        return self._state == CONNECTED

    def connecting(self):
        self._state = CONNECTING

    def heartbeat_received(self, at=None):
        """Call every time a HEARTBEAT message arrives. Moves CONNECTING
        or HEARTBEAT_LOST into CONNECTED; a no-op (stays CONNECTED) if
        already connected."""
        self._last_heartbeat = at if at is not None else time.time()
        self._state = CONNECTED

    def disconnect(self):
        self._state = DISCONNECTED
        self._last_heartbeat = None

    def check_timeout(self, now=None):
        """Call periodically (the manager's read loop does this on every
        pass) to detect a link that has gone silent. Only has an effect
        while CONNECTED — CONNECTING/DISCONNECTED have their own
        transitions and HEARTBEAT_LOST is already the timed-out state.
        Returns the current state after checking."""
        if self._state != CONNECTED:
            return self._state
        now = now if now is not None else time.time()
        if self._last_heartbeat is not None and (now - self._last_heartbeat) > self._heartbeat_timeout_s:
            self._state = HEARTBEAT_LOST
        return self._state
