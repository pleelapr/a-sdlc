"""Tests for the Health Dashboard UI.

Covers:
- GET /health route returns 200 with correct template context
- WebSocket /ws/health accepts connections and sends health updates
- Health nav link present in rendered HTML
- HealthDataProvider snapshot
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from a_sdlc.storage import FileStorage

# Only run if fastapi is installed
pytest.importorskip("fastapi")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileStorage(base_path=Path(tmpdir))
        yield storage


@pytest.fixture
def storage_with_project(temp_storage):
    """Create storage with a test project."""
    temp_storage.create_project("test-proj", "Test Project")
    return temp_storage


@pytest.fixture
def client(storage_with_project, monkeypatch):
    """Create TestClient with mocked storage pointing at a real project."""
    from starlette.testclient import TestClient

    import a_sdlc.ui as ui_module
    from a_sdlc.ui import app

    monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)
    return TestClient(app)


@pytest.fixture
def client_no_project(temp_storage, monkeypatch):
    """Create a test client with no project configured."""
    from starlette.testclient import TestClient

    import a_sdlc.ui as ui_module
    from a_sdlc.ui import app

    monkeypatch.setattr(ui_module, "get_storage", lambda: temp_storage)
    return TestClient(app)


@pytest.fixture
def fresh_provider():
    """Return a fresh HealthDataProvider instance."""
    from a_sdlc.ui import HealthDataProvider

    return HealthDataProvider()


# =============================================================================
# HealthDataProvider Unit Tests
# =============================================================================


class TestHealthDataProvider:
    """Test the HealthDataProvider class."""

    def test_snapshot_returns_required_keys(self, fresh_provider):
        """Snapshot dict contains all expected top-level keys."""
        snap = fresh_provider.snapshot()
        assert snap["type"] == "health_update"
        assert "status" in snap
        assert "status_label" in snap
        assert "status_detail" in snap
        assert "metrics" in snap

    def test_snapshot_metrics_structure(self, fresh_provider):
        """Metrics dict contains uptime, memory, connections, errors."""
        metrics = fresh_provider.snapshot()["metrics"]
        assert "uptime" in metrics
        assert "memory_mb" in metrics
        assert "active_connections" in metrics
        assert "error_count" in metrics

    def test_healthy_status_when_no_errors(self, fresh_provider):
        """Status is 'healthy' when no errors are recorded."""
        snap = fresh_provider.snapshot()
        assert snap["status"] == "healthy"
        assert snap["status_label"] == "Healthy"

    def test_ws_connection_tracking(self, fresh_provider):
        """WebSocket connections are tracked and removed correctly."""
        mock_ws = MagicMock()
        fresh_provider.add_ws(mock_ws)
        assert len(fresh_provider.ws_connections) == 1

        fresh_provider.remove_ws(mock_ws)
        assert len(fresh_provider.ws_connections) == 0

    def test_remove_unknown_ws_is_noop(self, fresh_provider):
        """Removing an unknown WebSocket does not raise."""
        mock_ws = MagicMock()
        fresh_provider.remove_ws(mock_ws)  # Should not raise


# =============================================================================
# _format_uptime Unit Tests
# =============================================================================


class TestFormatUptime:
    """Test the _format_uptime helper."""

    def test_seconds(self):
        from a_sdlc.ui import _format_uptime

        assert _format_uptime(45) == "45s"

    def test_minutes(self):
        from a_sdlc.ui import _format_uptime

        assert _format_uptime(125) == "2m 5s"

    def test_hours(self):
        from a_sdlc.ui import _format_uptime

        assert _format_uptime(3661) == "1h 1m"

    def test_days(self):
        from a_sdlc.ui import _format_uptime

        assert _format_uptime(90000) == "1d 1h"


# =============================================================================
# Health Route Tests
# =============================================================================


class TestHealthRoute:
    """Test the GET /health route."""

    def test_health_returns_200(self, client):
        """Health page returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_contains_status_banner(self, client):
        """Health page renders the status banner."""
        response = client.get("/health")
        assert "health-status-banner" in response.text
        assert "Server Status:" in response.text

    def test_health_contains_metrics_cards(self, client):
        """Health page renders all four metrics cards."""
        response = client.get("/health")
        assert "metric-uptime" in response.text
        assert "metric-memory" in response.text
        assert "metric-connections" in response.text
        assert "metric-errors" in response.text

    def test_health_contains_websocket_script(self, client):
        """Health page includes the WebSocket client script."""
        response = client.get("/health")
        assert "/ws/health" in response.text
        assert "connectWebSocket" in response.text

    def test_health_works_without_project(self, client_no_project):
        """Health page works even when no project is configured."""
        response = client_no_project.get("/health")
        assert response.status_code == 200
        assert "Health Dashboard" in response.text


# =============================================================================
# Health Nav Link Tests
# =============================================================================


class TestHealthNavLink:
    """Test that Health link appears in navigation."""

    def test_health_link_in_nav_with_project(self, client):
        """Health nav link is present when project exists."""
        response = client.get("/projects/test-proj")
        assert response.status_code == 200
        assert 'href="/health"' in response.text
        assert "Health" in response.text

    def test_health_link_in_nav_without_project(self, client_no_project):
        """Health nav link is present even without a project."""
        response = client_no_project.get("/health")
        assert response.status_code == 200
        assert 'href="/health"' in response.text

    def test_health_link_active_class(self, client):
        """Health link gets 'active' class when on health page."""
        response = client.get("/health")
        assert response.status_code == 200
        assert 'class="active"' in response.text


# =============================================================================
# WebSocket /ws/health Tests
# =============================================================================


class TestHealthWebSocket:
    """Test the /ws/health WebSocket endpoint."""

    def test_websocket_connect_and_receive(self, client):
        """WebSocket connection is accepted and sends initial health snapshot."""
        with client.websocket_connect("/ws/health") as ws:
            data = ws.receive_json()
            assert data["type"] == "health_update"
            assert "status" in data
            assert "metrics" in data

    def test_websocket_disconnect_cleanup(self, client):
        """After disconnect, connection is removed without errors."""
        with client.websocket_connect("/ws/health"):
            pass
        # No assertion on internal state -- verifies no exception

    def test_websocket_sends_periodic_updates(self, client):
        """WebSocket sends updates on subsequent receives (simulating timeout)."""
        with client.websocket_connect("/ws/health") as ws:
            # First message is the initial snapshot
            first = ws.receive_json()
            assert first["type"] == "health_update"

            # Send a ping to trigger the next update (simulates timeout path)
            ws.send_text("ping")
            second = ws.receive_json()
            assert second["type"] == "health_update"
