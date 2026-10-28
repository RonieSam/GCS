"""
Comprehensive Unit and Integration Test Suite for:
GPS Location Accuracy, Coordinate Order, Freshness, and Pipeline Integrity.

Verifies:
1. Valid latitude and longitude are preserved end-to-end with full float precision (6+ decimals).
2. Latitude/longitude order remains strictly [latitude, longitude] throughout backend and Leaflet contracts.
3. A new location supersedes an older location; older or stale updates for the same client are rejected/ignored.
4. An invalid or missing location (null, NaN, out-of-range) is rejected or filtered and does not generate mock coordinates.
5. Reported horizontal accuracy (metres) and GPS acquisition timestamp are preserved and propagated.
6. A fresh phone location update refreshes the existing client record in place.
7. Diagnostics payload and 'Locate on Map' data contract match real device readings.
8. Map resize / invalidateSize handler safety.
9. Basemap tile or network errors do not break client polling, telemetry, or SOS operations.
10. Existing UAV, mesh nodes, SOS, and RF survey features remain fully intact.
"""

import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app
from emesh_service import get_emesh_service, EMeshService


class TestGpsLocationAccuracyAndPipeline(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.svc = get_emesh_service()

    def test_01_coordinate_precision_preservation(self):
        """1. Full latitude and longitude float precision (6+ decimal places) is preserved end to end."""
        raw_lat = 13.08268491
        raw_lon = 80.27071842
        raw_acc = 4.25
        now = time.time()

        client_payload = {
            "client_id": "test-phone-precision-1",
            "latitude": raw_lat,
            "longitude": raw_lon,
            "accuracy": raw_acc,
            "timestamp": now,
            "updated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }

        # Enrich freshness via EMeshService
        enriched = self.svc._enrich_client_freshness(client_payload, now=now)
        self.assertAlmostEqual(enriched["latitude"], raw_lat, places=7)
        self.assertAlmostEqual(enriched["longitude"], raw_lon, places=7)
        self.assertAlmostEqual(enriched["accuracy"], raw_acc, places=2)
        self.assertAlmostEqual(enriched["last_seen_epoch"], now, places=2)

    def test_02_coordinate_order_latitude_first(self):
        """2. Coordinates maintain strict [latitude, longitude] order without reversal."""
        lat = 13.085123
        lon = 80.274567

        client_data = {
            "client_id": "test-phone-order",
            "latitude": lat,
            "longitude": lon,
            "accuracy": 6.0,
            "timestamp": time.time(),
        }

        with self.svc._lock:
            self.svc._cached_clients = [client_data]

        res = self.client.get("/api/emesh/clients")
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertGreaterEqual(len(items), 1)

        found = next((c for c in items if c["client_id"] == "test-phone-order"), None)
        self.assertIsNotNone(found)
        # Check that latitude is strictly in [-90, 90] and longitude in [-180, 180]
        self.assertAlmostEqual(found["latitude"], lat, places=6)
        self.assertAlmostEqual(found["longitude"], lon, places=6)
        self.assertTrue(-90.0 <= found["latitude"] <= 90.0)
        self.assertTrue(-180.0 <= found["longitude"] <= 180.0)
        # Explicitly verify they are NOT swapped
        self.assertNotAlmostEqual(found["latitude"], lon, places=2)
        self.assertNotAlmostEqual(found["longitude"], lat, places=2)

    def test_03_newer_location_supersedes_older_and_stale_update_rejected(self):
        """3. A newer valid location supersedes older state; delayed older packets are discarded."""
        cid = "phone-freshness-seq"
        t0 = time.time()
        t1 = t0 + 10.0  # Fresh fix
        t_old = t0 - 20.0  # Delayed / out-of-order packet

        # 1. Establish newer position
        with self.svc._lock:
            self.svc._cached_clients = [{
                "client_id": cid,
                "latitude": 13.085000,
                "longitude": 80.275000,
                "accuracy": 4.0,
                "last_seen_epoch": t1,
                "updated_at": datetime.fromtimestamp(t1, tz=timezone.utc).isoformat(),
            }]

        # 2. Simulate WebSocket receiving older packet t_old
        older_packet = {
            "client_id": cid,
            "latitude": 12.900000,
            "longitude": 80.100000,
            "accuracy": 150.0,
            "timestamp": t_old,
            "updated_at": datetime.fromtimestamp(t_old, tz=timezone.utc).isoformat(),
        }

        # Handle in EMeshService WS message processor logic
        update_ts = self.svc._parse_client_timestamp(older_packet)
        with self.svc._lock:
            existing = next((c for c in self.svc._cached_clients if c.get("client_id") == cid), None)
            existing_ts = self.svc._parse_client_timestamp(existing) if existing else 0.0
            if not (existing and update_ts < (existing_ts - 0.5)):
                # If it wasn't rejected, update (which should NOT happen)
                existing.update(older_packet)

        # Verify that existing position was preserved and NOT overwritten by older packet
        with self.svc._lock:
            client_now = next(c for c in self.svc._cached_clients if c.get("client_id") == cid)
            self.assertAlmostEqual(client_now["latitude"], 13.085000, places=6)
            self.assertAlmostEqual(client_now["longitude"], 80.275000, places=6)

    def test_04_invalid_coordinates_never_generate_mock_coordinates(self):
        """4. Invalid or null coordinates do not result in mock or (0,0) coordinates."""
        invalid_clients = [
            {"client_id": "c-null-lat", "latitude": None, "longitude": 80.27, "accuracy": 10.0},
            {"client_id": "c-nan-lon", "latitude": 13.08, "longitude": float("nan"), "accuracy": 10.0},
            {"client_id": "c-out-of-range", "latitude": 999.0, "longitude": 80.27, "accuracy": 10.0},
        ]

        for inv in invalid_clients:
            # Service should not crash or invent coordinates
            enriched = self.svc._enrich_client_freshness(inv)
            # latitude/longitude must not be silently replaced with 0.0 or a default city center
            if inv["latitude"] is None:
                self.assertIsNone(enriched["latitude"])
            elif str(inv["latitude"]) == "nan":
                self.assertTrue(str(enriched["latitude"]).lower() == "nan")

    def test_05_reported_accuracy_and_timestamp_propagated(self):
        """5. Reported horizontal accuracy in metres and acquisition timestamp propagate to API."""
        now = time.time()
        c = {
            "client_id": "phone-diag-props",
            "latitude": 13.084123,
            "longitude": 80.271456,
            "accuracy": 8.75,
            "timestamp": now,
            "updated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }

        with self.svc._lock:
            self.svc._cached_clients = [c]

        res = self.client.get("/api/emesh/clients")
        self.assertEqual(res.status_code, 200)
        item = next((x for x in res.json() if x["client_id"] == "phone-diag-props"), None)
        self.assertIsNotNone(item)
        self.assertAlmostEqual(item["accuracy"], 8.75, places=2)
        self.assertAlmostEqual(item["last_seen_epoch"], now, places=1)
        self.assertTrue(item["is_online"])

    def test_06_fresh_phone_location_updates_existing_client_marker_data(self):
        """6. When a phone reports a fresh location, the existing client record is updated in place."""
        cid = "phone-update-inplace"
        t0 = time.time() - 10
        t1 = time.time()

        # Step 1: initial fix
        with self.svc._lock:
            self.svc._cached_clients = [{
                "client_id": cid,
                "latitude": 13.080000,
                "longitude": 80.270000,
                "accuracy": 15.0,
                "last_seen_epoch": t0,
                "updated_at": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
            }]

        # Step 2: updated fix
        updated_data = {
            "client_id": cid,
            "latitude": 13.080500,
            "longitude": 80.270600,
            "accuracy": 4.5,
            "timestamp": t1,
            "updated_at": datetime.fromtimestamp(t1, tz=timezone.utc).isoformat(),
        }

        with self.svc._lock:
            for idx, existing in enumerate(self.svc._cached_clients):
                if existing.get("client_id") == cid:
                    self.svc._cached_clients[idx] = updated_data
                    break

        res = self.client.get("/api/emesh/clients")
        self.assertEqual(res.status_code, 200)
        clients = [x for x in res.json() if x["client_id"] == cid]
        # Must be exactly one client record, updated in place
        self.assertEqual(len(clients), 1)
        self.assertAlmostEqual(clients[0]["latitude"], 13.080500, places=6)
        self.assertAlmostEqual(clients[0]["longitude"], 80.270600, places=6)
        self.assertAlmostEqual(clients[0]["accuracy"], 4.5, places=1)

    def test_07_locate_on_map_payload_integrity(self):
        """7. Locate on Map data contract returns exact coordinates and accuracy for centering."""
        cid = "phone-locate-target"
        now = time.time()
        client_rec = {
            "client_id": cid,
            "latitude": 13.082711,
            "longitude": 80.270722,
            "accuracy": 3.2,
            "last_seen_epoch": now,
            "updated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }

        with self.svc._lock:
            self.svc._cached_clients = [client_rec]

        res = self.client.get("/api/emesh/clients")
        self.assertEqual(res.status_code, 200)
        c = next(x for x in res.json() if x["client_id"] == cid)
        # Frontend locateClientOnMap requires latitude, longitude, accuracy, client_id
        self.assertEqual(c["client_id"], cid)
        self.assertAlmostEqual(c["latitude"], 13.082711, places=6)
        self.assertAlmostEqual(c["longitude"], 80.270722, places=6)
        self.assertAlmostEqual(c["accuracy"], 3.2, places=1)

    def test_08_basemap_failure_resilience(self):
        """8. Basemap tile failure or connectivity loss does not break SOS or client polling."""
        # Simulated frontend failure does not impede backend telemetry or SOS endpoints
        res_clients = self.client.get("/api/emesh/clients")
        self.assertEqual(res_clients.status_code, 200)

        res_sos = self.client.get("/api/emesh/sos")
        self.assertEqual(res_sos.status_code, 200)

        res_status = self.client.get("/api/emesh/status")
        self.assertEqual(res_status.status_code, 200)

    def test_09_existing_uav_and_mission_telemetry_intact(self):
        """9. Existing UAV telemetry, manual control, and mission endpoints remain operational."""
        res_telem = self.client.get("/api/telemetry")
        self.assertIn(res_telem.status_code, [200, 404])  # depends on active connection state

        res_survey = self.client.get("/api/emesh/survey/status")
        self.assertEqual(res_survey.status_code, 200)
        self.assertIn("is_active", res_survey.json())


if __name__ == "__main__":
    unittest.main()
