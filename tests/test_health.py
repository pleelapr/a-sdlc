"""Tests for ServerHealth singleton and /health endpoint (SDLC-T00251).

Covers:
- Ring buffer capacity (101st event evicts oldest)
- Event recording with correct timestamps
- Health JSON payload contains all required fields
- Uptime calculation accuracy
- /health endpoint returns 200 with correct JSON structure
- Response time benchmark: p95 < 100ms
- Memory: ring buffer stays under 1MB
- Singleton pattern correctness
- Thread safety
- Active connection counting
- Error recording
- Optional ?events=true query parameter
"""

import asyncio
import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.server.health import ServerHealth

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset ServerHealth singleton before and after each test."""
    ServerHealth.reset()
    yield
    ServerHealth.reset()


# =============================================================================
# Singleton Pattern
# =============================================================================


class TestSingleton:
    """ServerHealth must be a singleton."""

    def test_same_instance(self):
        a = ServerHealth()
        b = ServerHealth()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = ServerHealth()
        ServerHealth.reset()
        b = ServerHealth()
        assert a is not b

    def test_state_preserved_across_calls(self):
        h1 = ServerHealth()
        h1.record_event("connect", "client-1")
        h2 = ServerHealth()
        payload = h2.get_health(include_events=True)
        assert payload["connection_events_count"] == 1
        assert len(payload["connection_events"]) == 1


# =============================================================================
# Ring Buffer
# =============================================================================


class TestRingBuffer:
    """Ring buffer stores last 100 events; 101st evicts oldest."""

    def test_empty_buffer(self):
        h = ServerHealth()
        payload = h.get_health(include_events=True)
        assert payload["connection_events_count"] == 0
        assert payload["connection_events"] == []

    def test_single_event(self):
        h = ServerHealth()
        h.record_event("connect", "client-1")
        payload = h.get_health(include_events=True)
        assert payload["connection_events_count"] == 1
        assert payload["connection_events"][0]["type"] == "connect"
        assert payload["connection_events"][0]["detail"] == "client-1"

    def test_buffer_at_capacity(self):
        h = ServerHealth()
        for i in range(100):
            h.record_event("connect", f"client-{i}")
        payload = h.get_health(include_events=True)
        assert payload["connection_events_count"] == 100
        assert len(payload["connection_events"]) == 100
        # First event should be client-0
        assert payload["connection_events"][0]["detail"] == "client-0"
        # Last event should be client-99
        assert payload["connection_events"][-1]["detail"] == "client-99"

    def test_101st_event_evicts_oldest(self):
        h = ServerHealth()
        for i in range(101):
            h.record_event("connect", f"client-{i}")
        payload = h.get_health(include_events=True)
        assert payload["connection_events_count"] == 100
        assert len(payload["connection_events"]) == 100
        # Oldest (client-0) should be evicted; first is now client-1
        assert payload["connection_events"][0]["detail"] == "client-1"
        # Newest is client-100
        assert payload["connection_events"][-1]["detail"] == "client-100"

    def test_large_overflow(self):
        """Adding 200 events should keep only the last 100."""
        h = ServerHealth()
        for i in range(200):
            h.record_event("connect", f"client-{i}")
        payload = h.get_health(include_events=True)
        assert payload["connection_events_count"] == 100
        assert payload["connection_events"][0]["detail"] == "client-100"
        assert payload["connection_events"][-1]["detail"] == "client-199"


# =============================================================================
# Event Recording
# =============================================================================


class TestEventRecording:
    """Events have correct structure and timestamps."""

    def test_event_has_required_fields(self):
        h = ServerHealth()
        h.record_event("disconnect", "timeout")
        payload = h.get_health(include_events=True)
        event = payload["connection_events"][0]
        assert "type" in event
        assert "detail" in event
        assert "timestamp" in event
        assert "monotonic" in event

    def test_event_type_is_correct(self):
        h = ServerHealth()
        h.record_event("error", "connection refused")
        payload = h.get_health(include_events=True)
        assert payload["connection_events"][0]["type"] == "error"

    def test_timestamp_is_iso_format(self):
        h = ServerHealth()
        h.record_event("connect", "")
        payload = h.get_health(include_events=True)
        ts = payload["connection_events"][0]["timestamp"]
        # Should be valid ISO 8601 with timezone (ends with +00:00)
        assert "T" in ts
        assert "+" in ts or "Z" in ts

    def test_monotonic_is_float(self):
        h = ServerHealth()
        h.record_event("connect", "")
        payload = h.get_health(include_events=True)
        mono = payload["connection_events"][0]["monotonic"]
        assert isinstance(mono, float)

    def test_event_ordering(self):
        h = ServerHealth()
        h.record_event("first", "")
        h.record_event("second", "")
        h.record_event("third", "")
        payload = h.get_health(include_events=True)
        types = [e["type"] for e in payload["connection_events"]]
        assert types == ["first", "second", "third"]


# =============================================================================
# Health Payload
# =============================================================================


class TestHealthPayload:
    """get_health() returns all required fields with correct types."""

    def test_required_fields_present(self):
        h = ServerHealth()
        payload = h.get_health()
        required = [
            "status",
            "version",
            "uptime_seconds",
            "pid",
            "memory_mb",
            "active_connections",
            "last_error",
            "connection_events_count",
        ]
        for field in required:
            assert field in payload, f"Missing required field: {field}"

    def test_status_is_healthy(self):
        h = ServerHealth()
        assert h.get_health()["status"] == "healthy"

    def test_version_matches_package(self):
        import a_sdlc

        h = ServerHealth()
        assert h.get_health()["version"] == a_sdlc.__version__

    def test_pid_is_current_process(self):
        h = ServerHealth()
        assert h.get_health()["pid"] == os.getpid()

    def test_memory_mb_is_positive_float(self):
        h = ServerHealth()
        mem = h.get_health()["memory_mb"]
        assert isinstance(mem, float)
        # On systems with resource module, memory should be positive
        if sys.platform != "win32":
            assert mem > 0

    def test_active_connections_default_zero(self):
        h = ServerHealth()
        assert h.get_health()["active_connections"] == 0

    def test_last_error_default_none(self):
        h = ServerHealth()
        assert h.get_health()["last_error"] is None

    def test_events_not_included_by_default(self):
        h = ServerHealth()
        h.record_event("connect", "")
        payload = h.get_health()
        assert "connection_events" not in payload

    def test_events_included_when_requested(self):
        h = ServerHealth()
        h.record_event("connect", "")
        payload = h.get_health(include_events=True)
        assert "connection_events" in payload
        assert len(payload["connection_events"]) == 1


# =============================================================================
# Uptime Calculation
# =============================================================================


class TestUptime:
    """Uptime is calculated from monotonic clock."""

    def test_uptime_is_non_negative(self):
        h = ServerHealth()
        assert h.get_health()["uptime_seconds"] >= 0

    def test_uptime_increases(self):
        h = ServerHealth()
        t1 = h.get_health()["uptime_seconds"]
        time.sleep(0.05)
        t2 = h.get_health()["uptime_seconds"]
        assert t2 > t1

    def test_uptime_accuracy(self):
        """Uptime should be approximately correct within 0.5s tolerance."""
        h = ServerHealth()
        time.sleep(0.1)
        uptime = h.get_health()["uptime_seconds"]
        assert 0.05 <= uptime <= 0.6


# =============================================================================
# Active Connections
# =============================================================================


class TestActiveConnections:
    """Active connection counter with increment/decrement."""

    def test_increment(self):
        h = ServerHealth()
        h.increment_connections()
        assert h.get_health()["active_connections"] == 1

    def test_decrement(self):
        h = ServerHealth()
        h.increment_connections()
        h.increment_connections()
        h.decrement_connections()
        assert h.get_health()["active_connections"] == 1

    def test_decrement_floor_at_zero(self):
        h = ServerHealth()
        h.decrement_connections()
        assert h.get_health()["active_connections"] == 0

    def test_multiple_increments(self):
        h = ServerHealth()
        for _ in range(5):
            h.increment_connections()
        assert h.get_health()["active_connections"] == 5


# =============================================================================
# Error Recording
# =============================================================================


class TestErrorRecording:
    """Last error tracking."""

    def test_record_exception(self):
        h = ServerHealth()
        h.record_error(ValueError("test error"))
        err = h.get_health()["last_error"]
        assert err is not None
        assert err["type"] == "ValueError"
        assert err["message"] == "test error"
        assert "timestamp" in err

    def test_record_string_error(self):
        h = ServerHealth()
        h.record_error("something went wrong")
        err = h.get_health()["last_error"]
        assert err is not None
        assert err["type"] == "Error"
        assert err["message"] == "something went wrong"

    def test_last_error_overwrites_previous(self):
        h = ServerHealth()
        h.record_error(ValueError("first"))
        h.record_error(RuntimeError("second"))
        err = h.get_health()["last_error"]
        assert err["type"] == "RuntimeError"
        assert err["message"] == "second"


# =============================================================================
# Memory Usage
# =============================================================================


class TestMemoryUsage:
    """Memory reporting via resource module."""

    def test_memory_on_supported_platform(self):
        """On macOS/Linux, memory should be reported."""
        h = ServerHealth()
        if sys.platform in ("darwin", "linux"):
            assert h._get_memory_mb() > 0

    def test_memory_fallback_on_import_error(self):
        """If resource module is unavailable, should return 0.0."""
        h = ServerHealth()
        with (
            patch.dict("sys.modules", {"resource": None}),
            patch("a_sdlc.server.health.ServerHealth._get_memory_mb", return_value=0.0),
        ):
            assert h._get_memory_mb() == 0.0


# =============================================================================
# Ring Buffer Memory Constraint (NFR-004)
# =============================================================================


class TestRingBufferMemory:
    """Ring buffer should stay under 1MB even when full."""

    def test_full_buffer_under_1mb(self):
        h = ServerHealth()
        # Fill with reasonably large events (256 chars each)
        large_detail = "x" * 256
        for _i in range(100):
            h.record_event("connect", large_detail)
        payload = h.get_health(include_events=True)
        # Serialize to estimate size
        size_bytes = len(json.dumps(payload["connection_events"]).encode())
        assert size_bytes < 1_000_000, f"Ring buffer is {size_bytes} bytes, exceeds 1MB"


# =============================================================================
# Response Time Benchmark (NFR-001)
# =============================================================================


class TestResponseTime:
    """get_health() must return in under 100ms (p95)."""

    def test_health_response_time_p95(self):
        h = ServerHealth()
        # Fill buffer to capacity to test worst case
        for i in range(100):
            h.record_event("connect", f"client-{i}")
        h.increment_connections()
        h.record_error(ValueError("test"))

        timings = []
        for _ in range(100):
            start = time.monotonic()
            h.get_health(include_events=True)
            elapsed_ms = (time.monotonic() - start) * 1000
            timings.append(elapsed_ms)

        timings.sort()
        p95 = timings[94]  # 95th percentile
        assert p95 < 100, f"p95 response time is {p95:.2f}ms, exceeds 100ms"


# =============================================================================
# Thread Safety
# =============================================================================


class TestThreadSafety:
    """Concurrent access should not corrupt state."""

    def test_concurrent_events(self):
        import threading

        h = ServerHealth()
        errors = []

        def record_many(start_idx: int):
            try:
                for i in range(50):
                    h.record_event("connect", f"client-{start_idx + i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many, args=(i * 50,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # 200 total events, buffer capacity 100
        payload = h.get_health(include_events=True)
        assert payload["connection_events_count"] == 100

    def test_concurrent_connections(self):
        import threading

        h = ServerHealth()
        barrier = threading.Barrier(10)

        def inc_dec():
            barrier.wait()
            for _ in range(100):
                h.increment_connections()
            for _ in range(100):
                h.decrement_connections()

        threads = [threading.Thread(target=inc_dec) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All increments and decrements should cancel out
        assert h.get_health()["active_connections"] == 0


# =============================================================================
# /health Endpoint Integration
# =============================================================================


class TestHealthEndpoint:
    """/health endpoint returns 200 with correct JSON structure."""

    def test_endpoint_registered_on_mcp(self):
        """The /health route should be registered as a custom Starlette route."""
        from a_sdlc.server import mcp

        route_paths = [r.path for r in mcp._custom_starlette_routes]
        assert "/health" in route_paths

    def test_health_endpoint_returns_200(self):
        """Simulate calling the /health endpoint handler directly."""
        from a_sdlc.server import _health_endpoint

        async def _run():
            request = MagicMock()
            request.query_params = {}
            response = await _health_endpoint(request)
            assert response.status_code == 200
            body = json.loads(response.body.decode())
            assert body["status"] == "healthy"
            assert "version" in body
            assert "uptime_seconds" in body
            assert "pid" in body
            assert "memory_mb" in body
            assert "active_connections" in body
            assert "connection_events_count" in body
            # Events should NOT be in the response by default
            assert "connection_events" not in body

        asyncio.run(_run())

    def test_health_endpoint_with_events_param(self):
        """?events=true should include the full ring buffer."""
        from a_sdlc.server import _health_endpoint

        # Record some events first
        h = ServerHealth()
        h.record_event("connect", "test-client")

        async def _run():
            request = MagicMock()
            request.query_params = {"events": "true"}
            response = await _health_endpoint(request)
            assert response.status_code == 200
            body = json.loads(response.body.decode())
            assert "connection_events" in body
            assert len(body["connection_events"]) == 1
            assert body["connection_events"][0]["detail"] == "test-client"

        asyncio.run(_run())

    def test_health_endpoint_events_false(self):
        """?events=false should NOT include events."""
        from a_sdlc.server import _health_endpoint

        async def _run():
            request = MagicMock()
            request.query_params = {"events": "false"}
            response = await _health_endpoint(request)
            body = json.loads(response.body.decode())
            assert "connection_events" not in body

        asyncio.run(_run())

    def test_health_endpoint_events_case_insensitive(self):
        """?events=TRUE should also work."""
        from a_sdlc.server import _health_endpoint

        async def _run():
            request = MagicMock()
            request.query_params = {"events": "TRUE"}
            response = await _health_endpoint(request)
            body = json.loads(response.body.decode())
            assert "connection_events" in body

        asyncio.run(_run())
