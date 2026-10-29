"""
Performance tests for FreshRoute.

Responsible for: measuring API response times, payload sizes and database
query latency so regressions are caught before a live demo.
NOT responsible for: correctness (those live in test_api.py, test_matcher.py, etc.).
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend import state
from backend.main import app

# Thresholds chosen to be generous enough for CI but tight enough to catch
# regressions.  All times are in milliseconds.
MAX_STATE_MS = 50
MAX_RECOMMEND_MS = 100
MAX_ANALYTICS_MS = 100
MAX_REROUTE_MS = 200
MAX_AUDIT_CSV_MS = 200
MAX_STATE_PAYLOAD_BYTES = 50_000


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_demo():
    state.reset_state()
    yield
    state.reset_state()


class TestStateLatency:
    def test_state_response_time(self, client):
        """GET /state must return within 50 ms."""
        start = time.perf_counter()
        resp = client.get("/state")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < MAX_STATE_MS, f"GET /state took {elapsed_ms:.1f} ms (limit {MAX_STATE_MS})"

    def test_state_payload_size(self, client):
        """Full state must stay under 50 KB to keep WebSocket frames small."""
        resp = client.get("/state")
        assert resp.status_code == 200
        assert len(resp.content) < MAX_STATE_PAYLOAD_BYTES, (
            f"State payload {len(resp.content)} bytes exceeds {MAX_STATE_PAYLOAD_BYTES}"
        )

    def test_health_response_time(self, client):
        """Health probe must be near-instant."""
        start = time.perf_counter()
        resp = client.get("/health")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 10, f"GET /health took {elapsed_ms:.1f} ms"


class TestRecommendLatency:
    def test_recommend_response_time(self, client):
        """Recommendation computation must complete within 100 ms."""
        client.post("/simulate/delay?vehicle_id=V1")
        start = time.perf_counter()
        resp = client.get("/recommend/V1")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < MAX_RECOMMEND_MS, (
            f"GET /recommend/V1 took {elapsed_ms:.1f} ms (limit {MAX_RECOMMEND_MS})"
        )

    def test_recommend_with_bulk_load(self, client):
        """Split-plan computation for a 6500 kg load must stay fast."""
        client.post("/simulate/reefer_failure?vehicle_id=V4")
        start = time.perf_counter()
        resp = client.get("/recommend/V4")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < MAX_RECOMMEND_MS, (
            f"GET /recommend/V4 took {elapsed_ms:.1f} ms (limit {MAX_RECOMMEND_MS})"
        )


class TestAnalyticsLatency:
    def test_analytics_response_time(self, client):
        """Analytics aggregation must complete within 100 ms."""
        client.post("/simulate/delay?vehicle_id=V1")
        client.post("/reroute", json={"vehicle_id": "V1", "facility_id": "F4"})
        start = time.perf_counter()
        resp = client.get("/analytics")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < MAX_ANALYTICS_MS, (
            f"GET /analytics took {elapsed_ms:.1f} ms (limit {MAX_ANALYTICS_MS})"
        )

    def test_audit_csv_response_time(self, client):
        """CSV export must complete within 200 ms."""
        client.post("/simulate/delay?vehicle_id=V1")
        client.post("/reroute", json={"vehicle_id": "V1", "facility_id": "F4"})
        start = time.perf_counter()
        resp = client.get("/audit.csv")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < MAX_AUDIT_CSV_MS, (
            f"GET /audit.csv took {elapsed_ms:.1f} ms (limit {MAX_AUDIT_CSV_MS})"
        )


class TestRerouteLatency:
    def test_reroute_response_time(self, client):
        """Accepting a reroute must complete within 200 ms."""
        client.post("/simulate/delay?vehicle_id=V1")
        rec = client.get("/recommend/V1").json()
        facility_id = rec["recommendations"][0]["facility_id"]
        start = time.perf_counter()
        resp = client.post(
            "/reroute", json={"vehicle_id": "V1", "facility_id": facility_id}
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < MAX_REROUTE_MS, (
            f"POST /reroute took {elapsed_ms:.1f} ms (limit {MAX_REROUTE_MS})"
        )


class TestBroadcastLatency:
    def test_state_serialization(self, client):
        """get_state() serialization must be fast."""
        from backend import state
        start = time.perf_counter()
        for _ in range(100):
            state.get_state()
        elapsed_ms = (time.perf_counter() - start) * 1000
        per_call_ms = elapsed_ms / 100
        assert per_call_ms < 5, f"get_state() took {per_call_ms:.2f} ms/call (limit 5)"


class TestDbLatency:
    def test_analytics_cached(self, client):
        """Second analytics call should be faster (cached)."""
        client.post("/simulate/delay?vehicle_id=V1")
        client.post("/reroute", json={"vehicle_id": "V1", "facility_id": "F4"})
        # Warm cache
        client.get("/analytics")
        start = time.perf_counter()
        client.get("/analytics")
        cached_ms = (time.perf_counter() - start) * 1000
        assert cached_ms < 10, f"Cached analytics took {cached_ms:.1f} ms (limit 10)"
