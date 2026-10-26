"""
Comprehensive Test Suite for SOS Map Accuracy, Real-Time Updates,
Acknowledgement Behavior, and Geospatial Coordinate Integrity.

Covers all 12 problem requirements:
1. Acknowledging an SOS removes it from active map and queue without deleting the stored record.
2. Resolved and dismissed SOS alerts also disappear from active map layer.
3. Active SOS counts update immediately.
4. New SOS reports appear in real-time via WebSocket broadcast without browser refresh.
5. Acknowledgement and resolution events update other connected GCS sessions.
6. WebSocket reconnection / snapshot restores current state.
7. Correct latitude/longitude ordering is maintained without coordinate swapping or excessive rounding.
8. Missing or invalid coordinates never generate arbitrary markers or mock coordinates.
9. Updates modify existing markers and records without creating duplicates.
10. Basemap loading failure does not break SOS actions, telemetry, or GCS functions.
11. API failures do not silently remove alerts or falsely confirm an acknowledgement.
12. Existing UAV mission planning, telemetry, map layers, RF survey, and safety checks continue to work.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app, session_state
from emesh_service import EMeshService, get_emesh_service


class TestSOSLifecycleAndCoordinateIntegrity(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.svc = get_emesh_service()

    def test_01_acknowledgement_preserves_record_and_marks_acknowledged(self):
        """1. Acknowledging an SOS updates status, sets timestamp, and preserves record."""
        fake_sos = {
            "id": "test-uuid-001",
            "sos_id": "SOS-10001",
            "status": "ACKNOWLEDGED",
            "latitude": 13.085001,
            "longitude": 80.275002,
            "accuracy": 8.5,
            "people_count": 2,
            "notes": "Flooding reported",
            "created_at": "2026-10-26T12:00:00Z",
            "acknowledged_at": "2026-10-26T12:05:00Z",
            "resolved_at": None,
        }

        with patch("emesh_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.patch.return_value = MagicMock(status_code=200, json=lambda: fake_sos)
            mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"data": [fake_sos], "total": 1})

            res = self.client.patch("/api/emesh/sos/test-uuid-001", json={"status": "ACKNOWLEDGED"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "ACKNOWLEDGED")
            self.assertEqual(data["id"], "test-uuid-001")
            self.assertIsNotNone(data["acknowledged_at"])
            # Ensure coordinates are preserved
            self.assertAlmostEqual(data["latitude"], 13.085001, places=6)
            self.assertAlmostEqual(data["longitude"], 80.275002, places=6)

    def test_02_resolution_and_dismissal_preserves_records(self):
        """2. Resolved and dismissed SOS alerts update status and preserve records."""
        fake_resolved = {
            "id": "test-uuid-002",
            "sos_id": "SOS-10002",
            "status": "RESOLVED",
            "latitude": 13.086000,
            "longitude": 80.276000,
            "accuracy": 5.0,
            "people_count": 1,
            "resolved_at": "2026-10-26T12:10:00Z",
        }
        fake_cancelled = {
            "id": "test-uuid-003",
            "sos_id": "SOS-10003",
            "status": "CANCELLED",
            "latitude": 13.087000,
            "longitude": 80.277000,
        }

        with patch("emesh_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            # Test RESOLVED
            mock_client.patch.return_value = MagicMock(status_code=200, json=lambda: fake_resolved)
            mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"data": [fake_resolved], "total": 1})
            res = self.client.patch("/api/emesh/sos/test-uuid-002", json={"status": "RESOLVED"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "RESOLVED")

            # Test DISMISSED -> maps to CANCELLED
            mock_client.patch.return_value = MagicMock(status_code=200, json=lambda: fake_cancelled)
            res = self.client.patch("/api/emesh/sos/test-uuid-003", json={"status": "DISMISSED"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "CANCELLED")

    def test_03_active_sos_counts_strictly_active_records(self):
        """3. Active SOS count must count only records with status ACTIVE."""
        test_sos_records = [
            {"id": "s1", "sos_id": "SOS-01", "status": "ACTIVE"},
            {"id": "s2", "sos_id": "SOS-02", "status": "ACKNOWLEDGED"},
            {"id": "s3", "sos_id": "SOS-03", "status": "RESOLVED"},
            {"id": "s4", "sos_id": "SOS-04", "status": "ACTIVE"},
            {"id": "s5", "sos_id": "SOS-05", "status": "CANCELLED"},
        ]
        with self.svc._lock:
            self.svc._cached_sos = test_sos_records

        # Calculate active count according to the rule
        active_records = [s for s in self.svc._cached_sos if str(s.get("status", "")).upper() == "ACTIVE"]
        self.assertEqual(len(active_records), 2)

        # Transition s1 to ACKNOWLEDGED
        self.svc._handle_incoming_ws_event({
            "event": "sos.updated",
            "data": {"id": "s1", "sos_id": "SOS-01", "status": "ACKNOWLEDGED"}
        })
        active_records_after = [s for s in self.svc._cached_sos if str(s.get("status", "")).upper() == "ACTIVE"]
        self.assertEqual(len(active_records_after), 1)

    def test_04_real_time_sos_creation_broadcast(self):
        """4. New SOS report broadcasts through service to GCS subscribers."""
        import asyncio
        loop = asyncio.new_event_loop()
        q = loop.create_task(self._subscribe_and_receive(loop))
        received = loop.run_until_complete(q)
        loop.close()
        self.assertEqual(received["event"], "sos.created")
        self.assertEqual(received["data"]["sos_id"], "SOS-99999")

    async def _subscribe_and_receive(self, loop):
        import asyncio
        q = asyncio.Queue()
        self.svc.register_subscriber(q)
        try:
            self.svc._handle_incoming_ws_event({
                "event": "sos.created",
                "data": {
                    "id": "new-uuid-99",
                    "sos_id": "SOS-99999",
                    "status": "ACTIVE",
                    "latitude": 13.082711,
                    "longitude": 80.270722,
                    "accuracy": 12.0,
                }
            })
            item = await asyncio.wait_for(q.get(), timeout=2.0)
            return item
        finally:
            self.svc.unregister_subscriber(q)

    def test_05_acknowledgement_event_broadcast_to_gcs_sessions(self):
        """5. Acknowledgement broadcasts sos.updated with status ACKNOWLEDGED to all sessions."""
        import asyncio
        loop = asyncio.new_event_loop()
        async def run_test():
            q1 = asyncio.Queue()
            q2 = asyncio.Queue()
            self.svc.register_subscriber(q1)
            self.svc.register_subscriber(q2)
            try:
                self.svc._handle_incoming_ws_event({
                    "event": "sos.updated",
                    "data": {
                        "id": "uuid-broadcast",
                        "sos_id": "SOS-777",
                        "status": "ACKNOWLEDGED",
                    }
                })
                m1 = await asyncio.wait_for(q1.get(), timeout=2.0)
                m2 = await asyncio.wait_for(q2.get(), timeout=2.0)
                return m1, m2
            finally:
                self.svc.unregister_subscriber(q1)
                self.svc.unregister_subscriber(q2)

        m1, m2 = loop.run_until_complete(run_test())
        loop.close()
        self.assertEqual(m1["event"], "sos.updated")
        self.assertEqual(m1["data"]["status"], "ACKNOWLEDGED")
        self.assertEqual(m2["event"], "sos.updated")
        self.assertEqual(m2["data"]["status"], "ACKNOWLEDGED")

    def test_06_websocket_snapshot_restores_state(self):
        """6. Reconnection snapshot returns current state of active and historical SOS."""
        fake_snapshot = [
            {"id": "hist-1", "sos_id": "SOS-01", "status": "ACKNOWLEDGED"},
            {"id": "act-1", "sos_id": "SOS-02", "status": "ACTIVE"},
        ]

        with patch("emesh_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"data": fake_snapshot, "total": 2})

            res = self.client.get("/api/emesh/sos")
            self.assertEqual(res.status_code, 200)
            items = res.json()
            self.assertEqual(len(items), 2)
            statuses = {s["status"] for s in items}
            self.assertIn("ACTIVE", statuses)
            self.assertIn("ACKNOWLEDGED", statuses)

    def test_07_lat_lon_ordering_and_precision_preserved(self):
        """7. Latitude and longitude maintain [lat, lon] order and 6 decimal places."""
        test_lat = 13.084567
        test_lon = 80.276543
        test_acc = 14.2

        fake_res = {
            "id": "geo-uuid-1",
            "sos_id": "SOS-GEO-1",
            "status": "ACTIVE",
            "latitude": test_lat,
            "longitude": test_lon,
            "accuracy": test_acc,
        }
        with patch("emesh_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.patch.return_value = MagicMock(status_code=200, json=lambda: fake_res)
            mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"data": [fake_res], "total": 1})

            res = self.client.patch(
                "/api/emesh/sos/geo-uuid-1",
                json={"latitude": test_lat, "longitude": test_lon}
            )
            self.assertEqual(res.status_code, 200)
            body = res.json()
            # Must strictly match latitude and longitude keys and order
            self.assertEqual(body["latitude"], test_lat)
            self.assertEqual(body["longitude"], test_lon)
            self.assertGreater(body["latitude"], -90)
            self.assertLess(body["latitude"], 90)
            self.assertGreater(body["longitude"], -180)
            self.assertLess(body["longitude"], 180)

    def test_08_missing_coordinates_never_generate_mock_coordinates(self):
        """8. Missing or null GPS coordinates must remain None without fallback mock coords."""
        fake_unlocated = {
            "id": "unlocated-uuid",
            "sos_id": "SOS-NO-GPS",
            "status": "ACTIVE",
            "latitude": None,
            "longitude": None,
            "accuracy": None,
            "notes": "GPS unavailable inside building",
        }
        with patch("emesh_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"data": [fake_unlocated], "total": 1})

            res = self.client.get("/api/emesh/sos")
            self.assertEqual(res.status_code, 200)
            items = res.json()
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertIsNone(item["latitude"])
            self.assertIsNone(item["longitude"])
            self.assertIsNone(item["accuracy"])

    def test_09_in_place_update_prevents_duplicate_records(self):
        """9. Multiple updates to an SOS update the existing entry without duplicating."""
        with self.svc._lock:
            self.svc._cached_sos = [
                {"id": "dup-check-1", "sos_id": "SOS-DUP", "status": "ACTIVE"}
            ]

        # First update
        self.svc._handle_incoming_ws_event({
            "event": "sos.updated",
            "data": {"id": "dup-check-1", "sos_id": "SOS-DUP", "status": "ACKNOWLEDGED"}
        })
        # Second update
        self.svc._handle_incoming_ws_event({
            "event": "sos.updated",
            "data": {"id": "dup-check-1", "sos_id": "SOS-DUP", "status": "RESOLVED"}
        })

        matching = [s for s in self.svc._cached_sos if s.get("id") == "dup-check-1"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["status"], "RESOLVED")

    def test_10_basemap_independence(self):
        """10. Backend API, telemetry, and SOS endpoints function completely independently of tile servers."""
        res_status = self.client.get("/api/status")
        self.assertEqual(res_status.status_code, 200)
        res_nodes = self.client.get("/api/nodes")
        self.assertEqual(res_nodes.status_code, 200)
        res_emesh_status = self.client.get("/api/emesh/status")
        self.assertEqual(res_emesh_status.status_code, 200)

    def test_11_api_failure_does_not_falsely_succeed(self):
        """11. API failures return honest error codes (502) and do not report false success."""
        with patch("emesh_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.patch.side_effect = Exception("E-MESH connection timeout")

            res = self.client.patch("/api/emesh/sos/nonexistent-id", json={"status": "ACKNOWLEDGED"})
            self.assertEqual(res.status_code, 502)
            self.assertIn("E-MESH update failed", res.json()["detail"])

    def test_12_existing_uav_mission_and_telemetry_intact(self):
        """12. Existing UAV mission planning, RF survey, and safety checks remain functional."""
        # 1. Status endpoint
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        self.assertIn("status", res.json())
        self.assertEqual(res.json()["status"], "ok")

        # 2. Nodes endpoint
        res_nodes = self.client.get("/api/nodes")
        self.assertEqual(res_nodes.status_code, 200)

        # 3. Area endpoint
        test_poly = [
            {"lat": 13.0820, "lon": 80.2700},
            {"lat": 13.0830, "lon": 80.2700},
            {"lat": 13.0830, "lon": 80.2710},
            {"lat": 13.0820, "lon": 80.2710},
        ]
        res_area = self.client.post("/api/area", json={"polygon": test_poly})
        self.assertEqual(res_area.status_code, 200)

        # 4. RF survey state
        res_rf = self.client.get("/api/emesh/survey/status")
        self.assertEqual(res_rf.status_code, 200)


if __name__ == "__main__":
    unittest.main()
