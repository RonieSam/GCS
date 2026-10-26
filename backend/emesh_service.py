"""
E-MESH Service & Survey Integration Adapter for UAV GCS.

Manages communication with the E-MESH backend:
- Proxies SOS alerts, node telemetry, topology, and connected client sessions.
- Ingests real-time RSSI readings from mesh nodes during RF Survey sessions.
- Connects to E-MESH WebSocket for live updates.
- Maintains live connection status, stale data detection, and subscriber fan-out.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

import httpx

import config

logger = logging.getLogger("emesh_service")


class EMeshSurveyCollector:
    """Thread-safe collector for real-time E-MESH node/link RSSI telemetry."""

    def __init__(self, stale_threshold_s: float = 30.0):
        self._lock = threading.Lock()
        self._state: str = "IDLE"  # IDLE, SCANNING, STOPPED
        self._start_time: Optional[float] = None
        self._stop_time: Optional[float] = None
        self._sample_counter: int = 0
        self._samples: List[Dict[str, Any]] = []
        self._latest_readings: Dict[str, Dict[str, Any]] = {}
        self._stale_threshold_s = stale_threshold_s
        self._max_samples = 2000

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def is_active(self) -> bool:
        with self._lock:
            return self._state == "SCANNING"

    def start(self) -> Dict[str, Any]:
        """Start a new survey session. Safe against rapid/duplicate clicks."""
        with self._lock:
            if self._state == "SCANNING":
                logger.info("Survey already in SCANNING state; ignoring duplicate start.")
                return self._get_status_locked()

            now = time.time()
            self._state = "SCANNING"
            self._start_time = now
            self._stop_time = None
            logger.info("E-MESH RF Survey collector started.")
            return self._get_status_locked()

    def stop(self) -> Dict[str, Any]:
        """Stop current survey session. Freezes samples and prevents further collection."""
        with self._lock:
            if self._state != "SCANNING":
                return self._get_status_locked()

            self._state = "STOPPED"
            self._stop_time = time.time()
            logger.info(f"E-MESH RF Survey collector stopped with {len(self._samples)} samples.")
            return self._get_status_locked()

    def reset(self) -> Dict[str, Any]:
        """Reset survey collector to IDLE and clear accumulated samples."""
        with self._lock:
            self._state = "IDLE"
            self._start_time = None
            self._stop_time = None
            self._sample_counter = 0
            self._samples.clear()
            self._latest_readings.clear()
            logger.info("E-MESH RF Survey collector reset to IDLE.")
            return self._get_status_locked()

    def record_reading(
        self,
        node_id: str,
        rssi_dbm: Optional[float],
        parent_id: Optional[str] = None,
        link_id: Optional[str] = None,
        link_quality: Optional[float] = None,
        measurement_time: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record an RSSI measurement if survey is currently SCANNING."""
        if rssi_dbm is None:
            return None

        with self._lock:
            if self._state != "SCANNING":
                return None

            now = time.time()
            ts = measurement_time if measurement_time is not None else now
            self._sample_counter += 1

            reading_key = f"{node_id}->{parent_id}" if parent_id else node_id
            reading = {
                "sample_id": self._sample_counter,
                "timestamp": ts,
                "timestamp_iso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "node_id": node_id,
                "parent_id": parent_id,
                "link_id": link_id,
                "rssi_dbm": round(float(rssi_dbm), 1),
                "link_quality": round(float(link_quality), 1) if link_quality is not None else None,
                "reading_key": reading_key,
                "received_at": now,
            }

            self._latest_readings[reading_key] = reading
            self._samples.append(reading)

            # Cap samples list size
            if len(self._samples) > self._max_samples:
                self._samples.pop(0)

            return reading

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return self._get_status_locked()

    def _get_status_locked(self) -> Dict[str, Any]:
        now = time.time()
        elapsed_s = 0.0
        if self._start_time:
            end = self._stop_time if self._stop_time else now
            elapsed_s = max(0.0, end - self._start_time)

        # Mark freshness for latest readings
        readings_with_freshness = {}
        for k, v in self._latest_readings.items():
            age_s = now - v["timestamp"]
            is_stale = age_s > self._stale_threshold_s
            reading_copy = dict(v)
            reading_copy["age_s"] = round(age_s, 1)
            reading_copy["is_stale"] = is_stale
            readings_with_freshness[k] = reading_copy

        return {
            "state": self._state,
            "is_active": self._state == "SCANNING",
            "start_time": self._start_time,
            "stop_time": self._stop_time,
            "elapsed_seconds": round(elapsed_s, 1),
            "sample_count": len(self._samples),
            "total_samples_recorded": self._sample_counter,
            "node_count": len(readings_with_freshness),
            "latest_readings": readings_with_freshness,
        }

    def get_samples(self) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._samples)


