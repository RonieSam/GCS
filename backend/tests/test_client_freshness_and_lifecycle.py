"""
Automated tests for citizen client freshness lifecycle, offline detection,
marker lifecycle, SOS preservation, and GCS UI navigation contracts.
"""

from datetime import datetime, timezone
import os
import sys
import time
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app
from emesh_service import EMeshService, get_emesh_service
import config


class TestClientFreshnessAndLifecycle:

    @classmethod
    def setup_class(cls):
        cls.client = TestClient(app)
        cls.svc = get_emesh_service()

    def test_1_fresh_client_is_online(self):
        """A client with a fresh heartbeat (<= timeout) reports is_online == True."""
        now = time.time()
        fresh_ts = datetime.fromtimestamp(now - 10, tz=timezone.utc).isoformat()
        raw_client = {
            "client_id": "phone-alpha-123",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "accuracy": 8.0,
            "updated_at": fresh_ts,
        }

        enriched = self.svc._enrich_client_freshness(raw_client, now=now)
        assert enriched["is_online"] is True
        assert enriched["last_seen_epoch"] == pytest.approx(now - 10, abs=1.0)
        assert enriched["age_seconds"] == pytest.approx(10.0, abs=1.0)

    def test_2_expired_client_becomes_offline(self):
        """A client whose heartbeat exceeds timeout (>35s) reports is_online == False."""
        now = time.time()
        timeout = self.svc.client_timeout_s
        stale_ts = datetime.fromtimestamp(now - (timeout + 15), tz=timezone.utc).isoformat()
        raw_client = {
            "client_id": "phone-beta-456",
            "latitude": 13.0850,
            "longitude": 80.2720,
            "accuracy": 12.0,
            "updated_at": stale_ts,
        }

        enriched = self.svc._enrich_client_freshness(raw_client, now=now)
        assert enriched["is_online"] is False
        assert enriched["age_seconds"] >= timeout

    def test_3_connected_client_count_decreases_correctly(self):
        """Status endpoint client_count strictly reflects actively online clients."""
        now = time.time()
        timeout = self.svc.client_timeout_s
        fresh_client = {
            "client_id": "c-fresh",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "last_seen_epoch": now - 5,
            "updated_at": datetime.fromtimestamp(now - 5, tz=timezone.utc).isoformat(),
        }
        expired_client = {
            "client_id": "c-expired",
            "latitude": 13.0830,
            "longitude": 80.2710,
            "last_seen_epoch": now - (timeout + 20),
            "updated_at": datetime.fromtimestamp(now - (timeout + 20), tz=timezone.utc).isoformat(),
        }

        with self.svc._lock:
            self.svc._cached_clients = [fresh_client, expired_client]

        st = self.svc.get_status()
        assert st["client_count"] == 1
        assert st["total_registered_clients"] == 2

    def test_4_reconnect_with_fresh_heartbeat_restores_online_status(self):
        """A client reconnecting after going offline has its online status restored."""
        now = time.time()
        timeout = self.svc.client_timeout_s

        # Initially offline
        with self.svc._lock:
            self.svc._cached_clients = [{
                "client_id": "c-reconnect",
                "latitude": 13.0827,
                "longitude": 80.2707,
                "last_seen_epoch": now - 100,
                "is_online": False,
            }]

        assert self.svc._enrich_client_freshness(self.svc._cached_clients[0], now=now)["is_online"] is False

        # Incoming WebSocket heartbeat from reconnected phone
        self.svc._handle_incoming_ws_event({
            "event": "user.location_updated",
            "data": {
                "client_id": "c-reconnect",
                "latitude": 13.0829,
                "longitude": 80.2709,
                "accuracy": 5.0,
            }
        })

        with self.svc._lock:
            updated = next(c for c in self.svc._cached_clients if c["client_id"] == "c-reconnect")

        assert updated["is_online"] is True
        assert updated["latitude"] == 13.0829
        assert updated["longitude"] == 80.2709
        assert updated["last_seen_epoch"] == pytest.approx(time.time(), abs=2.0)

    def test_5_offline_client_with_active_sos_retains_sos_record(self):
        """An offline client with an active SOS retains its SOS record and alert unchanged."""
        now = time.time()
        cid = "phone-emergency-victim"

        with self.svc._lock:
            # Client is offline
            self.svc._cached_clients = [{
                "client_id": cid,
                "latitude": 13.0844,
                "longitude": 80.2711,
                "last_seen_epoch": now - 500,
                "is_online": False,
            }]
            # SOS alert is active
            self.svc._cached_sos = [{
                "id": "sos-victim-001",
                "client_id": cid,
                "status": "ACTIVE",
                "message": "Trapped on roof",
                "latitude": 13.0844,
                "longitude": 80.2711,
            }]

        sos_list = self.svc.fetch_sos()
        assert len(sos_list) == 1
        assert sos_list[0]["id"] == "sos-victim-001"
        assert sos_list[0]["status"] == "ACTIVE"
        assert sos_list[0]["client_id"] == cid

        # Status check
        st = self.svc.get_status()
        assert st["active_sos_count"] == 1
        assert st["client_count"] == 0  # Client is offline, but SOS is ACTIVE

    def test_6_no_duplicate_clients_on_multiple_ws_events(self):
        """Multiple location updates for the same client update in-place without duplicating."""
        with self.svc._lock:
            self.svc._cached_clients.clear()

        for step in range(5):
            self.svc._handle_incoming_ws_event({
                "event": "user.location_updated",
                "data": {
                    "client_id": "phone-single-device",
                    "latitude": 13.0800 + (step * 0.0001),
                    "longitude": 80.2700 + (step * 0.0001),
                    "accuracy": 10.0,
                }
            })

        with self.svc._lock:
            assert len(self.svc._cached_clients) == 1
            c = self.svc._cached_clients[0]
            assert c["client_id"] == "phone-single-device"
            assert c["latitude"] == pytest.approx(13.0804, abs=0.00001)

    def test_7_explicit_disconnect_marks_offline(self):
        """An explicit user.offline event immediately sets is_online to False."""
        self.svc._handle_incoming_ws_event({
            "event": "user.location_updated",
            "data": {
                "client_id": "phone-to-disconnect",
                "latitude": 13.0810,
                "longitude": 80.2710,
            }
        })

        with self.svc._lock:
            assert any(c["client_id"] == "phone-to-disconnect" and c["is_online"] for c in self.svc._cached_clients)

        self.svc._handle_incoming_ws_event({
            "event": "user.offline",
            "data": {
                "client_id": "phone-to-disconnect",
            }
        })

        with self.svc._lock:
            c = next(c for c in self.svc._cached_clients if c["client_id"] == "phone-to-disconnect")
            assert c["is_online"] is False

    def test_8_ui_contracts_index_html(self):
        """Verify HTML contains all 5 top-level navigation tabs with correct IDs and attributes."""
        from pathlib import Path
        html_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")

        # Tabs exist
        assert 'id="tab-mission"' in content
        assert 'id="tab-rf"' in content
        assert 'id="tab-deploy"' in content
        assert 'id="tab-history"' in content
        assert 'id="tab-emesh"' in content
        assert 'EMERGENCY MESH' in content
        assert 'badge-tab-sos-count' in content

    def test_9_ui_contracts_style_css(self):
        """Verify CSS contains flex-based tab navigation without rigid 4-column constraint."""
        from pathlib import Path
        css_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "style.css"
        assert css_path.exists()
        content = css_path.read_text(encoding="utf-8")

        # .cmd-tabs flex layout and no repeat(4, 1fr)
        assert ".cmd-tabs {" in content
        assert "grid-template-columns: repeat(4, 1fr);" not in content
        assert "white-space: nowrap;" in content
        assert "#tab-emesh" in content
        assert ".card-client-online" in content
        assert ".card-client-offline" in content

    def test_10_ui_contracts_app_js(self):
        """Verify app.js contains authoritative freshness functions and periodic check."""
        from pathlib import Path
        js_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "app.js"
        assert js_path.exists()
        content = js_path.read_text(encoding="utf-8")

        assert "function isClientOnline(" in content
        assert "function getClientTimestampMs(" in content
        assert "function formatClientLastSeen(" in content
        assert "CLIENT_INACTIVITY_TIMEOUT_MS" in content
        assert "activeOnlineKeys" in content
        assert "state.connectedClientsLayer.removeLayer" in content
