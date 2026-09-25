"""
Phase 7 — WebSocket telemetry fan-out.

Fans the MAVLinkManager's live vehicle state out to any number of
connected /ws/telemetry clients on a fixed timer.

CRITICAL: this module never touches pymavlink or the MAVLink connection
itself. MAVLinkManager (mavlink_manager.py) remains the sole reader of
the socket; this module only calls its already thread-safe snapshot
method, get_vehicle_state(), from the asyncio event loop. That keeps
"exactly one reader of the pymavlink connection" true regardless of how
many WebSocket clients are attached.

Phase 3: The broadcast loop also feeds the raw vehicle state into the
RF survey collector (rf_collector.ingest_telemetry) on every tick.  The
collector decides internally whether to record a sample based on its own
state machine (SCANNING vs anything else). No state checking is needed
here — the collector is entirely self-governing.
"""

import asyncio
import time

from models import TelemetryMessage, VehicleStateOut


class TelemetryBroadcaster:
    def __init__(self, mav_manager, rate_hz):
        self._mav_manager = mav_manager
        # Guard against a misconfigured/zero rate rather than dividing by
        # zero — fall back to a sensible default inside the 4-10Hz range.
        self.interval_s = 1.0 / rate_hz if rate_hz and rate_hz > 0 else 0.2

        self._clients = set()
        self._clients_lock = asyncio.Lock()
        self._task = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    # ------------------------------------------------------------------
    # Client registration
    # ------------------------------------------------------------------

    async def register(self, websocket):
        async with self._clients_lock:
            self._clients.add(websocket)

    async def unregister(self, websocket):
        async with self._clients_lock:
            self._clients.discard(websocket)

    # ------------------------------------------------------------------
    # Message construction
    # ------------------------------------------------------------------

    def build_message(self):
        """Snapshot the current vehicle state into one telemetry message.

        Safe to call from the WebSocket handler for the initial push as
        well as from the broadcast loop — get_vehicle_state() just takes
        a lock and copies a dict, no MAVLink I/O.

        Phase 9A: when SIMULATION_MODE is True, the raw PX4 lat/lon in the
        vehicle state are transformed back into GCS coordinates before being
        sent to the frontend.  The GCS map therefore always operates in its
        own coordinate space, and the UAV marker tracks movements correctly
        regardless of which geographic region PX4/Gazebo is running in.
        """
        import config
        import coordinate_mapper

        state = self._mav_manager.get_vehicle_state()

        # Phase 9A — remap PX4 telemetry coordinates → GCS coordinates so the
        # UAV marker on the Leaflet map moves in the correct relative position.
        if (
            config.SIMULATION_MODE
            and state.get("latitude") is not None
            and state.get("longitude") is not None
        ):
            gcs_lat, gcs_lon = coordinate_mapper.get_mapper().px4_to_gcs(
                state["latitude"],
                state["longitude"],
            )
            # Build a shallow copy so we don't mutate the shared state dict.
            state = dict(state)
            state["latitude"]  = gcs_lat
            state["longitude"] = gcs_lon

        message = TelemetryMessage(
            timestamp=time.time(),
            vehicle=VehicleStateOut(**state),
        )
        return message.model_dump()


    # ------------------------------------------------------------------
    # Broadcast loop
    # ------------------------------------------------------------------

    async def _run(self):
        while True:
            await asyncio.sleep(self.interval_s)

            # Phase 3 — feed the raw vehicle state into the RF survey
            # collector on every broadcast tick, regardless of whether any
            # GCS WebSocket clients are currently connected.  The collector's
            # own state machine decides whether to accumulate a sample.
            # We always use run_in_executor because ingest_telemetry() holds
            # a threading.Lock and computes RSSI — both would block the event loop.
            try:
                raw_state = self._mav_manager.get_vehicle_state()
                if raw_state.get("latitude") is not None:
                    import asyncio as _asyncio
                    from rf_collector import get_rf_collector as _get_rf_collector
                    loop = _asyncio.get_event_loop()
                    collector = _get_rf_collector()
                    await loop.run_in_executor(
                        None, collector.ingest_telemetry, raw_state
                    )
            except Exception as _e:
                import logging as _logging
                _logging.getLogger("telemetry_broadcaster").debug(
                    f"RF collector ingest error (non-fatal): {_e}"
                )

            async with self._clients_lock:
                clients = list(self._clients)

            if not clients:
                # No clients connected — nothing to send, but the loop
                # (and the MAVLinkManager thread it reads from) keeps
                # running normally.
                continue

            payload = self.build_message()

            dead = []
            for websocket in clients:
                try:
                    await websocket.send_json(payload)
                except Exception:
                    # One client's dropped/broken socket must not affect
                    # delivery to the others.
                    dead.append(websocket)

            if dead:
                async with self._clients_lock:
                    for websocket in dead:
                        self._clients.discard(websocket)