class EMeshService:
    """Coordinates API proxying, survey telemetry collection, and WebSocket event fan-out."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        ws_url: Optional[str] = None,
        poll_interval_s: Optional[float] = None,
        stale_threshold_s: Optional[float] = None,
    ):
        self.base_url = (base_url or getattr(config, "EMESH_SERVER_URL", "http://127.0.0.1:8001")).rstrip("/")
        self.ws_url = ws_url or getattr(config, "EMESH_WS_URL", "ws://127.0.0.1:8001/api/v1/ws")
        self.poll_interval_s = poll_interval_s or getattr(config, "EMESH_POLL_INTERVAL_S", 2.0)
        self.stale_threshold_s = stale_threshold_s or getattr(config, "EMESH_STALE_THRESHOLD_S", 30.0)

        self.survey_collector = EMeshSurveyCollector(stale_threshold_s=self.stale_threshold_s)

        # Connection health
        self._is_connected = False
        self._last_checked_at: Optional[float] = None
        self._last_successful_at: Optional[float] = None
        self._last_error: Optional[str] = None

        # Cached states
        self._cached_nodes: List[Dict[str, Any]] = []
        self._cached_topology: Dict[str, Any] = {"nodes": [], "links": []}
        self._cached_clients: List[Dict[str, Any]] = []
        self._cached_sos: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

        # Background polling & WS loop threads
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._ws_thread: Optional[threading.Thread] = None

        # WebSocket subscribers (async queues or callbacks)
        self._subscribers: Set[asyncio.Queue] = set()
        self._subscribers_lock = threading.Lock()

    def start(self):
        """Start background polling and WebSocket monitoring threads."""
        if self._running:
            return
        self._running = True

        self._poll_thread = threading.Thread(target=self._poll_worker, name="EMeshPollWorker", daemon=True)
        self._poll_thread.start()

        self._ws_thread = threading.Thread(target=self._ws_worker, name="EMeshWSWorker", daemon=True)
        self._ws_thread.start()
        logger.info(f"EMeshService started targeting {self.base_url}")

    def stop(self):
        """Stop background workers."""
        self._running = False
        self.survey_collector.stop()

    def get_status(self) -> Dict[str, Any]:
        """Return connectivity, counts, and survey status."""
        with self._lock:
            connected = self._is_connected
            last_err = self._last_error
            last_success = self._last_successful_at
            node_cnt = len(self._cached_nodes)
            client_cnt = len(self._cached_clients)
            active_sos = sum(1 for s in self._cached_sos if str(s.get("status", "")).upper() == "ACTIVE")
            total_sos = len(self._cached_sos)

        survey_st = self.survey_collector.get_status()

        return {
            "connected": connected,
            "base_url": self.base_url,
            "ws_url": self.ws_url,
            "last_successful_iso": datetime.fromtimestamp(last_success, tz=timezone.utc).isoformat() if last_success else None,
            "last_error": last_err,
            "active_sos_count": active_sos,
            "total_sos_count": total_sos,
            "node_count": node_cnt,
            "client_count": client_cnt,
            "survey": survey_st,
        }

    # -------------------------------------------------------------------------
    # REST API Proxy Methods
    # -------------------------------------------------------------------------

    def fetch_nodes(self) -> List[Dict[str, Any]]:
        """Fetch nodes from E-MESH /api/v1/nodes."""
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.get(f"{self.base_url}/api/v1/nodes?page=1&page_size=200")
                if res.status_code == 200:
                    data = res.json()
                    nodes = data.get("data", [])
                    self._record_success()
                    with self._lock:
                        self._cached_nodes = nodes
                    # Ingest RSSI if survey active
                    self._ingest_nodes_rssi(nodes)
                    return nodes
                else:
                    self._record_error(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            self._record_error(str(e))
        with self._lock:
            return list(self._cached_nodes)

    def fetch_topology(self) -> Dict[str, Any]:
        """Fetch full mesh topology (nodes + links)."""
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.get(f"{self.base_url}/api/v1/nodes/topology")
                if res.status_code == 200:
                    data = res.json()
                    self._record_success()
                    with self._lock:
                        self._cached_topology = data
                    # Ingest link RSSI if survey active
                    links = data.get("links", [])
                    self._ingest_links_rssi(links)
                    return data
                else:
                    self._record_error(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            self._record_error(str(e))
        with self._lock:
            return dict(self._cached_topology)

    def fetch_clients(self) -> List[Dict[str, Any]]:
        """Fetch connected users/devices from /api/v1/location/users."""
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.get(f"{self.base_url}/api/v1/location/users?active_within_minutes=60")
                if res.status_code == 200:
                    data = res.json()
                    clients = data if isinstance(data, list) else data.get("data", [])
                    self._record_success()
                    with self._lock:
                        self._cached_clients = clients
                    return clients
                else:
                    self._record_error(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            self._record_error(str(e))
        with self._lock:
            return list(self._cached_clients)

    def fetch_sos(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch SOS alerts from /api/v1/sos."""
        url = f"{self.base_url}/api/v1/sos"
        if status:
            url += f"?status={status.upper()}"
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    sos_list = data if isinstance(data, list) else data.get("data", [])
                    self._record_success()
                    with self._lock:
                        self._cached_sos = sos_list
                    return sos_list
                else:
                    self._record_error(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            self._record_error(str(e))
        with self._lock:
            return list(self._cached_sos)

    def update_sos_status(
        self,
        sos_id: Union[int, str],
        new_status: Optional[str] = None,
        notes: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update SOS status (ACKNOWLEDGED, RESOLVED, CANCELLED) or coordinates on E-MESH server."""
        url = f"{self.base_url}/api/v1/sos/{sos_id}"
        payload: Dict[str, Any] = {}
        if new_status:
            st = new_status.upper()
            if st == "DISMISSED":
                st = "CANCELLED"
            payload["status"] = st
        if notes:
            payload["notes"] = notes
        if latitude is not None:
            payload["latitude"] = float(latitude)
        if longitude is not None:
            payload["longitude"] = float(longitude)
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.patch(url, json=payload)
                if res.status_code in (200, 201):
                    updated = res.json()
                    self._record_success()
                    # Refresh cached SOS list
                    self.fetch_sos()
                    # Broadcast to GCS subscribers
                    self.broadcast_event({
                        "event": "sos.updated",
                        "data": updated,
                    })
                    return updated
                else:
                    raise RuntimeError(f"E-MESH update failed ({res.status_code}): {res.text}")
        except Exception as e:
            self._record_error(str(e))
            raise

    # -------------------------------------------------------------------------
    # RF Survey Operations
    # -------------------------------------------------------------------------

    def start_rf_survey(self) -> Dict[str, Any]:
        """Start real-time RSSI collection from E-MESH nodes."""
        status = self.survey_collector.start()
        # Immediately perform an initial poll of nodes and topology
        self.fetch_nodes()
        self.fetch_topology()
        self.broadcast_event({
            "event": "survey.state_changed",
            "data": self.survey_collector.get_status(),
        })
        return status

    def stop_rf_survey(self) -> Dict[str, Any]:
        """Stop real-time RSSI collection."""
        status = self.survey_collector.stop()
        self.broadcast_event({
            "event": "survey.state_changed",
            "data": status,
        })
        return status

    def reset_rf_survey(self) -> Dict[str, Any]:
        """Reset survey data to IDLE."""
        status = self.survey_collector.reset()
        self.broadcast_event({
            "event": "survey.state_changed",
            "data": status,
        })
        return status

    def get_survey_status(self) -> Dict[str, Any]:
        return self.survey_collector.get_status()

    def get_survey_samples(self) -> List[Dict[str, Any]]:
        return self.survey_collector.get_samples()

    # -------------------------------------------------------------------------
    # Internal Ingestion & Background Polling
    # -------------------------------------------------------------------------

    def _ingest_nodes_rssi(self, nodes: List[Dict[str, Any]]):
        if not self.survey_collector.is_active():
            return
        for n in nodes:
            node_id = str(n.get("node_id") or n.get("id"))
            rssi = n.get("rssi_dbm")
            if rssi is not None:
                reading = self.survey_collector.record_reading(
                    node_id=node_id,
                    rssi_dbm=rssi,
                    measurement_time=time.time(),
                )
                if reading:
                    self.broadcast_event({
                        "event": "survey.reading",
                        "data": reading,
                    })

    def _ingest_links_rssi(self, links: List[Dict[str, Any]]):
        if not self.survey_collector.is_active():
            return
        for lk in links:
            from_node = str(lk.get("from_node_id") or lk.get("from_node") or "")
            to_node = str(lk.get("to_node_id") or lk.get("to_node") or "")
            rssi = lk.get("rssi_dbm")
            lq = lk.get("link_quality_pct")
            link_id = str(lk.get("id") or f"{from_node}-{to_node}")
            if rssi is not None and from_node:
                reading = self.survey_collector.record_reading(
                    node_id=from_node,
                    parent_id=to_node or None,
                    link_id=link_id,
                    rssi_dbm=rssi,
                    link_quality=lq,
                    measurement_time=time.time(),
                )
                if reading:
                    self.broadcast_event({
                        "event": "survey.reading",
                        "data": reading,
                    })

    def _record_success(self):
        with self._lock:
            self._is_connected = True
            self._last_successful_at = time.time()
            self._last_error = None

    def _record_error(self, err_msg: str):
        with self._lock:
            self._is_connected = False
            self._last_error = err_msg

    def _poll_worker(self):
        """Periodic background poll for health, nodes, clients, and SOS alerts."""
        while self._running:
            try:
                self.fetch_nodes()
                self.fetch_topology()
                self.fetch_clients()
                self.fetch_sos()
            except Exception as e:
                logger.debug(f"Poll cycle error: {e}")

            time.sleep(self.poll_interval_s)

    def _ws_worker(self):
        """Background thread running an asyncio event loop for the E-MESH WebSocket connection."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_loop())
        finally:
            loop.close()

    async def _ws_loop(self):
        """Maintains persistent WebSocket connection to E-MESH backend."""
        import websockets

        while self._running:
            try:
                ws_target = self.ws_url
                if "client_type=" not in ws_target:
                    sep = "&" if "?" in ws_target else "?"
                    ws_target = f"{ws_target}{sep}client_type=gcs"

                logger.info(f"Connecting to E-MESH WebSocket at {ws_target}...")
                async with websockets.connect(ws_target, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Connected to E-MESH WebSocket.")
                    self._record_success()

                    while self._running:
                        msg = await ws.recv()
                        try:
                            payload = json.loads(msg)
                            self._handle_incoming_ws_event(payload)
                        except Exception as parse_err:
                            logger.debug(f"WS parse error: {parse_err}")

            except Exception as e:
                logger.warning(f"E-MESH WS connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    def _handle_incoming_ws_event(self, payload: Dict[str, Any]):
        """Process event received from E-MESH WS and fan-out to GCS clients."""
        event_name = payload.get("event") or payload.get("type")
        data = payload.get("data", payload)

        # Update cached SOS state
        if event_name == "sos.created":
            with self._lock:
                sid = data.get("id") or data.get("sos_id")
                exists = any(s.get("id") == sid or s.get("sos_id") == sid for s in self._cached_sos)
                if not exists:
                    self._cached_sos.insert(0, data)
        elif event_name in ("sos.updated", "incident.updated"):
            sid = data.get("id") or data.get("sos_id")
            with self._lock:
                found = False
                for idx, s in enumerate(self._cached_sos):
                    if (s.get("id") and s.get("id") == sid) or (s.get("sos_id") and s.get("sos_id") == sid):
                        self._cached_sos[idx] = {**s, **data}
                        found = True
                        break
                if not found and sid:
                    self._cached_sos.insert(0, data)

        # Update cached citizen clients state
        elif event_name == "user.location_updated":
            cid = data.get("client_id") or data.get("user_id")
            if cid:
                with self._lock:
                    found = False
                    for idx, c in enumerate(self._cached_clients):
                        if c.get("client_id") == cid or c.get("user_id") == cid:
                            self._cached_clients[idx] = {**c, **data}
                            found = True
                            break
                    if not found:
                        self._cached_clients.insert(0, data)

        # Ingest RSSI if this is a node telemetry event during survey
        if event_name in ("node.updated", "node.online", "mesh.telemetry") and self.survey_collector.is_active():
            node_id = str(data.get("node_id") or data.get("id"))
            sig = data.get("signal_quality") or data.get("rssi_dbm")
            if sig is not None and node_id:
                reading = self.survey_collector.record_reading(
                    node_id=node_id,
                    rssi_dbm=sig,
                    measurement_time=time.time(),
                )
                if reading:
                    self.broadcast_event({
                        "event": "survey.reading",
                        "data": reading,
                    })

        # Broadcast event directly to connected GCS frontend clients
        self.broadcast_event({
            "event": event_name,
            "data": data,
            "timestamp": time.time(),
        })

    # -------------------------------------------------------------------------
    # GCS WebSocket Fan-out Subscriptions
    # -------------------------------------------------------------------------

    def register_subscriber(self, q: asyncio.Queue):
        with self._subscribers_lock:
            self._subscribers.add(q)

    def unregister_subscriber(self, q: asyncio.Queue):
        with self._subscribers_lock:
            self._subscribers.discard(q)

    def broadcast_event(self, event_dict: Dict[str, Any]):
        """Broadcast event to all connected GCS WebSockets (thread-safe)."""
        with self._subscribers_lock:
            dead_queues = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event_dict)
                except Exception:
                    dead_queues.append(q)
            for dq in dead_queues:
                self._subscribers.discard(dq)


# Global singleton instance
_emesh_service: Optional[EMeshService] = None


def get_emesh_service() -> EMeshService:
    global _emesh_service
    if _emesh_service is None:
        _emesh_service = EMeshService()
        _emesh_service.start()
    return _emesh_service
